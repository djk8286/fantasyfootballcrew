"use client";

import { useState, useEffect } from "react";
import { leaguesApi } from "@/lib/api-client";

interface ManagementWindow {
  enabled: boolean;
  is_open: boolean;
  next_transition_at: string | null;
  next_transition_type: "opens" | "closes" | null;
}

// Best-Ball Hybrid (Phase 6) -- a small, self-contained status pill for
// GET /leagues/{id}/management-window. Renders nothing at all for a
// non-best-ball league (the endpoint itself always returns enabled:false
// there, so this is safe to drop into any page unconditionally without
// first checking whether best-ball applies). Same placement rule as
// SalaryCapBadge/BestBallBadge -- only where it's cheap to fetch, not
// the general discovery list.
export default function ManagementWindowIndicator({ leagueId }: { leagueId: string }) {
  const [win, setWin] = useState<ManagementWindow | null>(null);

  useEffect(() => {
    if (!leagueId) return;
    leaguesApi
      .getManagementWindow(leagueId)
      .then((w) => setWin(w as ManagementWindow))
      .catch(() => {});
  }, [leagueId]);

  if (!win || !win.enabled) return null;

  const nextLabel = win.next_transition_at && win.next_transition_type
    ? `${win.next_transition_type} ${new Date(win.next_transition_at + "Z").toLocaleString(undefined, {
        weekday: "short", hour: "numeric", minute: "2-digit", timeZoneName: "short",
      })}`
    : null;

  return (
    <span
      title={nextLabel ? `Window ${nextLabel}` : undefined}
      className={`inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded shrink-0 border ${
        win.is_open
          ? "text-green-400 bg-green-400/10 border-green-400/20"
          : "text-red-400 bg-red-400/10 border-red-400/20"
      }`}
    >
      {win.is_open ? "Window Open" : "Window Closed"}
    </span>
  );
}
