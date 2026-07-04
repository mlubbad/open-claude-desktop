import { describe, expect, it } from "vitest";

import { isNearBottom } from "./useAutoScroll";

describe("isNearBottom", () => {
  it("is true at the very bottom", () => {
    expect(isNearBottom({ scrollTop: 900, scrollHeight: 1000, clientHeight: 100 })).toBe(true);
  });

  it("is true within the threshold", () => {
    // 1000 - 850 - 100 = 50 <= 80
    expect(isNearBottom({ scrollTop: 850, scrollHeight: 1000, clientHeight: 100 })).toBe(true);
  });

  it("is false when scrolled well up", () => {
    // 1000 - 200 - 100 = 700 > 80
    expect(isNearBottom({ scrollTop: 200, scrollHeight: 1000, clientHeight: 100 })).toBe(false);
  });

  it("respects a custom threshold", () => {
    const m = { scrollTop: 700, scrollHeight: 1000, clientHeight: 100 }; // gap = 200
    expect(isNearBottom(m, 80)).toBe(false);
    expect(isNearBottom(m, 250)).toBe(true);
  });
});
