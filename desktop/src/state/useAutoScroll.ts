// Keep a scrollable transcript pinned to the bottom as content streams — but only
// when the user is already near the bottom, so scrolling up to read isn't yanked back.
// Exposes a jump-to-latest affordance for when they've scrolled away.

import { type DependencyList, useCallback, useEffect, useRef, useState } from "react";

export interface ScrollMetrics {
  scrollTop: number;
  scrollHeight: number;
  clientHeight: number;
}

// Whether the viewport is within `threshold` px of the bottom.
export function isNearBottom(m: ScrollMetrics, threshold = 80): boolean {
  return m.scrollHeight - m.scrollTop - m.clientHeight <= threshold;
}

export function useAutoScroll<T extends HTMLElement>(deps: DependencyList) {
  const ref = useRef<T | null>(null);
  const [showJump, setShowJump] = useState(false);

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "auto") => {
    const el = ref.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior });
  }, []);

  // Follow new content when already near the bottom.
  useEffect(() => {
    const el = ref.current;
    if (el && isNearBottom(el)) scrollToBottom();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  // Track scroll position to toggle the jump affordance.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onScroll = () => setShowJump(!isNearBottom(el));
    el.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  const jumpToBottom = useCallback(() => scrollToBottom("smooth"), [scrollToBottom]);

  return { ref, showJump, jumpToBottom };
}
