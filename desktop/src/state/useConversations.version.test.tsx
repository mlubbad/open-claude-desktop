// @vitest-environment jsdom
// F-16: a save carries the last-seen version; on a 409 (another writer got there first)
// the hook resyncs to the server's version and retries once so this window's transcript
// still persists.
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { ApiError, saveSpy, getSpy } = vi.hoisted(() => {
  class ApiError extends Error {
    status: number;
    constructor(status: number, detail: string) {
      super(`${status}: ${detail}`);
      this.status = status;
    }
  }
  const saveSpy = vi.fn(async (_p: string, _c: string, _m: unknown, _t: unknown, version?: number) => {
    if (saveSpy.mock.calls.length === 1) throw new ApiError(409, "conflict"); // first call only
    return { id: "c1", messages: [], version: (version ?? 0) + 1 };
  });
  const getSpy = vi.fn(async (_p: string, _c: string) => ({ id: "c1", messages: [], version: 7 }));
  return { ApiError, saveSpy, getSpy };
});

vi.mock("../api/client", () => ({
  ApiError,
  GENERAL_PROJECT: "general",
  conversations: {
    create: vi.fn(async () => ({ id: "c1", version: 1 })),
    save: (p: string, c: string, m: unknown, t: unknown, v?: number) => saveSpy(p, c, m, t, v),
    get: (p: string, c: string) => getSpy(p, c),
    listAll: vi.fn(async () => []),
    generateTitle: vi.fn(async () => ({ title: "" })),
    rename: vi.fn(async () => ({})),
  },
  streamTurn: vi.fn(() => new AbortController()),
  replyPermission: vi.fn(async () => ({ resolved: true, decision: "approve" })),
}));

import { useConversations } from "./useConversations";

const config = { model: "m", projectId: null };

describe("optimistic-version save (F-16)", () => {
  beforeEach(() => {
    saveSpy.mockClear();
    getSpy.mockClear();
  });

  it("retries with the resynced version after a 409", async () => {
    const h = renderHook(() => useConversations(config, false));
    await act(async () => {
      await h.result.current.openConversation("c1", "general"); // seeds version 7
    });
    await act(async () => {
      await h.result.current.send("hi"); // fires an eager save that 409s, then retries
    });
    await waitFor(() => expect(saveSpy).toHaveBeenCalledTimes(2));
    // The retry sent the version we refetched (7), not the stale/undefined one.
    expect(saveSpy.mock.calls[1][4]).toBe(7);
  });
});
