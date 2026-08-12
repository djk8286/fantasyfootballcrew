"use client";

import { Radio } from "lucide-react";
import PlayerAvatar from "./PlayerAvatar";
import PositionBadge from "./PositionBadge";

// Matches draft/[id]/page.tsx's DraftPickPlayer. Doesn't carry
// first_name/last_name/avatar_url (PlayerAvatar's own HoverPlayer type
// wants those, but doesn't actually need them at runtime -- it falls back
// to full_name.charAt(0) and an "avatar_url" in player runtime check).
// TeamRosters.tsx, which renders these same DraftPick objects, already
// types its onPlayerHover as `any` for exactly this reason -- matching
// that rather than fighting the type system with a third hand-copy of a
// shape that has already drifted twice this session.
interface RecentPick {
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

interface RecentPicksPanelProps {
  picks: RecentPick[]; // already sorted most-recent-first, already sliced to a reasonable feed length
  myTeamId: string | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  onPlayerHover: (player: any, el: HTMLElement | null) => void;
}

export default function RecentPicksPanel({ picks, myTeamId, onPlayerHover }: RecentPicksPanelProps) {
  return (
    <div className="bg-surface-800/50 border border-surface-700 rounded-2xl overflow-hidden">
      <div className="px-4 py-3 border-b border-surface-700">
        <h3 className="text-xs font-semibold text-surface-400 uppercase tracking-wider flex items-center gap-2">
          <Radio className="w-3.5 h-3.5 text-gold-400" />
          Recent Picks
        </h3>
      </div>
      {picks.length === 0 ? (
        <div className="p-5 text-center text-surface-500 text-xs">
          Picks will show up here as the draft gets underway.
        </div>
      ) : (
        <div className="divide-y divide-surface-800 max-h-[520px] overflow-y-auto">
          {picks.map((p) => {
            const isMine = myTeamId === p.team.id;
            return (
              <div key={p.id} className="flex items-center gap-2.5 px-4 py-2.5">
                <span className="text-surface-500 text-[10px] font-mono w-7 shrink-0 text-center">
                  #{p.pick_number}
                </span>
                {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                {p.player && <PlayerAvatar player={p.player as any} size="sm" onHover={onPlayerHover} />}
                <div
                  className="flex-1 min-w-0"
                  onMouseEnter={(e) => p.player && onPlayerHover(p.player, e.currentTarget)}
                  onMouseLeave={() => onPlayerHover(null, null)}
                >
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs font-medium text-white truncate">
                      {p.player?.full_name || "—"}
                    </span>
                    {p.player && <PositionBadge pos={p.player.position} />}
                  </div>
                  <span className={`text-[10px] truncate block ${isMine ? "text-gold-400" : "text-surface-500"}`}>
                    {isMine ? "Your Team" : p.team.name}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
