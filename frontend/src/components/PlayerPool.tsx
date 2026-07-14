"use client";

import { Search, Plus, Loader2 } from "lucide-react";
import PlayerAvatar from "./PlayerAvatar";
import PositionBadge, { POSITION_ORDER } from "./PositionBadge";

interface PlayerPoolPlayer {
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

interface PlayerPoolPick {
  player?: {
    id: string;
    full_name: string;
    position: string;
  } | null;
  pick_number: number;
  team: { name: string };
}

interface PlayerPoolProps {
  filteredPlayers: PlayerPoolPlayer[];
  searchQuery: string;
  onSearchQueryChange: (q: string) => void;
  positionFilter: string;
  onPositionFilterChange: (pos: string) => void;
  positionCounts: Record<string, number>;
  availableCount: number;
  isUserOnClock: boolean;
  isCompleted: boolean;
  actionLoading: string;
  onMakePick: (playerId: string) => void;
  onToggleQueue: (player: PlayerPoolPlayer) => void;
  isQueued: (playerId: string) => boolean;
  availableQueue: PlayerPoolPlayer[];
  showQueue: boolean;
  onShowQueueChange: (show: boolean) => void;
  // "On the clock" banner
  currentPick: { pick_number: number; team: { name: string } } | null;
  timeLeft: number | null;
  timerSeconds: number;
  totalPicks: number;
  cpuingPick: boolean;
  draftCurrentTeamName: string | null;
  myTeamId: string | null;
  // Last pick + on deck
  lastPick: PlayerPoolPick | null;
  nextTwoTeamNames: string[];
  // Hover
  onPlayerHover: (player: PlayerPoolPlayer | null, el: HTMLElement | null) => void;
}

export default function PlayerPool({
  filteredPlayers,
  searchQuery,
  onSearchQueryChange,
  positionFilter,
  onPositionFilterChange,
  positionCounts,
  availableCount,
  isUserOnClock: userOnClock,
  isCompleted,
  actionLoading,
  onMakePick,
  onToggleQueue,
  isQueued,
  availableQueue,
  showQueue,
  onShowQueueChange,
  currentPick,
  timeLeft,
  timerSeconds,
  totalPicks,
  cpuingPick,
  draftCurrentTeamName,
  myTeamId,
  lastPick,
  nextTwoTeamNames,
  onPlayerHover,
}: PlayerPoolProps) {
  return (
    <div className="flex-1 min-w-0">
      {/* ON THE CLOCK banner */}
      {currentPick && !isCompleted && (
        <div
          className={`mb-4 p-4 rounded-2xl border-2 transition-all duration-300 ${
            userOnClock
              ? "bg-gold-400/20 border-gold-400/50 ring-2 ring-gold-400/20 animate-[pulse_2s_ease-in-out_infinite] shadow-[0_0_30px_rgba(255,215,0,0.15)]"
              : cpuingPick
                ? "bg-blue-500/10 border-blue-500/30"
                : "bg-surface-800/50 border-surface-700"
          }`}
        >
          <div className="flex items-center gap-3">
            <div
              className={`w-3 h-3 rounded-full shrink-0 ${
                userOnClock ? "bg-gold-400 animate-ping" : "bg-blue-400/60"
              }`}
            />
            <div className="flex-1">
              <span className="text-surface-400 text-xs">
                {userOnClock ? "YOUR TURN" : cpuingPick ? "Auto-Picking..." : "On the Clock"}
              </span>
              <p
                className={`font-bold text-lg ${
                  userOnClock ? "text-gold-400" : "text-white"
                }`}
              >
                {draftCurrentTeamName || "Unknown"}
                {userOnClock && myTeamId && (
                  <span className="ml-3 text-sm bg-gold-400/20 text-gold-400 px-3 py-1 rounded-lg font-bold">
                    YOUR TEAM
                  </span>
                )}
              </p>
            </div>
            {timeLeft !== null && timerSeconds > 0 && (
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
            )}
            <span className="text-surface-500 text-xs hidden sm:block">
              Pick {currentPick.pick_number}/{totalPicks}
            </span>
          </div>
        </div>
      )}

      {/* LAST PICK + ON DECK row */}
      {!isCompleted && (lastPick || nextTwoTeamNames.length > 0) && (
        <div className="flex gap-3 mb-4">
          {lastPick && (
            <div className="flex-1 bg-surface-800/40 border border-surface-700/60 rounded-xl px-3 py-2">
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-surface-500 uppercase tracking-wider font-semibold shrink-0">
                  Last Pick
                </span>
                <span className="text-surface-300 text-xs font-medium truncate">
                  {lastPick.player?.full_name}
                </span>
                <PositionBadge pos={lastPick.player?.position || ""} />
                <span className="text-[10px] text-surface-500 truncate shrink-0">
                  → {lastPick.team.name}
                </span>
              </div>
            </div>
          )}
          {nextTwoTeamNames.length > 0 && (
            <div className="flex-1 bg-surface-800/40 border border-surface-700/60 rounded-xl px-3 py-2">
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-surface-500 uppercase tracking-wider font-semibold shrink-0">
                  On Deck
                </span>
                {nextTwoTeamNames.map((name, i) => (
                  <span key={i} className="text-surface-300 text-xs font-medium">
                    {i > 0 && <span className="text-surface-600 mx-1">→</span>}
                    {name}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Search & Filters */}
      <div className="bg-surface-800/50 border border-surface-700 rounded-2xl overflow-hidden mb-4">
        <div className="p-4">
          {/* Player pool / Queue tabs */}
          <div className="flex gap-1 bg-surface-900 rounded-lg p-0.5 mb-4">
            <button
              onClick={() => onShowQueueChange(false)}
              className={`flex-1 py-2 rounded-lg text-sm font-medium transition-all ${
                !showQueue ? "bg-surface-700 text-white" : "text-surface-400"
              }`}
            >
              Players ({filteredPlayers.length})
            </button>
            <button
              onClick={() => onShowQueueChange(true)}
              className={`flex-1 py-2 rounded-lg text-sm font-medium transition-all relative ${
                showQueue ? "bg-surface-700 text-white" : "text-surface-400"
              }`}
            >
              Queue
              {availableQueue.length > 0 && (
                <span className="ml-1.5 bg-gold-400 text-surface-900 text-[10px] font-bold px-1.5 py-0.5 rounded-full">
                  {availableQueue.length}
                </span>
              )}
            </button>
          </div>

          {/* Search */}
          {!showQueue && (
            <>
              <div className="relative mb-3">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-surface-500" />
                <input
                  type="text"
                  placeholder="Search by name, team, or position..."
                  value={searchQuery}
                  onChange={(e) => onSearchQueryChange(e.target.value)}
                  className="w-full pl-10 pr-3 py-2.5 bg-surface-900 border border-surface-700 rounded-xl text-sm text-white placeholder-surface-500 focus:outline-none focus:ring-1 focus:ring-gold-400"
                  autoFocus={userOnClock}
                />
              </div>
              {/* Position filters */}
              <div className="flex flex-wrap gap-1.5">
                <button
                  onClick={() => onPositionFilterChange("ALL")}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                    positionFilter === "ALL"
                      ? "bg-gold-400/20 text-gold-400 border border-gold-400/30"
                      : "bg-surface-900 text-surface-400 border border-surface-700 hover:border-surface-500"
                  }`}
                >
                  All ({availableCount})
                </button>
                {POSITION_ORDER.map((pos) => {
                  const count = positionCounts[pos] || 0;
                  return (
                    <button
                      key={pos}
                      onClick={() => onPositionFilterChange(pos)}
                      className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                        positionFilter === pos
                          ? "bg-gold-400/20 text-gold-400 border border-gold-400/30"
                          : count === 0
                            ? "bg-surface-900 text-surface-600 border border-surface-700/50 opacity-50 cursor-not-allowed"
                            : "bg-surface-900 text-surface-400 border border-surface-700 hover:border-surface-500"
                      }`}
                    >
                      {pos} ({count})
                    </button>
                  );
                })}
              </div>
            </>
          )}
        </div>

        {/* Player/Queue list */}
        <div
          className={`${
            userOnClock
              ? "max-h-[calc(100vh-480px)]"
              : "max-h-[calc(100vh-430px)]"
          } overflow-y-auto divide-y divide-surface-700/50`}
        >
          {!showQueue ? (
            // Player list
            filteredPlayers.length === 0 ? (
              <div className="p-6 text-center text-surface-500 text-sm">
                {searchQuery
                  ? "No players match your search"
                  : "No players available"}
              </div>
            ) : (
              filteredPlayers.map((player) => {
                const mine = userOnClock;
                return (
                  <div
                    key={player.id}
                    className={`flex items-center gap-3 px-4 py-3 transition-colors ${
                      mine ? "hover:bg-surface-700/30 cursor-pointer" : ""
                    } ${isQueued(player.id) ? "bg-gold-400/5" : ""}`}
                  >
                    {/* Avatar */}
                    <PlayerAvatar player={player} size="md" onHover={onPlayerHover} />
                    {/* Player info */}
                    <div
                      className="flex-1 min-w-0"
                      onMouseEnter={(e) => onPlayerHover(player, e.currentTarget)}
                      onMouseLeave={() => onPlayerHover(null, null)}
                    >
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold text-white truncate">
                          {player.full_name}
                        </span>
                        <PositionBadge pos={player.position} />
                      </div>
                      <div className="flex items-center gap-3 text-xs text-surface-500 mt-0.5">
                        <span>{player.team || "FA"}</span>
                        {player.rank_score < 500 && (
                          <span className="text-gold-400/70">
                            Rank #{player.rank_score}
                          </span>
                        )}
                      </div>
                    </div>
                    {/* Action buttons */}
                    <div className="flex items-center gap-1.5 shrink-0">
                      {/* Queue toggle */}
                      <button
                        onClick={() => onToggleQueue(player)}
                        className={`p-1.5 rounded-lg transition-all ${
                          isQueued(player.id)
                            ? "bg-gold-400/20 text-gold-400"
                            : "text-surface-500 hover:text-surface-300 hover:bg-surface-700"
                        }`}
                        title={
                          isQueued(player.id)
                            ? "Remove from queue"
                            : "Add to queue"
                        }
                      >
                        <Plus
                          className={`w-4 h-4 transition-transform ${
                            isQueued(player.id) ? "rotate-45" : ""
                          }`}
                        />
                      </button>
                      {/* Pick button */}
                      {!isCompleted && (
                        <button
                          onClick={() => onMakePick(player.id)}
                          disabled={actionLoading === "pick" || !mine}
                          className={`px-4 py-2 rounded-lg text-xs font-bold transition-all ${
                            mine
                              ? "bg-gold-400 hover:bg-gold-300 text-surface-900 hover:shadow-lg hover:shadow-gold-400/25 active:scale-95"
                              : "bg-surface-700 text-surface-500 cursor-not-allowed"
                          } disabled:opacity-50 disabled:cursor-not-allowed`}
                        >
                          {actionLoading === "pick" ? (
                            <Loader2 className="w-3 h-3 animate-spin" />
                          ) : mine ? (
                            "Pick"
                          ) : (
                            "—"
                          )}
                        </button>
                      )}
                    </div>
                  </div>
                );
              })
            )
          ) : (
            // Queue list
            availableQueue.length === 0 ? (
              <div className="p-6 text-center text-surface-500 text-sm">
                Queue is empty. Click{" "}
                <Plus className="w-3 h-3 inline" /> on a player to add them here.
              </div>
            ) : (
              availableQueue.map((player, idx) => (
                <div
                  key={player.id}
                  className="flex items-center gap-3 px-4 py-3 hover:bg-surface-700/30 transition-colors"
                >
                  <span className="text-surface-500 text-xs font-mono w-5 shrink-0 text-center">
                    {idx + 1}
                  </span>
                  <PlayerAvatar player={player} size="sm" onHover={onPlayerHover} />
                  <div
                    className="flex-1 min-w-0"
                    onMouseEnter={(e) => onPlayerHover(player, e.currentTarget)}
                    onMouseLeave={() => onPlayerHover(null, null)}
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-white truncate">
                        {player.full_name}
                      </span>
                      <PositionBadge pos={player.position} />
                    </div>
                    <span className="text-xs text-surface-500">
                      {player.team || "FA"}
                    </span>
                  </div>
                  <button
                    onClick={() => onToggleQueue(player)}
                    className="p-1.5 rounded-lg text-surface-500 hover:text-red-400 hover:bg-surface-700 transition-all"
                    title="Remove from queue"
                  >
                    <Plus className="w-4 h-4 rotate-45" />
                  </button>
                  {!isCompleted && userOnClock && (
                    <button
                      onClick={() => onMakePick(player.id)}
                      disabled={actionLoading === "pick"}
                      className="px-4 py-2 rounded-lg text-xs font-bold bg-gold-400 hover:bg-gold-300 text-surface-900 transition-all disabled:opacity-50"
                    >
                      {actionLoading === "pick" ? (
                        <Loader2 className="w-3 h-3 animate-spin" />
                      ) : (
                        "Pick"
                      )}
                    </button>
                  )}
                </div>
              ))
            )
          )}
        </div>
      </div>
    </div>
  );
}
