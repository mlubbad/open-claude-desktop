import { type RefObject, useLayoutEffect } from "react";

// Keep an absolutely-positioned menu / submenu / popover inside the viewport.
//
// Every menu in the app is a `position: absolute` panel with a HARDCODED side (left/right,
// up/down) chosen at author time — so a menu whose trigger sits near the "wrong" edge
// overflows and gets clipped, and a submenu that always opens (say) left clips when there's
// no room on the left. This hook fixes all of that in one place: while the panel is open it
// measures its rect and nudges it back on-screen with a transform. It re-measures on
// window resize, on any ancestor scroll, AND on panel size changes (a ResizeObserver) —
// menus grow after opening (async provider/model lists, flyout content), and a grown
// bottom-anchored panel extends upward past the viewport top. It is ADDITIVE — a menu that
// already fits is left untouched, so the existing CSS positioning still drives the default
// placement. A panel taller than the viewport itself (no translate can fix that) is capped
// to the viewport and scrolls internally; author max-heights tighter than the viewport are
// respected untouched.
//
// Pass the panel's ref (most menus already keep one for outside-click detection) and the
// open flag: `useMenuFit(ref, open)`.
export function useMenuFit(ref: RefObject<HTMLElement | null>, open: boolean, margin = 8): void {
  useLayoutEffect(() => {
    const el = ref.current;
    if (!open || !el) return;

    // Once capped, the panel stays capped for this open (tracking the viewport), so the
    // measure loop is idempotent — re-writing the same max-height doesn't retrigger the
    // ResizeObserver, while resetting it every pass would oscillate forever.
    let capped = false;

    const measure = () => {
      el.style.transform = "none"; // reset before measuring so we read the natural rect
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const cap = vh - margin * 2;
      if (capped) el.style.maxHeight = `${cap}px`;
      let r = el.getBoundingClientRect();
      if (!capped && r.height > cap) {
        capped = true;
        el.style.maxHeight = `${cap}px`;
        el.style.overflowY = "auto";
        r = el.getBoundingClientRect();
      }
      let dx = 0;
      let dy = 0;
      // Pull back from the right/bottom first, then make sure that didn't push the
      // opposite edge off-screen (a panel bigger than the viewport pins to the top-left).
      if (r.right > vw - margin) dx = vw - margin - r.right;
      if (r.left + dx < margin) dx = margin - r.left;
      if (r.bottom > vh - margin) dy = vh - margin - r.bottom;
      if (r.top + dy < margin) dy = margin - r.top;
      el.style.transform =
        dx || dy ? `translate(${Math.round(dx)}px, ${Math.round(dy)}px)` : "none";
    };

    measure();
    // Guarded: jsdom (tests) has no ResizeObserver; every shipped webview does.
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    ro?.observe(el);
    window.addEventListener("resize", measure);
    // Capture-phase scroll catches scrolling in any ancestor (sidebar, transcript, page).
    window.addEventListener("scroll", measure, true);
    return () => {
      ro?.disconnect();
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
      // Clear our inline styles so a re-open starts from the stylesheet's layout.
      el.style.transform = "none";
      el.style.maxHeight = "";
      el.style.overflowY = "";
    };
  }, [ref, open, margin]);
}
