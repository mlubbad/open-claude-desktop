// @vitest-environment jsdom
import { act, render } from "@testing-library/react";
import { createElement as h, useRef } from "react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

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

  it("caps a panel taller than the viewport and makes it scrollable", () => {
    // 900px of menu in a 768px viewport can never fit by moving alone: it must be
    // capped to vh - 2*margin, scroll internally, and be pulled back below the top.
    const { getByTestId } = render(
      h(Menu, { rect: { left: 100, right: 300, top: -100, bottom: 800, height: 900 } }),
    );
    const el = getByTestId("menu");
    expect(el.style.maxHeight).toBe("752px"); // 768 - 2*8
    expect(el.style.overflowY).toBe("auto");
    expect(el.style.transform).toBe("translate(0px, 108px)"); // top -100 → margin 8
  });

  it("leaves a shorter-than-viewport panel's max-height alone", () => {
    // The author stylesheet may cap menus tighter than the viewport (e.g. the model
    // picker's 50vh) — the hook must not override that when the panel already fits.
    const { getByTestId } = render(h(Menu, { rect: { left: 100, right: 300, top: 100, bottom: 400, height: 300 } }));
    expect(getByTestId("menu").style.maxHeight).toBe("");
  });
});

// Menus load content AFTER opening (the model picker fetches its provider list, flyouts
// fill in async) — the panel then grows in place and can push past the viewport edge.
// A ResizeObserver on the panel must re-clamp on any size change, not just window events.
describe("useMenuFit — async content growth", () => {
  class FakeResizeObserver {
    static instances: FakeResizeObserver[] = [];
    cb: ResizeObserverCallback;
    observed: Element[] = [];
    constructor(cb: ResizeObserverCallback) {
      this.cb = cb;
      FakeResizeObserver.instances.push(this);
    }
    observe(el: Element) {
      this.observed.push(el);
    }
    unobserve() {}
    disconnect() {
      this.observed = [];
    }
    trigger() {
      this.cb([], this as unknown as ResizeObserver);
    }
  }

  beforeEach(() => {
    FakeResizeObserver.instances = [];
    (globalThis as { ResizeObserver?: unknown }).ResizeObserver = FakeResizeObserver;
  });
  afterEach(() => {
    delete (globalThis as { ResizeObserver?: unknown }).ResizeObserver;
  });

  it("observes the open panel and re-clamps when it grows past the top", () => {
    const rect = { left: 100, right: 300, top: 100, bottom: 300 };
    const { getByTestId } = render(h(Menu, { rect }));
    expect(getByTestId("menu").style.transform).toBe("none");

    const ro = FakeResizeObserver.instances.at(-1);
    expect(ro?.observed).toContain(getByTestId("menu"));

    act(() => {
      // A bottom-anchored menu that grows extends UPWARD: top goes past the viewport.
      rect.top = -140;
      ro?.trigger();
    });
    expect(getByTestId("menu").style.transform).toBe("translate(0px, 148px)"); // 8 - (-140)
  });

  it("disconnects the observer when the menu closes", () => {
    const { unmount } = render(h(Menu, { rect: { left: 0, right: 100, top: 0, bottom: 100 } }));
    const ro = FakeResizeObserver.instances.at(-1);
    expect(ro?.observed.length).toBe(1);
    unmount();
    expect(ro?.observed.length).toBe(0);
  });
});
