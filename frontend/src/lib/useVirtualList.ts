"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Minimal fixed-row-height virtualization for a single scrollable list --
 * hand-rolled rather than pulling in react-window/@tanstack/react-virtual
 * (consistent with this project's existing preference for small
 * dependency-free implementations, e.g. raw CDP instead of Playwright for
 * screenshot verification), since every consumer of this hook is a
 * uniform-height row list.
 *
 * Renders only the rows within the scrolled viewport (+ overscan) instead
 * of mounting all of them. For the draft player pool specifically, that's
 * the difference between ~20 mounted rows (and ~20 concurrent avatar
 * image loads) and the full undrafted pool (thousands) -- confirmed via a
 * live MutationObserver check to be a real, large source of the reported
 * "draft page is unreasonably slow" bug, separate from (and in addition
 * to) the timer-driven re-render issue PickCountdown.tsx fixes.
 *
 * `resetKey` -- pass whatever should snap scroll back to the top (e.g. a
 * search query or position filter). Deliberately NOT the items array
 * itself: `available`/`filteredPlayers` also changes on every ~5s poll
 * once another team picks, and resetting scroll on every one of those
 * would yank a user back to the top of the list while they're mid-browse.
 */
export function useVirtualList<T>(items: T[], rowHeight: number, resetKey: unknown, overscan = 6) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(600);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const measure = () => setViewportHeight(el.clientHeight);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const onScroll = useCallback(() => {
    if (containerRef.current) setScrollTop(containerRef.current.scrollTop);
  }, []);

  // eslint-disable-next-line react-hooks/exhaustive-deps -- resetKey is
  // intentionally the only real dependency; see the doc comment above.
  useEffect(() => {
    if (containerRef.current) containerRef.current.scrollTop = 0;
    setScrollTop(0);
  }, [resetKey]);

  const start = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan);
  const visibleCount = Math.ceil(viewportHeight / rowHeight) + overscan * 2;
  const end = Math.min(items.length, start + visibleCount);

  return {
    containerRef,
    onScroll,
    visibleItems: items.slice(start, end),
    startIndex: start,
    paddingTop: start * rowHeight,
    paddingBottom: Math.max(0, (items.length - end) * rowHeight),
  };
}
