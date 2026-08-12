"use client";

import { useEffect, useRef, useState } from "react";
import { Search, Plus, Loader2, Clock, Zap, ListChecks, X, TrendingUp, Grid3X3 } from "lucide-react";
import PlayerAvatar, { STAT_LABELS } from "./PlayerAvatar";
import PositionBadge, { POSITION_ORDER } from "./PositionBadge";
import { TEAM_COLORS, hashTeam } from "./TeamBadge";

// Matches draft/[id]/page.tsx's Player interface exactly (structurally --
// no index signature, since that would make this type incompatible with
// the concrete Player[] the page actually passes in). headline_stats/
// season_points* are optional extras PlayerPool.tsx's PlayerPoolPlayer
// already carries the same way -- the runtime data has them even though
// this page's own Player interface predates that addition.
interface MobileDraftPlayer {
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
}

interface MobileDraftPick {
  id: string;
  round: number;
  pick_number: number;
  player: { id: string; full_name: string; position: string } | null;
  team: { id: string; name: string };
}

// Global pick index (0-based, matches team_order's indexing) -> "round.pick"
// display, e.g. index 39 in a 12-team draft is round 4 (indices 36-47),
// pick 4 within that round -> "4.04".
function formatPickLabel(globalIndex: number, numTeams: number): string {
  if (numTeams <= 0) return "";
  const round = Math.floor(globalIndex / numTeams) + 1;
  const pickInRound = (globalIndex % numTeams) + 1;
  return `${round}.${String(pickInRound).padStart(2, "0")}`;
}

// How many picks (including CPU/other-human picks) happen before it's
// myTeamId's turn again, counting from currentIndex. 0 means it's already
// my turn. null means I don't have a claimed team, or I'm not in this
// draft's team_order at all.
function picksUntilMyTurn(teamOrder: string[], currentIndex: number, myTeamId: string | null): number | null {
  if (!myTeamId) return null;
  for (let i = currentIndex; i < teamOrder.length; i++) {
    if (teamOrder[i] === myTeamId) return i - currentIndex;
  }
  return null;
}

// Best-available-at-a-position-of-need, falling back to pure best-player-
// available. Not a real projections model (this app doesn't have one) --
// a simple, honest heuristic: standard starter counts per position, most-
// short-handed need first, tie-broken by rank; once every modeled slot is
// filled, just the single best-ranked player left. availablePlayers is
// assumed already sorted best-to-worst by rank_score.
const STARTER_SLOTS: Record<string, number> = { QB: 1, RB: 2, WR: 2, TE: 1, K: 1, DEF: 1 };

function projectNextPick(
  availablePlayers: MobileDraftPlayer[],
  myRosterByPos: Record<string, MobileDraftPick[]>
): { player: MobileDraftPlayer; reason: string } | null {
  if (availablePlayers.length === 0) return null;

  const needs = Object.entries(STARTER_SLOTS)
    .map(([pos, need]) => ({ pos, short: need - (myRosterByPos[pos]?.length || 0) }))
    .filter((n) => n.short > 0)
    .sort((a, b) => b.short - a.short);

  for (const need of needs) {
    const best = availablePlayers.find((p) => p.position === need.pos);
    if (best) {
      return { player: best, reason: `Fills your ${need.pos} need` };
    }
  }
  return { player: availablePlayers[0], reason: "Best player available" };
}

// "CPU Team 3" / "CPU Team 9" / ... all reduce to the same "CP" under a
// plain first-two-letters rule -- every CPU circle in the train would
// look identical. Prefer a leading letter + trailing number when the name
// ends in digits (matches how CPU teams are actually named, see
// teams.py's bulk_add_cpu_teams), falling back to first-two-letters for
// anything else (real team names, "Your Team").
function initialsFor(name: string): string {
  const m = name.match(/^(\D*?)(\d+)$/);
  if (m) {
    const letter = m[1].trim().charAt(0) || name.charAt(0);
    return `${letter}${m[2]}`.toUpperCase().slice(0, 3);
  }
  return name.slice(0, 2).toUpperCase();
}

function TeamCircle({
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
  size?: "sm" | "md";
}) {
  const colors = TEAM_COLORS[hashTeam(teamId) % TEAM_COLORS.length];
  const dims = size === "md" ? "w-12 h-12 text-sm" : "w-9 h-9 text-xs";
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

interface MobileDraftRoomProps {
  teamOrder: string[];
  teams: Record<string, { name: string }>;
  currentTeamId: string | null;
  currentPickGlobalIndex: number;
  numTeams: number;
  totalPicks: number;
  currentRound: number;
  totalRounds: number;
  isCompleted: boolean;
  myTeamId: string | null;

  lastPick: MobileDraftPick | null;

  availablePlayers: MobileDraftPlayer[];
  myRosterByPos: Record<string, MobileDraftPick[]>;

  filteredPlayers: MobileDraftPlayer[];
  searchQuery: string;
  onSearchQueryChange: (q: string) => void;
  positionFilter: string;
  onPositionFilterChange: (pos: string) => void;
  positionCounts: Record<string, number>;
  availableCount: number;

  isUserOnClock: boolean;
  actionLoading: string;
  onMakePick: (playerId: string) => void;
  onToggleQueue: (player: MobileDraftPlayer) => void;
  isQueued: (id: string) => boolean;
  queue: MobileDraftPlayer[];

  timeLeft: number | null;
  timerSeconds: number;

  autoPickForMe: boolean;
  onToggleAutoPickForMe: () => void;

  onPlayerHover: (player: MobileDraftPlayer | null, el: HTMLElement | null) => void;
  onShowBoard?: () => void;
}

export default function MobileDraftRoom({
  teamOrder,
  teams,
  currentTeamId,
  currentPickGlobalIndex,
  numTeams,
  totalPicks,
  currentRound,
  totalRounds,
  isCompleted,
  myTeamId,
  lastPick,
  availablePlayers,
  myRosterByPos,
  filteredPlayers,
  searchQuery,
  onSearchQueryChange,
  positionFilter,
  onPositionFilterChange,
  positionCounts,
  availableCount,
  isUserOnClock,
  actionLoading,
  onMakePick,
  onToggleQueue,
  isQueued,
  queue,
  timeLeft,
  timerSeconds,
  autoPickForMe,
  onToggleAutoPickForMe,
  onPlayerHover,
  onShowBoard,
}: MobileDraftRoomProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showQueuePanel, setShowQueuePanel] = useState(false);
  const currentTeamRef = useRef<HTMLDivElement>(null);

  // Keep the on-the-clock avatar scrolled into view as the draft advances.
  useEffect(() => {
    currentTeamRef.current?.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
  }, [currentTeamId]);

  // Dedupe consecutive team_order entries into a display list (train
  // shows one circle per team, not one per round-repeat).
  const uniqueTeams = teamOrder.filter((tid, i, arr) => arr.indexOf(tid) === i);

  const picksAway = isCompleted ? null : picksUntilMyTurn(teamOrder, currentPickGlobalIndex, myTeamId);
  const nextPickLabel = !isCompleted && myTeamId
    ? picksAway !== null
      ? formatPickLabel(currentPickGlobalIndex + picksAway, numTeams)
      : null
    : null;

  // Persistent, not conditioned on whose turn it is right now -- even
  // during your own turn this doubles as "here's the recommendation" atop
  // an otherwise-unranked-looking list.
  const projected = !isCompleted ? projectNextPick(availablePlayers, myRosterByPos) : null;
  const selectedPlayer = selectedId ? filteredPlayers.find((p) => p.id === selectedId) || null : null;

  const handleRowTap = (player: MobileDraftPlayer) => {
    setSelectedId((prev) => (prev === player.id ? null : player.id));
    onPlayerHover(player, null);
  };

  const availableQueue = queue;

  return (
    <div className="xl:hidden">
      {/* ── Header: status bar + draft train ─────────────────────── */}
      <div className="bg-surface-850 border-b border-surface-700 pt-3 pb-2">
        {/* Draft train */}
        <div className="flex items-center gap-2 px-4 pb-2">
          <div className="flex-1 flex gap-3 overflow-x-auto no-scrollbar" style={{ scrollSnapType: "x proximity" }}>
            {uniqueTeams.map((tid) => (
              <div key={tid} ref={tid === currentTeamId ? currentTeamRef : undefined}>
                <TeamCircle
                  teamId={tid}
                  name={teams[tid]?.name || "Team"}
                  isCurrent={tid === currentTeamId && !isCompleted}
                  isMine={tid === myTeamId}
                />
              </div>
            ))}
          </div>
          {onShowBoard && (
            <button
              onClick={onShowBoard}
              className="shrink-0 p-2 rounded-lg bg-surface-800 border border-surface-700 text-surface-400"
              title="View draft board"
            >
              <Grid3X3 className="w-4 h-4" />
            </button>
          )}
        </div>

        {/* Round number + next-pick timing */}
        <div className="flex items-end justify-between px-4 mt-1">
          <div>
            <span className="text-2xl font-extrabold text-white leading-none">
              {isCompleted ? "DONE" : `ROUND ${currentRound}`}
            </span>
            <span className="text-surface-500 text-xs ml-1.5">/ {totalRounds}</span>
          </div>
          <div className="text-right">
            {isCompleted ? (
              <span className="text-xs text-green-400 font-semibold">Draft complete</span>
            ) : isUserOnClock ? (
              <span className="text-xs text-gold-400 font-bold animate-pulse">
                YOUR PICK{timeLeft !== null && timerSeconds > 0 ? ` — ${timeLeft}s` : ""}
              </span>
            ) : picksAway !== null && nextPickLabel ? (
              <span className="text-xs text-surface-300">
                Your next pick: <span className="font-bold text-white">{nextPickLabel}</span>
                <span className="text-surface-500"> ({picksAway} away)</span>
              </span>
            ) : myTeamId ? (
              // myTeamId is set, but no further occurrence of it in
              // team_order after the current pick -- genuinely no picks
              // left for this team (not "you forgot to claim a team").
              <span className="text-xs text-surface-500">No picks remaining for your team</span>
            ) : (
              <span className="text-xs text-surface-500">Claim a team to track your picks</span>
            )}
          </div>
        </div>

        {/* Last pick */}
        {lastPick?.player && (
          <div className="flex items-center gap-1.5 px-4 mt-2 text-[11px] text-surface-400 truncate">
            <span className="text-surface-600 uppercase tracking-wider font-semibold shrink-0">Last:</span>
            <span className="text-surface-200 font-medium truncate">{lastPick.player.full_name}</span>
            <PositionBadge pos={lastPick.player.position} />
            <span className="text-surface-500 truncate">→ {lastPick.team.name}</span>
          </div>
        )}
      </div>

      {/* ── Your Next Projected Pick ──────────────────────────────── */}
      {projected && (
        <div className="px-4 mt-3">
          <div className="bg-surface-800 border border-surface-700 rounded-2xl p-3 shadow-lg shadow-black/20">
            <div className="flex items-center gap-1.5 mb-2">
              <TrendingUp className="w-3.5 h-3.5 text-gold-400" />
              <span className="text-[10px] font-bold uppercase tracking-wider text-gold-400">
                Your Next Projected Pick
              </span>
            </div>
            <div
              className="flex items-center gap-3"
              onClick={(e) => onPlayerHover(projected.player, e.currentTarget)}
            >
              <PlayerAvatar player={projected.player} size="lg" onHover={onPlayerHover} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-bold text-white truncate">{projected.player.full_name}</span>
                  <PositionBadge pos={projected.player.position} />
                </div>
                <div className="flex items-center gap-2 text-[11px] text-surface-400 mt-0.5">
                  <span>{projected.player.team || "FA"}</span>
                  {projected.player.rank_score < 500 && <span className="text-gold-400/80">Rank #{projected.player.rank_score}</span>}
                </div>
                <span className="text-[10px] text-surface-500">{projected.reason}</span>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onToggleQueue(projected.player);
                }}
                className={`p-2 rounded-lg shrink-0 ${
                  isQueued(projected.player.id) ? "bg-gold-400/20 text-gold-400" : "bg-surface-900 text-surface-400"
                }`}
              >
                <Plus className={`w-4 h-4 transition-transform ${isQueued(projected.player.id) ? "rotate-45" : ""}`} />
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Search + position pills ───────────────────────────────── */}
      <div className="px-4 mt-3 sticky top-[52px] z-20 bg-surface-900/95 backdrop-blur-md pb-2 pt-1">
        <div className="relative mb-2">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-surface-500" />
          <input
            type="text"
            placeholder="Search players..."
            value={searchQuery}
            onChange={(e) => onSearchQueryChange(e.target.value)}
            className="w-full pl-10 pr-3 py-2.5 bg-surface-800 border border-surface-700 rounded-xl text-sm text-white placeholder-surface-500 focus:outline-none focus:ring-1 focus:ring-gold-400"
          />
        </div>
        <div className="flex gap-1.5 overflow-x-auto no-scrollbar pb-0.5">
          <button
            onClick={() => onPositionFilterChange("ALL")}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold shrink-0 transition-all ${
              positionFilter === "ALL"
                ? "bg-gold-400/20 text-gold-400 border border-gold-400/30"
                : "bg-surface-800 text-surface-400 border border-surface-700"
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
                disabled={count === 0}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold shrink-0 transition-all ${
                  positionFilter === pos
                    ? "bg-gold-400/20 text-gold-400 border border-gold-400/30"
                    : count === 0
                      ? "bg-surface-800 text-surface-600 border border-surface-700/50 opacity-50"
                      : "bg-surface-800 text-surface-400 border border-surface-700"
                }`}
              >
                {pos} ({count})
              </button>
            );
          })}
        </div>
      </div>

      {/* ── Player list ────────────────────────────────────────────── */}
      <div className="px-4 pb-28">
        {filteredPlayers.length === 0 ? (
          <div className="py-10 text-center text-surface-500 text-sm">
            {searchQuery ? "No players match your search" : "No players available"}
          </div>
        ) : (
          <div className="divide-y divide-surface-800">
            {filteredPlayers.map((player) => {
              const selected = selectedId === player.id;
              return (
                <div
                  key={player.id}
                  onClick={() => handleRowTap(player)}
                  className={`flex items-center gap-3 py-3 transition-colors ${
                    selected ? "bg-gold-400/10 -mx-4 px-4 rounded-xl" : ""
                  }`}
                >
                  <PlayerAvatar player={player} size="md" onHover={onPlayerHover} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold text-white truncate">{player.full_name}</span>
                      <PositionBadge pos={player.position} />
                    </div>
                    <div className="flex items-center gap-2 text-[11px] text-surface-500 mt-0.5">
                      <span>{player.team || "FA"}</span>
                      {player.rank_score < 500 && <span className="text-gold-400/70">#{player.rank_score}</span>}
                      {player.season_points != null && (
                        <span className="text-surface-400">{Math.round(player.season_points * 10) / 10} pts</span>
                      )}
                    </div>
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onToggleQueue(player);
                    }}
                    className={`p-2 rounded-lg shrink-0 ${
                      isQueued(player.id) ? "bg-gold-400/20 text-gold-400" : "text-surface-500 bg-surface-800"
                    }`}
                  >
                    <Plus className={`w-4 h-4 transition-transform ${isQueued(player.id) ? "rotate-45" : ""}`} />
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ── Sticky bottom action bar ──────────────────────────────── */}
      {!isCompleted && (
        <div className="fixed bottom-0 left-0 right-0 z-30 bg-surface-850/95 backdrop-blur-md border-t border-surface-700 px-4 pt-2.5 pb-[calc(0.625rem+env(safe-area-inset-bottom))]">
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowQueuePanel(true)}
              className="relative flex items-center justify-center gap-1.5 px-3 py-3 rounded-xl bg-surface-800 border border-surface-700 text-surface-300 shrink-0"
            >
              <ListChecks className="w-4 h-4" />
              <span className="text-xs font-semibold">Queue</span>
              {availableQueue.length > 0 && (
                <span className="absolute -top-1.5 -right-1.5 bg-gold-400 text-surface-900 text-[9px] font-bold w-4 h-4 rounded-full flex items-center justify-center">
                  {availableQueue.length}
                </span>
              )}
            </button>

            <button
              onClick={onToggleAutoPickForMe}
              className={`flex items-center justify-center gap-1.5 px-3 py-3 rounded-xl border shrink-0 transition-all ${
                autoPickForMe
                  ? "bg-blue-500/20 border-blue-500/40 text-blue-300"
                  : "bg-surface-800 border-surface-700 text-surface-400"
              }`}
              title="Auto-pick for me when it's my turn"
            >
              <Zap className={`w-4 h-4 ${autoPickForMe ? "fill-blue-300" : ""}`} />
            </button>

            {selectedPlayer ? (
              <button
                onClick={() => onMakePick(selectedPlayer.id)}
                disabled={!isUserOnClock || actionLoading === "pick"}
                className={`flex-1 py-3 rounded-xl font-bold text-sm transition-all flex items-center justify-center gap-2 ${
                  isUserOnClock
                    ? "bg-gold-400 hover:bg-gold-300 text-surface-900 active:scale-[0.98]"
                    : "bg-surface-800 text-surface-500"
                } disabled:opacity-60`}
              >
                {actionLoading === "pick" ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : isUserOnClock ? (
                  `Draft ${selectedPlayer.full_name}`
                ) : (
                  `Select — not your turn`
                )}
              </button>
            ) : (
              <div className="flex-1 py-3 rounded-xl bg-surface-900/60 text-center text-xs text-surface-500 font-medium">
                {isUserOnClock ? "Tap a player to draft" : "On the Clock: " + (teams[currentTeamId || ""]?.name || "—")}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Queue panel (slide-up sheet) ──────────────────────────── */}
      {showQueuePanel && (
        <div className="fixed inset-0 z-40 flex items-end">
          <div className="absolute inset-0 bg-black/60" onClick={() => setShowQueuePanel(false)} />
          <div className="relative w-full max-h-[70vh] bg-surface-850 border-t border-surface-700 rounded-t-3xl flex flex-col">
            <div className="flex items-center justify-between px-4 py-3 border-b border-surface-700">
              <span className="text-sm font-bold text-white">Your Queue ({availableQueue.length})</span>
              <button onClick={() => setShowQueuePanel(false)} className="p-1.5 text-surface-400">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="overflow-y-auto divide-y divide-surface-800 px-4 pb-[calc(1rem+env(safe-area-inset-bottom))]">
              {availableQueue.length === 0 ? (
                <div className="py-8 text-center text-surface-500 text-sm">
                  Queue is empty. Tap <Plus className="w-3 h-3 inline" /> on a player to add them.
                </div>
              ) : (
                availableQueue.map((player, idx) => (
                  <div key={player.id} className="flex items-center gap-3 py-3">
                    <span className="text-surface-500 text-xs font-mono w-5 text-center shrink-0">{idx + 1}</span>
                    <PlayerAvatar player={player} size="sm" onHover={onPlayerHover} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-white truncate">{player.full_name}</span>
                        <PositionBadge pos={player.position} />
                      </div>
                      <span className="text-xs text-surface-500">{player.team || "FA"}</span>
                    </div>
                    <button onClick={() => onToggleQueue(player)} className="p-1.5 rounded-lg text-surface-500">
                      <Plus className="w-4 h-4 rotate-45" />
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
