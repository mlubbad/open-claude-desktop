// @vitest-environment jsdom
import { act, render } from "@testing-library/react";
import { createElement as h, useRef } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { useMenuFit } from "./useMenuFit";

// A tiny host that drives useMenuFit and lets a test inject the panel's measured rect.
function Menu({ rect }: { rect: Partial<DOMRect> }) {
  const ref = useRef<HTMLDivElement | null>(null);
  useMenuFit(ref, true);
  const setNode = (n: HTMLDivElement | null) => {
    ref.current = n;
    if (n) {
      const base = { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0 };
      n.getBoundingClientRect = () => ({ ...base, ...rect, toJSON() {} }) as DOMRect;
    }
  };
  return h("div", { ref: setNode, "data-testid": "menu" });
}

afterEach(() => {
  window.innerWidth = 1024;
  window.innerHeight = 768;
});

describe("useMenuFit", () => {
  it("leaves an on-screen menu untouched", () => {
    const { getByTestId } = render(h(Menu, { rect: { left: 100, right: 300, top: 100, bottom: 300 } }));
    expect(getByTestId("menu").style.transform).toBe("none");
  });

  it("pulls a right-overflowing menu back on-screen", () => {
    // Panel's right edge at 1200 > innerWidth(1024) - margin(8) → shift left by 184.
    const { getByTestId } = render(h(Menu, { rect: { left: 900, right: 1200, top: 100, bottom: 300 } }));
    expect(getByTestId("menu").style.transform).toBe("translate(-184px, 0px)");
  });

  it("pulls a bottom-overflowing menu up", () => {
    const { getByTestId } = render(h(Menu, { rect: { left: 100, right: 300, top: 700, bottom: 860 } }));
    // bottom 860 > innerHeight(768) - 8 → shift up by 100.
    expect(getByTestId("menu").style.transform).toBe("translate(0px, -100px)");
  });

  it("re-clamps on window resize", () => {
    const { getByTestId } = render(h(Menu, { rect: { left: 100, right: 300, top: 100, bottom: 300 } }));
    expect(getByTestId("menu").style.transform).toBe("none");
    act(() => {
      window.innerWidth = 250; // now the right edge (300) overflows
      window.dispatchEvent(new Event("resize"));
    });
    expect(getByTestId("menu").style.transform).toBe("translate(-58px, 0px)"); // 250-8-300
  });
});
