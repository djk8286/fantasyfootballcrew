"use client";

import { Zap, Plus, Loader2, ListChecks } from "lucide-react";
import PlayerAvatar from "./PlayerAvatar";
import PositionBadge from "./PositionBadge";

// Matches draft/[id]/page.tsx's Player interface structurally -- no index
// signature, since that makes this type incompatible with the concrete
// Player[] the page actually passes in (same trap documented in
// MobileDraftRoom.tsx's equivalent type).
interface QueuePlayer {
  id: string;
  full_name: string;
  first_name: string;
  last_name: string;
  position: string;
  team: string;
  age: number | null;
  number: number | null;
  bye_week: number | null;
  injury_status: string | null;
  fantasy_positions: string[] | null;
  avatar_url: string | null;
  sleeper_id: string | null;
  rank_score: number;
  pos_rank: number;
}

interface DraftQueuePanelProps {
  queue: QueuePlayer[];
  isUserOnClock: boolean;
  actionLoading: string;
  onMakePick: (playerId: string) => void;
  onToggleQueue: (player: QueuePlayer) => void;
  autoPickForMe: boolean;
  onToggleAutoPickForMe: () => void;
  onPlayerHover: (player: QueuePlayer | null, el: HTMLElement | null) => void;
}

export default function DraftQueuePanel({
  queue,
  isUserOnClock,
  actionLoading,
  onMakePick,
  onToggleQueue,
  autoPickForMe,
  onToggleAutoPickForMe,
  onPlayerHover,
}: DraftQueuePanelProps) {
  return (
    <div className="bg-surface-800/50 border border-surface-700 rounded-2xl overflow-hidden">
      <div className="px-4 py-3 border-b border-surface-700 flex items-center justify-between">
        <h2 className="text-xs font-semibold text-surface-400 uppercase tracking-wider flex items-center gap-2">
          <ListChecks className="w-3.5 h-3.5 text-gold-400" />
          Pick Queue
          {queue.length > 0 && (
            <span className="bg-gold-400 text-surface-900 text-[10px] font-bold px-1.5 py-0.5 rounded-full">
              {queue.length}
            </span>
          )}
        </h2>
        <button
          onClick={onToggleAutoPickForMe}
          aria-pressed={autoPickForMe}
          className={`inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-semibold border transition-all ${
            autoPickForMe
              ? "bg-blue-500/20 border-blue-500/40 text-blue-300"
              : "bg-surface-900 border-surface-700 text-surface-400 hover:text-surface-200"
          }`}
          title="Auto-pick for me the instant it's my turn (queue first, then best available)"
        >
          <Zap className={`w-3 h-3 ${autoPickForMe ? "fill-blue-300" : ""}`} />
          Autopick {autoPickForMe ? "On" : "Off"}
        </button>
      </div>

      {queue.length === 0 ? (
        <div className="p-5 text-center text-surface-500 text-xs">
          Empty. Add players from the pool to line up your next picks.
        </div>
      ) : (
        <div className="divide-y divide-surface-800 max-h-[280px] overflow-y-auto">
          {queue.map((player, idx) => (
            <div
              key={player.id}
              className="flex items-center gap-2 px-4 py-2 hover:bg-surface-800/40 transition-colors"
            >
              <span className="text-surface-500 text-[10px] font-mono w-4 shrink-0 text-center">{idx + 1}</span>
              <PlayerAvatar player={player} size="sm" onHover={onPlayerHover} />
              <div
                className="flex-1 min-w-0"
                onMouseEnter={(e) => onPlayerHover(player, e.currentTarget)}
                onMouseLeave={() => onPlayerHover(null, null)}
              >
                <div className="flex items-center gap-1.5">
                  <span className="text-xs font-medium text-white truncate">{player.full_name}</span>
                  <PositionBadge pos={player.position} />
                </div>
                <span className="text-[10px] text-surface-500">{player.team || "FA"}</span>
              </div>
              <button
                onClick={() => onToggleQueue(player)}
                className="p-1 rounded text-surface-500 hover:text-red-400 transition-colors shrink-0"
                title="Remove from queue"
              >
                <Plus className="w-3.5 h-3.5 rotate-45" />
              </button>
              {isUserOnClock && (
                <button
                  onClick={() => onMakePick(player.id)}
                  disabled={actionLoading === "pick"}
                  className="px-2.5 py-1 rounded-lg text-[10px] font-bold bg-gold-400 hover:bg-gold-300 text-surface-900 transition-all disabled:opacity-50 shrink-0"
                >
                  {actionLoading === "pick" ? <Loader2 className="w-3 h-3 animate-spin" /> : "Pick"}
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
