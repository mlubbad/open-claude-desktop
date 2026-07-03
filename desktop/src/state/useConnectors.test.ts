import { describe, expect, it } from "vitest";

import { toggleId } from "./useConnectors";

describe("toggleId", () => {
  it("adds an id that is absent", () => {
    expect(toggleId([], "a")).toEqual(["a"]);
    expect(toggleId(["a"], "b")).toEqual(["a", "b"]);
  });

  it("removes an id that is present", () => {
    expect(toggleId(["a", "b"], "a")).toEqual(["b"]);
    expect(toggleId(["a"], "a")).toEqual([]);
  });
});
