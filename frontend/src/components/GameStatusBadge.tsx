"use client";

/** Small LIVE/FINAL indicator next to a player's per-week score (2026-09-10)
 * -- a bare number can't tell you whether that's a final score or one
 * still climbing mid-game. Renders nothing for "not_started" (no game
 * yet, or the player has no NFL team at all) -- the score itself
 * (almost always 0 in that case) already says enough. */
export default function GameStatusBadge({ status }: { status?: string }) {
  if (status === "live") {
    return (
      <span className="inline-flex items-center gap-1 text-[9px] font-bold text-red-400 uppercase tracking-wider shrink-0">
        <span className="w-1.5 h-1.5 rounded-full bg-red-400 animate-pulse" />
        Live
      </span>
    );
  }
  if (status === "final") {
    return (
      <span className="text-[9px] font-bold text-surface-500 uppercase tracking-wider shrink-0">
        Final
      </span>
    );
  }
  return null;
}
