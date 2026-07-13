// @vitest-environment jsdom
// retryLast optionally swaps model/provider for a single regeneration ("regenerate with
// a different model"), leaving every other turn parameter untouched.
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

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
