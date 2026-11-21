// @vitest-environment jsdom
import { act, render } from "@testing-library/react";
import { createElement as h } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { isNearBottom, useAutoScroll } from "./useAutoScroll";

// Capture the IntersectionObserver callback so a test can drive the sentinel in/out of view.
let ioCb: ((entries: Array<{ isIntersecting: boolean }>) => void) | null = null;

beforeEach(() => {
  ioCb = null;
  class MockIO {
    constructor(cb: (e: Array<{ isIntersecting: boolean }>) => void) {
      ioCb = cb;
    }
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  vi.stubGlobal("IntersectionObserver", MockIO);
  // jsdom doesn't implement scrollIntoView.
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function Host() {
  const s = useAutoScroll<HTMLDivElement>([0]);
  return h(
    "div",
    { ref: s.ref, "data-testid": "root", "data-jump": s.showJump ? "yes" : "no" },
    h("div", { ref: s.bottomRef, "data-testid": "sentinel" }),
  );
}

describe("useAutoScroll — jump affordance", () => {
  it("hides at the bottom and shows once the bottom sentinel scrolls off-screen", () => {
    const { getByTestId } = render(h(Host));
    // Sentinel visible (at bottom) → no button.
    act(() => ioCb?.([{ isIntersecting: true }]));
    expect(getByTestId("root").dataset.jump).toBe("no");
    // User scrolls up → sentinel leaves the viewport → button appears.
    act(() => ioCb?.([{ isIntersecting: false }]));
    expect(getByTestId("root").dataset.jump).toBe("yes");
    // Back at the bottom → sentinel visible again → button hides.
    act(() => ioCb?.([{ isIntersecting: true }]));
    expect(getByTestId("root").dataset.jump).toBe("no");
  });
});

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
