// @vitest-environment jsdom
import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../api/client", () => ({
  isTauriShell: () => true,
  checkBackendHealth: vi.fn(),
}));
import { checkBackendHealth } from "../api/client";
import { useBackendHealth } from "./useBackendHealth";

describe("useBackendHealth", () => {
  it("flips to down after two consecutive misses and recovers on success", async () => {
    vi.mocked(checkBackendHealth).mockResolvedValue(false);
    const { result } = renderHook(() => useBackendHealth(5));
    // One miss is tolerated (rides out a blip); the second flips it down.
    await waitFor(() => expect(result.current).toBe(false));
    vi.mocked(checkBackendHealth).mockResolvedValue(true);
    await waitFor(() => expect(result.current).toBe(true)); // recovers immediately
  });
});
