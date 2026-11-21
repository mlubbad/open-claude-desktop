// @vitest-environment jsdom
// P1-2: prompts from enabled+connected MCP servers become `/server:prompt` entries.
import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const promptsSpy = vi.fn(async (sid: string) => ({
  prompts: sid === "fs" ? [{ name: "summarize", description: "Summarize a file" }] : [],
}));

vi.mock("../api/client", () => ({
  mcp: { prompts: (sid: string) => promptsSpy(sid) },
}));

import { useMcpPrompts } from "./useMcpPrompts";

describe("useMcpPrompts", () => {
  it("namespaces prompts and only queries connected + enabled servers", async () => {
    const servers = [
      { id: "fs", status: "connected" },
      { id: "broken", status: "error" },      // never queried
      { id: "offswitch", status: "connected" }, // connected but not enabled
    ];
    const h = renderHook(() => useMcpPrompts(servers, ["fs", "broken"]));
    await waitFor(() =>
      expect(h.result.current).toEqual([
        { name: "fs:summarize", description: "Summarize a file", sid: "fs", prompt: "summarize" },
      ]));
    expect(promptsSpy).toHaveBeenCalledTimes(1);
    expect(promptsSpy).toHaveBeenCalledWith("fs");
  });

  it("is empty with no usable servers", () => {
    const h = renderHook(() => useMcpPrompts([], []));
    expect(h.result.current).toEqual([]);
  });
});
