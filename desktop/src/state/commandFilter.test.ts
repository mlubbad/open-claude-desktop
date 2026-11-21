import { describe, expect, it } from "vitest";

import { filterByLabel, subsequence } from "./commandFilter";

describe("command filter", () => {
  it("subsequence matches in order, not contiguous", () => {
    expect(subsequence("new chat", "nc")).toBe(true);
    expect(subsequence("new chat", "chat")).toBe(true);
    expect(subsequence("new chat", "xz")).toBe(false);
    expect(subsequence("new chat", "")).toBe(true);
  });

  it("filterByLabel is case-insensitive and returns all on empty query", () => {
    const items = [{ label: "New chat" }, { label: "Settings" }, { label: "Connectors" }];
    expect(filterByLabel(items, "")).toHaveLength(3);
    expect(filterByLabel(items, "set").map((i) => i.label)).toEqual(["Settings"]);
    expect(filterByLabel(items, "cn").map((i) => i.label)).toEqual(["Connectors"]);
  });
});
