"use client";

import { useEffect, useState } from "react";

/**
 * A pick's remaining time is a pure function of a fixed deadline
 * (current_pick_started_at + timer_seconds) vs "now" -- it never actually
 * needed to live in draft/[id]/page.tsx's own state. It used to: a
 * page-level `timeLeft` state ticked via setInterval(500ms), which meant
 * the ENTIRE draft page re-rendered twice a second -- including whatever
 * huge available-player list (thousands of rows, no virtualization) was
 * currently mounted in PlayerPool/MobileDraftRoom. That reconciliation
 * cost, not the list itself, was the real cause of the reported "draft
 * page is unreasonably slow" bug.
 *
 * Isolating the tick into its own leaf component fixes it structurally:
 * only THIS component's own subtree re-renders every 500ms. PlayerPool
 * and MobileDraftRoom now receive `pickStartedAt` (a string that only
 * changes when a new pick actually starts, not every half-second) instead
 * of a raw ticking number, so they no longer hold -- or receive -- any
 * prop that changes that often, and can be wrapped in React.memo
 * effectively.
 */
export function usePickCountdown(startedAt: string | null, timerSeconds: number): number | null {
  const [timeLeft, setTimeLeft] = useState<number | null>(null);

  useEffect(() => {
    if (!startedAt || !timerSeconds || timerSeconds <= 0) {
      setTimeLeft(null);
      return;
    }
    const started = new Date(startedAt).getTime();
    const update = () => {
      const elapsed = (Date.now() - started) / 1000;
      setTimeLeft(Math.max(0, Math.ceil(timerSeconds - elapsed)));
    };
    update();
    const interval = setInterval(update, 500);
    return () => clearInterval(interval);
  }, [startedAt, timerSeconds]);

  return timeLeft;
}

/** Big styled countdown numeral -- PlayerPool's "on the clock" banner. */
export function PickCountdownBadge({
  startedAt,
  timerSeconds,
}: {
  startedAt: string | null;
  timerSeconds: number;
}) {
  const timeLeft = usePickCountdown(startedAt, timerSeconds);
  if (timeLeft === null || timerSeconds <= 0) return null;
  return (
    <div
      className={`text-2xl font-bold font-mono tabular-nums ${
        timeLeft <= 10
          ? "text-red-400 animate-pulse"
          : timeLeft <= 30
            ? "text-yellow-400"
            : "text-surface-300"
      }`}
    >
      {timeLeft}s
    </div>
  );
}

/** Plain "<prefix><N>s" inline text -- MobileDraftRoom's compact header. */
export function PickCountdownText({
  startedAt,
  timerSeconds,
  prefix = "",
}: {
  startedAt: string | null;
  timerSeconds: number;
  prefix?: string;
}) {
  const timeLeft = usePickCountdown(startedAt, timerSeconds);
  if (timeLeft === null || timerSeconds <= 0) return null;
  return (
    <>
      {prefix}
      {timeLeft}s
    </>
  );
}
