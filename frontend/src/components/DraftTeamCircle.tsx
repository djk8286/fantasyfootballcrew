"use client";

// Shared "team identity" mark for the draft train -- originally built for
// MobileDraftRoom, extracted here so the desktop draft room can reuse the
// exact same visual (and initials logic) instead of drifting into its own
// slightly-different copy. See TeamBadge for the smaller inline badge
// used elsewhere (team rosters, board view) -- this is the larger,
// glow-capable version specifically for "who's drafting right now" trains.
import { Clock } from "lucide-react";
import { TEAM_COLORS, hashTeam } from "./TeamBadge";

// "CPU Team 3" / "CPU Team 9" / ... all reduce to the same "CP" under a
// plain first-two-letters rule -- every CPU circle in the train would
// look identical. Prefer a leading letter + trailing number when the name
// ends in digits (matches how CPU teams are actually named, see
// teams.py's bulk_add_cpu_teams), falling back to first-two-letters for
// anything else (real team names, "Your Team").
export function initialsFor(name: string): string {
  const m = name.match(/^(\D*?)(\d+)$/);
  if (m) {
    const letter = m[1].trim().charAt(0) || name.charAt(0);
    return `${letter}${m[2]}`.toUpperCase().slice(0, 3);
  }
  return name.slice(0, 2).toUpperCase();
}

export default function DraftTeamCircle({
  teamId,
  name,
  isCurrent,
  isMine,
  size = "md",
}: {
  teamId: string;
  name: string;
  isCurrent: boolean;
  isMine: boolean;
  size?: "sm" | "md" | "lg";
}) {
  const colors = TEAM_COLORS[hashTeam(teamId) % TEAM_COLORS.length];
  const dims = { sm: "w-9 h-9 text-xs", md: "w-12 h-12 text-sm", lg: "w-14 h-14 text-base" }[size];
  return (
    <div className="flex flex-col items-center gap-1 shrink-0" style={{ scrollSnapAlign: "center" }}>
      <div className="relative">
        {isCurrent && (
          <span className="absolute -inset-1 rounded-full bg-gradient-to-tr from-red-500 to-orange-400 animate-pulse blur-[2px]" />
        )}
        <div
          className={`relative ${dims} rounded-full flex items-center justify-center font-bold border-2 ${
            isCurrent
              ? "border-orange-400 ring-2 ring-red-500/60 shadow-[0_0_16px_rgba(251,146,60,0.5)]"
              : isMine
                ? "border-gold-400/60"
                : "border-surface-700"
          } ${isMine ? "bg-gold-400/20 text-gold-400" : `${colors.bg} ${colors.text}`}`}
        >
          {isMine ? "★" : initialsFor(name)}
          {isCurrent && (
            <span className="absolute -bottom-1 -right-1 w-4 h-4 rounded-full bg-red-500 border border-surface-900 flex items-center justify-center">
              <Clock className="w-2.5 h-2.5 text-white" />
            </span>
          )}
        </div>
      </div>
      <span className={`text-[9px] font-medium truncate max-w-[52px] ${isCurrent ? "text-orange-300" : "text-surface-500"}`}>
        {isMine ? "You" : name}
      </span>
    </div>
  );
}
