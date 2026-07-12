// @vitest-environment jsdom
// P1-5: an incognito chat never persists — no conversation row is created and
// nothing is saved; a normal chat still creates-on-first-send.
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const createSpy = vi.fn(async (_pid: string, _goal: string) => ({ id: "c1" }));
const saveSpy = vi.fn(async () => ({}));
const streamSpy = vi.fn((_req: object, onEvent: (ev: object) => void) => {
  // Finish the turn immediately so the store never stays busy between tests.
  onEvent({ type: "done" });
  return new AbortController();
});

vi.mock("../api/client", () => ({
  GENERAL_PROJECT: "general",
  conversations: {
    create: (pid: string, goal: string) => createSpy(pid, goal),
    save: () => saveSpy(),
    listAll: vi.fn(async () => []),
    generateTitle: vi.fn(async () => ({ title: "" })),
    rename: vi.fn(async () => ({})),
    get: vi.fn(async () => ({ messages: [] })),
  },
  streamTurn: (req: object, onEvent: (ev: object) => void) => streamSpy(req, onEvent),
  replyPermission: vi.fn(async () => ({ resolved: true, decision: "approve" })),
}));

import { useConversations } from "./useConversations";

const config = { model: "m", projectId: null };

describe("incognito chats", () => {
  beforeEach(() => {
    createSpy.mockClear();
    saveSpy.mockClear();
    streamSpy.mockClear();
  });

  it("incognito send streams the turn but creates/saves NOTHING", async () => {
    const h = renderHook(() => useConversations(config, true));
    await act(async () => {
      await h.result.current.send("secret question");
    });
    expect(streamSpy).toHaveBeenCalledTimes(1);
    expect(createSpy).not.toHaveBeenCalled();
    expect(saveSpy).not.toHaveBeenCalled();
    act(() => h.result.current.newChat()); // leaves no trace behind
  });

  it("a normal send still creates the conversation row", async () => {
    const h = renderHook(() => useConversations(config, false));
    await act(async () => {
      await h.result.current.send("normal question");
    });
    expect(createSpy).toHaveBeenCalledTimes(1);
    expect(streamSpy).toHaveBeenCalled();
  });
});
