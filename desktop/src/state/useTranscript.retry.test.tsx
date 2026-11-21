// @vitest-environment jsdom
// retryLast optionally swaps model/provider for a single regeneration ("regenerate with
// a different model"), leaving every other turn parameter untouched.
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// A stable snapshot — useSyncExternalStore requires getSnapshot to be cached.
const SNAP = {
  state: { messages: [], error: null, pendingApproval: null, artifactPanelId: null },
  busy: false,
};

vi.mock("./turnSessions", () => ({
  subscribe: () => () => {},
  getSnapshot: () => SNAP,
  retryActive: vi.fn(),
  sendActive: vi.fn(),
  editActive: vi.fn(),
  stopActive: vi.fn(),
  resolveApprovalActive: vi.fn(),
  markQuestionAnsweredActive: vi.fn(),
  setArtifactPanelActive: vi.fn(),
}));

import * as store from "./turnSessions";
import { useTranscript } from "./useTranscript";

const config = {
  model: "base-model",
  provider: "base-prov",
  effort: "High",
  projectId: "p1",
  options: { web_search: true },
};

describe("retryLast override", () => {
  it("swaps model+provider for this run but keeps the other turn params", () => {
    const h = renderHook(() => useTranscript(config));
    act(() => h.result.current.retryLast({ model: "other-model", provider: "openai" }));
    expect(store.retryActive).toHaveBeenCalledWith(
      expect.objectContaining({
        model: "other-model",
        provider: "openai",
        project_id: "p1",
        options: { web_search: true },
      }),
    );
  });

  it("without an override uses the conversation's own model", () => {
    const h = renderHook(() => useTranscript(config));
    act(() => h.result.current.retryLast());
    expect(store.retryActive).toHaveBeenLastCalledWith(
      expect.objectContaining({ model: "base-model", provider: "base-prov" }),
    );
  });
});

// The stale-config regression: a memoized message bubble keeps the SAME callback
// reference across renders (its comparator ignores callback identity), so a callback
// captured before a settings change must still submit with the NEW settings.
describe("retryLast reads the latest config (stale-closure fix)", () => {
  beforeEach(() => vi.mocked(store.retryActive).mockClear());

  it("a callback captured before a permission-mode change still uses the new mode", () => {
    const { result, rerender } = renderHook((c) => useTranscript(c), {
      initialProps: { ...config, permissionMode: "auto" },
    });
    const staleRetry = result.current.retryLast; // what a memoized bubble would hold
    rerender({ ...config, permissionMode: "strict" }); // user flips auto → strict
    expect(result.current.retryLast).toBe(staleRetry); // identity is stable (empty deps)
    act(() => staleRetry()); // invoke the OLD reference
    expect(store.retryActive).toHaveBeenLastCalledWith(
      expect.objectContaining({ permission_mode: "strict" }), // NOT the superseded "auto"
    );
  });
});
