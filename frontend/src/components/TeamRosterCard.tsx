"use client";

// Shared "one team's drafted-so-far roster, position-grouped" card --
// extracted once this exact markup started showing up a third time
// (TeamRosters.tsx's desktop single-team panel, MobileDraftRoom.tsx's
// roster tab, and now the mobile board view/BoardRosterCards.tsx) rather
// than let a fourth copy drift out of sync with the other three.
import { Star } from "lucide-react";
import PositionBadge, { POSITION_ORDER } from "./PositionBadge";
import { PlayerAvatar } from "./PlayerAvatar";

export interface TeamRosterCardPick {
  id: string;
  pick_number: number;
  player?: {
    id: string;
    full_name: string;
    position: string;
    team: string;
    number?: number | null;
    age?: number | null;
    bye_week?: number | null;
    injury_status?: string | null;
    fantasy_positions?: string[] | null;
    avatar_url?: string | null;
    sleeper_id?: string | null;
    rank_score?: number;
    pos_rank?: number;
    headline_stats?: Record<string, number> | null;
  } | null;
  team: { id: string; name: string };
}

export default function TeamRosterCard({
  teamName,
  isMine,
  picks,
  emptyLabel,
  onPlayerHover,
}: {
  teamName: string;
  isMine: boolean;
  picks: TeamRosterCardPick[];
  emptyLabel: string;
  onPlayerHover: (player: any, el: HTMLElement | null) => void;
}) {
  const byPos: Record<string, TeamRosterCardPick[]> = {};
  picks.forEach((p) => {
    const pos = p.player?.position || "UNKNOWN";
    if (!byPos[pos]) byPos[pos] = [];
    byPos[pos].push(p);
  });

  return (
    <div className="bg-surface-800/50 border border-surface-700 rounded-2xl overflow-hidden">
      <div className="px-4 py-3 border-b border-surface-700 flex items-center justify-between">
        <h2 className="text-xs font-semibold text-surface-400 uppercase tracking-wider flex items-center gap-2">
          {isMine && <Star className="w-3.5 h-3.5 text-gold-400" />}
          {teamName}
        </h2>
        <span className="text-surface-500 text-xs">{picks.length} players</span>
      </div>
      {picks.length === 0 ? (
        <div className="p-6 text-center text-surface-500 text-sm">{emptyLabel}</div>
      ) : (
        <div className="divide-y divide-surface-800">
          {POSITION_ORDER.filter((pos) => byPos[pos]).map((pos) => (
            <div key={pos}>
              <div className="px-4 py-1.5 bg-surface-900/30 text-[10px] font-semibold text-surface-500 uppercase tracking-wider">
                {pos} ({byPos[pos].length})
              </div>
              {byPos[pos].map((p) => (
                <div
                  key={p.id}
                  className="flex items-center gap-2 px-4 py-1.5"
                  onMouseEnter={(e) => p.player && onPlayerHover(p.player, e.currentTarget)}
                  onMouseLeave={() => onPlayerHover(null, null)}
                >
                  <span className="text-surface-500 text-[10px] font-mono w-4 shrink-0">{p.pick_number}</span>
                  {p.player && <PlayerAvatar player={p.player as any} size="sm" onHover={onPlayerHover} />}
                  <span className="text-sm text-white truncate flex-1">{p.player?.full_name}</span>
                  <PositionBadge pos={p.player?.position || ""} />
                  <span className="text-[10px] text-surface-500 shrink-0">{p.player?.team}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
