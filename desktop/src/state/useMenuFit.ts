import { type RefObject, useLayoutEffect } from "react";

// Keep an absolutely-positioned menu / submenu / popover inside the viewport.
//
// Every menu in the app is a `position: absolute` panel with a HARDCODED side (left/right,
// up/down) chosen at author time — so a menu whose trigger sits near the "wrong" edge
// overflows and gets clipped, and a submenu that always opens (say) left clips when there's
// no room on the left. This hook fixes all of that in one place: while the panel is open it
// measures its rect and nudges it back on-screen with a transform (re-measuring on
// resize/scroll). It is ADDITIVE — a menu that already fits is left untouched, so the
// existing CSS positioning still drives the default placement.
//
// Pass the panel's ref (most menus already keep one for outside-click detection) and the
// open flag: `useMenuFit(ref, open)`.
export function useMenuFit(ref: RefObject<HTMLElement | null>, open: boolean, margin = 8): void {
  useLayoutEffect(() => {
    const el = ref.current;
    if (!open || !el) return;

    const measure = () => {
      el.style.transform = "none"; // reset before measuring so we read the natural rect
      const r = el.getBoundingClientRect();
      const vw = window.innerWidth;
      const vh = window.innerHeight;
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
    window.addEventListener("resize", measure);
    // Capture-phase scroll catches scrolling in any ancestor (sidebar, transcript, page).
    window.addEventListener("scroll", measure, true);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [ref, open, margin]);
}
