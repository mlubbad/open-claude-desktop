import { describe, expect, it } from "vitest";

import { DEFAULT_PICKER_COUNT, pickerModels } from "./modelMeta";

const CATALOG = ["m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8"];

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
