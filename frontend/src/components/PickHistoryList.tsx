"use client";

import PlayerAvatar from "./PlayerAvatar";
import PositionBadge from "./PositionBadge";
import TeamBadge from "./TeamBadge";
import { formatPickLabel } from "@/lib/draftPickMath";

// Matches draft/[id]/page.tsx's DraftPickPlayer. See RecentPicksPanel.tsx
// for why this doesn't try to match PlayerAvatar's HoverPlayer exactly
// (TeamRosters.tsx, rendering these same objects, already types its
// onPlayerHover as `any` for the same reason).
interface HistoryPick {
  id: string;
  pick_number: number;
  player: {
    id: string;
    full_name: string;
    position: string;
    team: string;
    number?: number | null;
    age?: number | null;
    bye_week?: number | null;
    injury_status?: string | null;
    fantasy_positions?: string[] | null;
    rank_score?: number;
    pos_rank?: number;
  } | null;
  team: { id: string; name: string };
}

interface PickHistoryListProps {
  picks: HistoryPick[]; // all completed picks, any order -- sorted here
  numTeams: number;
  myTeamId: string | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  onPlayerHover: (player: any, el: HTMLElement | null) => void;
}

export default function PickHistoryList({ picks, numTeams, myTeamId, onPlayerHover }: PickHistoryListProps) {
  const sorted = [...picks].sort((a, b) => b.pick_number - a.pick_number); // most recent first

  if (sorted.length === 0) {
    return (
      <div className="bg-surface-800/50 border border-surface-700 rounded-2xl p-10 text-center text-surface-500 text-sm">
        No picks made yet.
      </div>
    );
  }

  return (
    <div className="bg-surface-800/50 border border-surface-700 rounded-2xl overflow-hidden">
      <div className="px-4 py-3 border-b border-surface-700">
        <h2 className="text-xs font-semibold text-surface-400 uppercase tracking-wider">
          Full Pick History · {sorted.length} picks
        </h2>
      </div>
      <div className="divide-y divide-surface-800/70 max-h-[calc(100vh-320px)] overflow-y-auto">
        {sorted.map((p) => {
          const isMine = myTeamId === p.team.id;
          return (
            <div key={p.id} className="flex items-center gap-3 px-4 py-2.5 hover:bg-surface-800/30 transition-colors">
              <span className="text-surface-500 text-xs font-mono w-14 shrink-0">
                {formatPickLabel(p.pick_number - 1, numTeams)}
              </span>
              {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
              {p.player && <PlayerAvatar player={p.player as any} size="sm" onHover={onPlayerHover} />}
              <div
                className="flex-1 min-w-0 flex items-center gap-2"
                onMouseEnter={(e) => p.player && onPlayerHover(p.player, e.currentTarget)}
                onMouseLeave={() => onPlayerHover(null, null)}
              >
                <span className="text-sm font-medium text-white truncate">{p.player?.full_name || "—"}</span>
                {p.player && <PositionBadge pos={p.player.position} />}
                <span className="text-xs text-surface-500 shrink-0">{p.player?.team || ""}</span>
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                <TeamBadge team={p.team.name} isMine={isMine} />
                <span className={`text-xs truncate max-w-[140px] ${isMine ? "text-gold-400 font-medium" : "text-surface-400"}`}>
                  {isMine ? "Your Team" : p.team.name}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
