// Keep a streaming transcript pinned to the bottom as content arrives — but only when
// the user is already at the bottom, so scrolling up to read isn't yanked back — and show
// a "jump to latest" affordance whenever they've scrolled away.
//
// "Am I at the bottom?" is answered with an IntersectionObserver watching a 1px sentinel
// at the very END of the content, NOT with scroll-math. Scroll-math (scrollHeight -
// scrollTop - clientHeight) mis-fires at sub-pixel edges and when content grows, which is
// exactly why the button could linger at the bottom. With the sentinel, the button is
// shown precisely when the sentinel is off-screen and hidden the instant it scrolls into
// view — so it always disappears once you reach the end. (This is the widely-used pattern
// for chat "scroll to bottom" buttons.)

import { type DependencyList, useCallback, useEffect, useRef, useState } from "react";

export interface ScrollMetrics {
  scrollTop: number;
  scrollHeight: number;
  clientHeight: number;
}

// Whether the viewport is within `threshold` px of the bottom. Kept as a pure, exported
// helper (used by tests and as a fallback where no sentinel exists).
export function isNearBottom(m: ScrollMetrics, threshold = 80): boolean {
  return m.scrollHeight - m.scrollTop - m.clientHeight <= threshold;
}

export function useAutoScroll<T extends HTMLElement>(deps: DependencyList) {
  const ref = useRef<T | null>(null); // the scroll container
  const bottomRef = useRef<HTMLDivElement | null>(null); // sentinel at the end of content
  const atBottom = useRef(true); // live "are we at the bottom" (read by the follow effect)
  const [showJump, setShowJump] = useState(false);

  // Observe the sentinel inside the scroll container: intersecting == at the bottom.
  useEffect(() => {
    const root = ref.current;
    const sentinel = bottomRef.current;
    if (!root || !sentinel || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      ([entry]) => {
        atBottom.current = entry.isIntersecting;
        setShowJump(!entry.isIntersecting);
      },
      // A little bottom rootMargin treats "almost there" as bottom, so the button doesn't
      // flicker on the final pixel while streaming.
      { root, rootMargin: "0px 0px 48px 0px", threshold: 0 },
    );
    io.observe(sentinel);
    return () => io.disconnect();
  }, []);

  // Follow new content only when already pinned to the bottom (instant, not smooth, so a
  // streaming reply doesn't animate on every token).
  useEffect(() => {
    if (atBottom.current) bottomRef.current?.scrollIntoView({ block: "end" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  const jumpToBottom = useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, []);

  return { ref, bottomRef, showJump, jumpToBottom };
}
