// @vitest-environment jsdom
// branchAt forks the open conversation at a message index and navigates to the new
// branch; with no conversation open it's a safe no-op.
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const branchSpy = vi.fn(async (_pid: string, _cid: string, _i: number) => ({
  id: "branch1",
  messages: [{ role: "user", content: "q1", kind: "user" }],
}));
const getSpy = vi.fn(async (_pid: string, cid: string) => ({
  id: cid,
  messages: [{ role: "user", content: "q1", kind: "user" }],
}));

vi.mock("../api/client", () => ({
  GENERAL_PROJECT: "general",
  conversations: {
    branch: (pid: string, cid: string, i: number) => branchSpy(pid, cid, i),
    get: (pid: string, cid: string) => getSpy(pid, cid),
    listAll: vi.fn(async () => []),
    save: vi.fn(async () => ({})),
    generateTitle: vi.fn(async () => ({ title: "" })),
    rename: vi.fn(async () => ({})),
  },
  streamTurn: vi.fn(() => new AbortController()),
  replyPermission: vi.fn(async () => ({ resolved: true, decision: "approve" })),
}));

import { useConversations } from "./useConversations";

const config = { model: "m", projectId: null };

describe("branchAt", () => {
  beforeEach(() => {
    branchSpy.mockClear();
    getSpy.mockClear();
  });

  it("forks the open conversation at an index and opens the new branch", async () => {
    const h = renderHook(() => useConversations(config, false));
    await act(async () => {
      await h.result.current.openConversation("src", "general");
    });
    await act(async () => {
      const ok = await h.result.current.branchAt(1);
      expect(ok).toBe(true);
    });
    expect(branchSpy).toHaveBeenCalledWith("general", "src", 1);
    await waitFor(() => expect(h.result.current.current?.cid).toBe("branch1"));
  });

  it("is a no-op with no conversation open", async () => {
    const h = renderHook(() => useConversations(config, false));
    await act(async () => {
      const ok = await h.result.current.branchAt(0);
      expect(ok).toBe(false);
    });
    expect(branchSpy).not.toHaveBeenCalled();
  });
});
