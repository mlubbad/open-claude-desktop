import { describe, expect, it } from "vitest";

import { DEFAULT_PICKER_COUNT, effectiveCatalog, pickerModels } from "./modelMeta";

const CATALOG = ["m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8"];

describe("effectiveCatalog", () => {
  it("returns the built-in catalog unchanged with no customisation", () => {
    expect(effectiveCatalog(["a", "b"])).toEqual(["a", "b"]);
    expect(effectiveCatalog(["a", "b"], [], [])).toEqual(["a", "b"]);
  });

  it("puts user-added models first, then the catalog", () => {
    expect(effectiveCatalog(["a", "b"], ["z"])).toEqual(["z", "a", "b"]);
  });

  it("removes hidden models (built-in or custom)", () => {
    expect(effectiveCatalog(["a", "b", "c"], ["z"], ["b", "z"])).toEqual(["a", "c"]);
  });

  it("collapses duplicates and trims blanks", () => {
    expect(effectiveCatalog(["a", "a", "b"], ["a", " "], [])).toEqual(["a", "b"]);
    expect(effectiveCatalog([" a ", "b"])).toEqual(["a", "b"]);
  });

  it("a custom model flows into the picker's default newest-few", () => {
    // Added model sits at the front, so it appears without an explicit selection.
    expect(pickerModels(effectiveCatalog(CATALOG, ["mine"]), undefined, "").slice(0, 1)).toEqual(["mine"]);
  });
});

describe("pickerModels", () => {
  it("defaults to the newest few when the user hasn't chosen", () => {
    expect(pickerModels(CATALOG, undefined, "m1")).toEqual(CATALOG.slice(0, DEFAULT_PICKER_COUNT));
    expect(pickerModels(CATALOG, [], "m1")).toEqual(CATALOG.slice(0, DEFAULT_PICKER_COUNT));
  });

  it("respects the user's selection, in catalog order", () => {
    expect(pickerModels(CATALOG, ["m7", "m2"], "m2")).toEqual(["m2", "m7"]);
  });

  it("always includes the currently-active model", () => {
    expect(pickerModels(CATALOG, ["m2"], "m8")).toEqual(["m2", "m8"]);
    expect(pickerModels(CATALOG, undefined, "m8")).toContain("m8");
  });

  it("ignores selected models that left the catalog and falls back if none remain", () => {
    expect(pickerModels(CATALOG, ["gone"], "m1")).toEqual(CATALOG.slice(0, DEFAULT_PICKER_COUNT));
  });

  it("handles a short catalog", () => {
    expect(pickerModels(["a", "b"], undefined, "a")).toEqual(["a", "b"]);
  });
});
