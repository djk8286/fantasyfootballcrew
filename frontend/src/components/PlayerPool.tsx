"use client";

import { memo } from "react";
import { Search, Plus, Loader2 } from "lucide-react";
import PlayerAvatar, { STAT_LABELS } from "./PlayerAvatar";
import PositionBadge, { POSITION_ORDER } from "./PositionBadge";
import { PickCountdownBadge } from "./PickCountdown";
import { useVirtualList } from "@/lib/useVirtualList";

// Matches the row's actual rendered height (verified via CDP against a
// real draft page: 64px, driven by the two-line name/team block, not the
// 36px avatar). Virtualizing this list is the fix for a real, large
// perf bug -- the undrafted player pool can be thousands of entries, all
// previously mounted at once (thousands of concurrent avatar image
// loads, confirmed via a live MutationObserver check), not just tens.
const PLAYER_ROW_HEIGHT = 64;

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
  headline_stats?: Record<string, number> | null;
  season_points?: number | null;
  season_points_year?: number | null;
  // Simple, honestly-labeled 2026 estimate (not a real projections model --
  // this app has no external projections data source, see the backend's
  // _projected_points_field docstring). Currently just last season's actual
  // total, same source as season_points.
  projected_points?: number | null;
}

// Compact "<team> · <2-3 headline stats> · <season total>" line for the
// space in a player row that used to just be blank -- headline_stats and
// season_points are last season's real numbers until the new season has
// its own synced data (see effective_season_stats on the backend), so
// this is never empty just because the current season hasn't started.
function PlayerStatsLine({ player }: { player: PlayerPoolPlayer }) {
  const stats = Object.entries(player.headline_stats || {}).slice(0, 3);
  if (stats.length === 0 && player.season_points == null) return null;
  return (
    <div className="hidden md:flex items-center gap-2.5 text-[11px] text-surface-400 shrink-0 px-3 whitespace-nowrap">
      <span className="text-surface-500 uppercase tracking-wider font-semibold">
        {player.team || "FA"}
      </span>
      {stats.map(([key, value]) => (
        <span key={key}>
          <span className="text-surface-300 font-semibold">
            {Math.round(value * 10) / 10}
          </span>{" "}
          {STAT_LABELS[key] || key}
        </span>
      ))}
      {player.season_points != null && (
        <span className="text-gold-400/80 font-semibold">
          {Math.round(player.season_points * 10) / 10} pts
          {player.season_points_year ? ` (${player.season_points_year})` : ""}
        </span>
      )}
      {player.projected_points != null && (
        <span className="text-blue-400/70 font-semibold" title="Simple estimate based on last season's production -- not a real projections model">
          {Math.round(player.projected_points * 10) / 10} proj
        </span>
      )}
    </div>
  );
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

// Mirrors draft/[id]/page.tsx's DRAFT_SORT_OPTIONS -- kept here too since
// this is the only place the desktop player pool renders (sorting itself
// happens in the page, this component just needs the label list + the
// current value to render the control and reflect its state).
const SORT_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "Default (Rank)" },
  { value: "points", label: "Fantasy Points (last season)" },
  { value: "yards", label: "Yards (last season)" },
  { value: "touchdowns", label: "Touchdowns (last season)" },
  { value: "projected", label: "Projected" },
];

interface PlayerPoolProps {
  filteredPlayers: PlayerPoolPlayer[];
  searchQuery: string;
  onSearchQueryChange: (q: string) => void;
  positionFilter: string;
  onPositionFilterChange: (pos: string) => void;
  sortBy: string;
  onSortByChange: (sort: string) => void;
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
  // Deadline, not a ticking number -- see PickCountdown.tsx. Stable across
  // the 500ms ticks (only changes when a new pick actually starts), which
  // is what lets this whole component be wrapped in React.memo below.
  pickStartedAt: string | null;
  timerSeconds: number;
  totalPicks: number;
  cpuingPick: boolean;
  draftCurrentTeamName: string | null;
  myTeamId: string | null;
  // 2-Man team on-the-clock indicator -- see draft/[id]/page.tsx for how
  // these are derived (display convention only, not enforcement).
  currentTeamHasCoOwner: boolean;
  onClockManagerIsOwner: boolean;
  // Last pick + on deck
  lastPick: PlayerPoolPick | null;
  nextTwoTeamNames: string[];
  // Hover
  onPlayerHover: (player: PlayerPoolPlayer | null, el: HTMLElement | null) => void;
}

function PlayerPool({
  filteredPlayers,
  searchQuery,
  onSearchQueryChange,
  positionFilter,
  onPositionFilterChange,
  sortBy,
  onSortByChange,
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
  pickStartedAt,
  timerSeconds,
  totalPicks,
  cpuingPick,
  draftCurrentTeamName,
  myTeamId,
  currentTeamHasCoOwner,
  onClockManagerIsOwner,
  lastPick,
  nextTwoTeamNames,
  onPlayerHover,
}: PlayerPoolProps) {
  // Reset scroll on an actual filter/search edit (a deliberate "show me
  // something different" action), not on every filteredPlayers reference
  // change -- that also happens on the ~5s poll once any team picks, and
  // resetting scroll then would yank anyone mid-browse back to the top.
  const {
    containerRef: playerListRef,
    onScroll: onPlayerListScroll,
    visibleItems: visiblePlayers,
    paddingTop: playerListPaddingTop,
    paddingBottom: playerListPaddingBottom,
  } = useVirtualList(filteredPlayers, PLAYER_ROW_HEIGHT, `${positionFilter}:${searchQuery}:${sortBy}`);

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
          {/* Announces whose turn it is without a screen-reader user having
              to re-scan the page -- the draft room is entirely timer-driven,
              so this is the single highest-impact a11y fix here. Only the
              turn-change text lives in the live region, not the ticking
              countdown (PickCountdownBadge below) -- that would announce
              every second and make the page unusable with a screen reader. */}
          <span className="sr-only" aria-live="polite" aria-atomic="true">
            {userOnClock
              ? "It's your turn to pick."
              : cpuingPick
                ? `${draftCurrentTeamName || "A team"} is auto-picking.`
                : `${draftCurrentTeamName || "A team"} is on the clock.`}
          </span>
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
              {/* 2-Man team: shows whose turn it "should" be within the
                  shared team, alternating by pick count -- a convention
                  for the two co-managers to coordinate by, not an
                  enforcement (either can actually submit the pick). */}
              {currentTeamHasCoOwner && (
                <div className="flex items-center gap-1.5 mt-1.5">
                  <span
                    className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                      onClockManagerIsOwner
                        ? "bg-gold-400/20 text-gold-400"
                        : "bg-surface-700/60 text-surface-500"
                    }`}
                  >
                    Owner{onClockManagerIsOwner ? "'s pick" : ""}
                  </span>
                  <span
                    className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                      !onClockManagerIsOwner
                        ? "bg-gold-400/20 text-gold-400"
                        : "bg-surface-700/60 text-surface-500"
                    }`}
                  >
                    Co-Owner{!onClockManagerIsOwner ? "'s pick" : ""}
                  </span>
                </div>
              )}
            </div>
            <PickCountdownBadge startedAt={pickStartedAt} timerSeconds={timerSeconds} />
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
              aria-pressed={!showQueue}
              className={`flex-1 py-2 rounded-lg text-sm font-medium transition-all ${
                !showQueue ? "bg-surface-700 text-white" : "text-surface-400"
              }`}
            >
              Players ({filteredPlayers.length})
            </button>
            <button
              onClick={() => onShowQueueChange(true)}
              aria-pressed={showQueue}
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
                  aria-label="Search players by name, team, or position"
                  value={searchQuery}
                  onChange={(e) => onSearchQueryChange(e.target.value)}
                  className="w-full pl-10 pr-3 py-2.5 bg-surface-900 border border-surface-700 rounded-xl text-sm text-white placeholder-surface-500 focus:outline-none focus:ring-1 focus:ring-gold-400"
                  autoFocus={userOnClock}
                />
              </div>
              {/* Position filters + sort */}
              <div className="flex flex-wrap items-center gap-1.5">
                <button
                  onClick={() => onPositionFilterChange("ALL")}
                  aria-pressed={positionFilter === "ALL"}
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
                      aria-pressed={positionFilter === pos}
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
                <label className="ml-auto flex items-center gap-1.5 text-xs text-surface-400">
                  Sort by
                  <select
                    value={sortBy}
                    onChange={(e) => onSortByChange(e.target.value)}
                    className="bg-surface-900 border border-surface-700 rounded-lg text-xs text-white px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-gold-400"
                  >
                    {SORT_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </>
          )}
        </div>

        {/* Player/Queue list */}
        <div
          ref={!showQueue ? playerListRef : undefined}
          onScroll={!showQueue ? onPlayerListScroll : undefined}
          className={`${
            userOnClock
              ? "max-h-[calc(100vh-480px)]"
              : "max-h-[calc(100vh-430px)]"
          } overflow-y-auto ${showQueue ? "divide-y divide-surface-700/50" : ""}`}
        >
          {!showQueue ? (
            // Player list -- virtualized (see useVirtualList.ts). Only
            // paddingTop/paddingBottom spacers + the rows actually in view
            // are real DOM nodes; divide-y moves onto this inner wrapper
            // since it needs to apply between the rendered rows, not
            // between the spacers and the rows.
            filteredPlayers.length === 0 ? (
              <div className="p-6 text-center text-surface-500 text-sm">
                {searchQuery
                  ? "No players match your search"
                  : "No players available"}
              </div>
            ) : (
              <div
                style={{ paddingTop: playerListPaddingTop, paddingBottom: playerListPaddingBottom }}
                className="divide-y divide-surface-700/50"
              >
                {visiblePlayers.map((player) => {
                  const mine = userOnClock;
                  return (
                    <div
                      key={player.id}
                      style={{ height: PLAYER_ROW_HEIGHT }}
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
                      {/* Last season's stats + team -- was blank space here before */}
                      <PlayerStatsLine player={player} />
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
                })}
              </div>
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

// filteredPlayers can be thousands of rows -- memo() so a parent re-render
// that doesn't actually change any of this component's props (e.g. the
// 5s draft-state poll ticking `draft` while nothing here changed) doesn't
// force React to re-reconcile all of them. Only actually works because
// pickStartedAt replaced a raw ticking timeLeft number (see above) and
// the page memoizes filteredPlayers/availableQueue/positionCounts with
// useMemo so their array/object references stay stable across renders
// that don't change their real inputs.
export default memo(PlayerPool);
