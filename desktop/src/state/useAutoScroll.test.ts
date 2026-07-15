// @vitest-environment jsdom
import { act, render } from "@testing-library/react";
import { createElement as h } from "react";
import { describe, expect, it } from "vitest";

import { isNearBottom, useAutoScroll } from "./useAutoScroll";

function mock(el: HTMLElement, m: Record<string, number>) {
  for (const [k, v] of Object.entries(m)) Object.defineProperty(el, k, { value: v, configurable: true });
  (el as unknown as { scrollTo: () => void }).scrollTo = () => {};
}

// Drives the hook and re-applies mocked scroll metrics on every render.
function Host({ n, sh }: { n: number; sh: number }) {
  const s = useAutoScroll<HTMLDivElement>([n]);
  return h("div", {
    "data-testid": "sc",
    "data-jump": s.showJump ? "yes" : "no",
    ref: (el: HTMLDivElement | null) => {
      s.ref.current = el;
      if (el) mock(el, { scrollTop: 900, scrollHeight: sh, clientHeight: 100 });
    },
  });
}

describe("useAutoScroll — jump affordance", () => {
  it("reveals the jump button when content grows below the fold (no scroll event)", () => {
    const { getByTestId, rerender } = render(h(Host, { n: 0, sh: 1000 }));
    // At the bottom (900+100 == 1000) → no jump arrow.
    expect(getByTestId("sc").dataset.jump).toBe("no");
    // A reply streams in: content height jumps to 2000 while scrollTop stays 900 → the
    // bottom is now far below the fold, so the arrow appears even without a scroll event.
    act(() => rerender(h(Host, { n: 1, sh: 2000 })));
    expect(getByTestId("sc").dataset.jump).toBe("yes");
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
