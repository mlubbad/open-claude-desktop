// @vitest-environment jsdom
// P0-3: plugin enablement must survive a reload. Previously plain useState — every
// app start silently disabled every plugin.
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", () => ({
  plugins: {
    list: vi.fn(async () => [{ name: "alpha" }, { name: "beta" }]),
    marketplace: vi.fn(async () => []),
    sources: vi.fn(async () => ({ allow_remote: false, sources: [] })),
  },
}));

import { usePlugins } from "./usePlugins";

describe("usePlugins enablement persistence", () => {
  beforeEach(() => localStorage.clear());

  it("persists toggles and restores them on a fresh mount", async () => {
    const h1 = renderHook(() => usePlugins());
    await waitFor(() => expect(h1.result.current.installed).toHaveLength(2));
    act(() => h1.result.current.toggle("alpha"));
    expect(JSON.parse(localStorage.getItem("ocd.enabledPlugins")!)).toEqual(["alpha"]);
    h1.unmount();

    // A "reload": new mount reads the persisted set before any fetch resolves.
    const h2 = renderHook(() => usePlugins());
    expect(h2.result.current.enabled).toEqual(["alpha"]);
    await waitFor(() => expect(h2.result.current.installed).toHaveLength(2));
    expect(h2.result.current.enabled).toEqual(["alpha"]); // survives the reconcile
  });

  it("drops persisted ids for plugins that are no longer installed", async () => {
    localStorage.setItem("ocd.enabledPlugins", JSON.stringify(["ghost", "beta"]));
    const h = renderHook(() => usePlugins());
    await waitFor(() => expect(h.result.current.enabled).toEqual(["beta"]));
  });

  it("treats corrupt storage as empty", async () => {
    localStorage.setItem("ocd.enabledPlugins", "{not json");
    const h = renderHook(() => usePlugins());
    expect(h.result.current.enabled).toEqual([]);
    await waitFor(() => expect(h.result.current.installed).toHaveLength(2));
  });
});
