"use client";

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { draftsApi } from "@/lib/api-client";
import {
  Trophy,
  Users,
  Clock,
  Play,
  Swords,
  Sparkles,
  ChevronLeft,
  CheckCircle2,
  Loader2,
  Search,
  Plus,
  Star,
  User,
  GripVertical,
  List,
  Timer,
  Info,
} from "lucide-react";

import PositionBadge, { POSITION_ORDER } from "@/components/PositionBadge";
import { PlayerAvatar, PlayerCardOverlay } from "@/components/PlayerAvatar";
import TeamBadge from "@/components/TeamBadge";
import DraftHeader from "@/components/DraftHeader";
import PlayerPool from "@/components/PlayerPool";
import TeamRosters from "@/components/TeamRosters";
import BoardView from "@/components/BoardView";
import MobileBoardView from "@/components/MobileBoardView";
import MobileDraftRoom from "@/components/MobileDraftRoom";
import DraftQueuePanel from "@/components/DraftQueuePanel";
import RecentPicksPanel from "@/components/RecentPicksPanel";
import PickHistoryList from "@/components/PickHistoryList";

interface Player {
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
  // Present on the real get_draft_state response (PlayerPool.tsx's own
  // PlayerPoolPlayer already declares these the same way) -- needed here
  // now too since sortPlayers below actually reads them, not just passes
  // them through opaquely.
  headline_stats?: Record<string, number> | null;
  season_points?: number | null;
  season_points_year?: number | null;
  projected_points?: number | null;
}

// Mirrors backend/app/api/v1/players.py's SORT_VALUES, adapted to the
// fields the draft-state payload actually carries (headline_stats is a
// compact, position-specific slice -- not the full raw stat dict the
// standalone /players page's yards/touchdowns sort works from -- so
// "yards"/"touchdowns" here sum whatever headline_stats keys end in
// _yd/_td, which covers every position HEADLINE_STAT_KEYS gives a real
// yard/TD stat to). Client-side only: the pool is already fully loaded
// per poll, so re-sorting a few thousand rows in JS is cheap and needs
// no new API call.
const DRAFT_SORT_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "Default (Rank)" },
  { value: "points", label: "Fantasy Points (last season)" },
  { value: "yards", label: "Yards (last season)" },
  { value: "touchdowns", label: "Touchdowns (last season)" },
  { value: "projected", label: "Projected" },
];

function sumHeadlineStatsBySuffix(stats: Record<string, number> | null | undefined, suffix: string): number {
  if (!stats) return 0;
  return Object.entries(stats).reduce((sum, [k, v]) => (k.endsWith(suffix) ? sum + (v || 0) : sum), 0);
}

// Every comparator below tie-breaks on rank_score (the real, live
// search_rank-based rank -- see draft_manager.build_rank_by_id on the
// backend) whenever the primary value is equal, not just left in
// whatever order the array happened to already be in. Without this,
// "projected" in particular degraded to effectively random order: with
// no real Sleeper projections synced yet this preseason, virtually every
// player ties at the exact same value, and Array.sort's tie behavior
// just preserves array order -- surfacing random deep-bench names above
// real stars, a real reported bug, not a hypothetical edge case.
function sortPlayers<T extends Player>(players: T[], sortBy: string): T[] {
  if (!sortBy) return players; // "" = keep the server-provided rank_score order as-is
  const sorted = [...players];
  switch (sortBy) {
    case "points":
      sorted.sort((a, b) => (b.season_points ?? -Infinity) - (a.season_points ?? -Infinity) || a.rank_score - b.rank_score);
      break;
    case "projected":
      sorted.sort((a, b) => (b.projected_points ?? -Infinity) - (a.projected_points ?? -Infinity) || a.rank_score - b.rank_score);
      break;
    case "yards":
      sorted.sort((a, b) => sumHeadlineStatsBySuffix(b.headline_stats, "_yd") - sumHeadlineStatsBySuffix(a.headline_stats, "_yd") || a.rank_score - b.rank_score);
      break;
    case "touchdowns":
      sorted.sort((a, b) => sumHeadlineStatsBySuffix(b.headline_stats, "_td") - sumHeadlineStatsBySuffix(a.headline_stats, "_td") || a.rank_score - b.rank_score);
      break;
  }
  return sorted;
}

interface DraftPickPlayer {
    id: string;
    full_name: string;
    position: string;
    team: string;
    number: number | null;
    age: number | null;
    bye_week: number | null;
    injury_status: string | null;
    fantasy_positions: string[] | null;
    rank_score: number;
    pos_rank: number;
}

interface DraftPick {
  id: string;
  round: number;
  pick_number: number;
  player: DraftPickPlayer | null;
  team: {
    id: string;
    name: string;
  };
}

interface DraftState {
  draft: {
    id: string;
    league_id: string;
    status: string;
    draft_type: string;
    current_round: number;
    current_pick: number;
    total_rounds: number;
    num_teams: number;
    total_picks: number;
    timer_seconds: number;
    current_pick_started_at: string | null;
  };
  picks: DraftPick[];
  current_team_id: string | null;
  current_team_name: string | null;
  available_players: Player[];
  teams: Record<string, { name: string; owner_id: string | null; co_owner_id: string | null; partner_team_id: string | null }>;
  team_order: string[];
  claimed_teams: Record<string, string>;
}

export default function DraftPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;

  const [draft, setDraft] = useState<DraftState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionLoading, setActionLoading] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [positionFilter, setPositionFilter] = useState("ALL");
  const [sortBy, setSortBy] = useState("");
  const [cpuingPick, setCpuingPick] = useState(false);
  const [showTimerSettings, setShowTimerSettings] = useState(false);
  const [viewMode, setViewMode] = useState<"draft" | "board" | "history">("draft");
  // Which team's roster the roster sidebar (desktop TeamRosters) / roster
  // tab (mobile MobileDraftRoom) currently shows -- shared across both via
  // the same desktop/mobile draft-train tap-to-select circles. Defaults
  // to (and resets to, on claim/unclaim) your own team below.
  const [selectedTeamId, setSelectedTeamId] = useState<string | null>(null);
  const cpuingRef = useRef(false);

  // Fixed hover card state
  const [hoveredPlayer, setHoveredPlayer] = useState<Player | DraftPickPlayer | null>(null);
  const [hoverPos, setHoverPos] = useState<{ x: number; y: number } | null>(null);
  const handlePlayerHover = useCallback((player: Player | DraftPickPlayer | null, el: HTMLElement | null) => {
    if (player && el) {
      setHoveredPlayer(player);
      const rect = el.getBoundingClientRect();
      setHoverPos({ x: rect.left + rect.width / 2, y: rect.top });
    } else {
      setHoveredPlayer(null);
      setHoverPos(null);
    }
  }, []);

  // Queue system
  const [queue, setQueue] = useState<Player[]>([]);

  // Filter + search players. Memoized -- available_players can be
  // thousands of entries (the full undrafted NFL+IDP pool), and this page
  // re-renders for lots of reasons that have nothing to do with the
  // player list (hover state, action-loading toggles, panel expand/
  // collapse, etc.). Without memoizing, every one of those would
  // recompute a brand-new filteredPlayers array reference, which -- since
  // PlayerPool/MobileDraftRoom are wrapped in React.memo -- would defeat
  // that memo and force a full re-reconciliation of the whole list on
  // every unrelated state change. This only recomputes when the real
  // inputs (fresh poll data, or an actual filter/search edit) change.
  //
  // Placed here (above the loading/error early returns below, unlike
  // where this used to live as plain consts after them) because hooks
  // can't follow a conditional return -- these are read directly off
  // `draft` (possibly still null pre-load) rather than the later `allPicks`
  // derived const, which relies on the early returns having already
  // guaranteed draft is non-null by that point.
  const available = useMemo(() => draft?.available_players || [], [draft?.available_players]);
  const draftedIds = useMemo(
    () => new Set((draft?.picks || []).filter(p => p.player).map(p => p.player!.id)),
    [draft?.picks],
  );
  const filteredPlayers = useMemo(() => sortPlayers(available.filter((p) => {
    if (positionFilter !== "ALL" && p.position !== positionFilter) return false;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      return (
        p.full_name.toLowerCase().includes(q) ||
        p.team.toLowerCase().includes(q) ||
        p.position.toLowerCase().includes(q)
      );
    }
    return true;
  }), sortBy), [available, positionFilter, searchQuery, sortBy]);

  // Filter queue to only show still-available players
  const availableQueue = useMemo(
    () => queue.filter(p => !draftedIds.has(p.id)),
    [queue, draftedIds],
  );

  const positionCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    available.forEach((p) => { counts[p.position] = (counts[p.position] || 0) + 1; });
    return counts;
  }, [available]);
  const [showQueue, setShowQueue] = useState(false);
  const [myTeamId, setMyTeamId] = useState<string | null>(null);

  // Mobile draft room's "auto-pick for me" toggle -- session-only (not
  // persisted), off by default. When on, treats the user's own team like
  // a CPU team the instant it's their turn: picks the top of their queue
  // if they have one queued, otherwise defers to the same backend
  // auto-pick the CPU teams already use.
  const [autoPickForMe, setAutoPickForMe] = useState(false);

  // Load claimed team from localStorage on mount (backend claimed_teams is read on each fetchState)
  useEffect(() => {
    if (!draft) return;
    try {
      const stored = JSON.parse(localStorage.getItem("ffc_user_teams") || "{}");
      const localTeamId = stored[draft.draft.league_id];
      if (localTeamId) {
        setMyTeamId(localTeamId);
      }
    } catch {}
  }, [draft?.draft?.league_id]);

  const claimTeam = (teamId: string) => {
    if (!draft?.draft?.league_id) return;
    const userTeams = JSON.parse(localStorage.getItem("ffc_user_teams") || "{}");
    userTeams[draft.draft.league_id] = teamId;
    localStorage.setItem("ffc_user_teams", JSON.stringify(userTeams));
    setMyTeamId(teamId);
  };

  const unclaimTeam = () => {
    if (!draft?.draft?.league_id) return;
    const userTeams = JSON.parse(localStorage.getItem("ffc_user_teams") || "{}");
    delete userTeams[draft.draft.league_id];
    localStorage.setItem("ffc_user_teams", JSON.stringify(userTeams));
    setMyTeamId(null);
  };

  // Reset the roster-view selection to your own team whenever it changes
  // (claim, unclaim, or the localStorage-load effect above resolving) --
  // same default-to-your-team behavior on both mobile and desktop.
  useEffect(() => {
    setSelectedTeamId(myTeamId);
  }, [myTeamId]);

  const fetchState = useCallback(async () => {
    try {
      const state = await draftsApi.getState(id);
      setDraft(state as DraftState);
      setError("");
    } catch {
      setError("Draft not found. Create a draft from your league page.");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchState();
  }, [fetchState]);

  // Auto-refresh every 5 seconds while in progress
  useEffect(() => {
    if (!draft || draft.draft.status !== "in_progress") return;
    const interval = setInterval(fetchState, 5000);
    return () => clearInterval(interval);
  }, [draft?.draft.status, fetchState]);

  const handleStartDraft = async () => {
    setActionLoading("start");
    try {
      await draftsApi.start(id);
      await fetchState();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to start draft");
    }
    setActionLoading("");
  };

  const handleRunMock = async () => {
    setActionLoading("mock");
    try {
      // Dual-Squad (Phase 7): skip BOTH of a claimed pair's teams during
      // mock-fill, not just the one stored in localStorage -- otherwise
      // the mock draft would auto-pick for the manager's second team
      // even though they're the human managing it too.
      const skipIds = Array.from(myTeamIds);
      await draftsApi.runMock(id, skipIds.length > 0 ? skipIds : undefined);
      await fetchState();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Mock draft failed");
    }
    setActionLoading("");
  };

  // useCallback (like handlePlayerHover/fetchState already were) so this
  // stays a stable reference across renders that don't actually need a
  // new one -- part of what lets PlayerPool/MobileDraftRoom's React.memo
  // actually skip re-rendering the player list on unrelated state changes.
  const handleMakePick = useCallback(async (playerId: string) => {
    if (!draft?.current_team_id) return;
    setActionLoading("pick");
    try {
      await draftsApi.makePick(id, draft.current_team_id, playerId);
      // Remove from queue if queued
      setQueue(prev => prev.filter(p => p.id !== playerId));
      await fetchState();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to make pick");
    }
    setActionLoading("");
  }, [draft?.current_team_id, id, fetchState]);

  // No more page-level ticking timer state here -- see PickCountdown.tsx.
  // The deadline is just draft.draft.current_pick_started_at, which is
  // already page state that only changes when a pick actually starts;
  // PlayerPool/MobileDraftRoom each own their own 500ms tick internally
  // now, instead of that tick forcing this whole page (and its
  // potentially thousands-of-rows player list) to re-render twice a
  // second regardless of whose clock is running.

  // Dual-Squad/Mirror (Phase 7): a claimed team's turn AND its linked
  // partner's turn both count as "mine" -- only one of the pair is ever
  // stored in localStorage (ffc_user_teams), so without this a claimed
  // pair's own partner-team turns would never be recognized as the
  // user's, even though claim_team already claimed both as owner.
  const myTeamIds = useMemo(() => {
    if (!myTeamId) return new Set<string>();
    const ids = new Set([myTeamId]);
    const partnerId = draft?.teams?.[myTeamId]?.partner_team_id;
    if (partnerId) ids.add(partnerId);
    return ids;
  }, [myTeamId, draft?.teams]);

  const isUserOnClock = (): boolean => {
    if (!draft || !draft.current_team_id) return false;
    return myTeamIds.has(draft.current_team_id);
  };

  // CPU auto-pick: sequential, no racing
  const doCpuPick = useCallback(async () => {
    if (!draft || draft.draft.status !== "in_progress") return;
    if (!draft.current_team_id) return;
    if (isUserOnClock()) return;
    if (cpuingRef.current) return;

    cpuingRef.current = true;
    setCpuingPick(true);
    try {
      await draftsApi.autoPick(id);
      await fetchState();
    } catch {
      // draft may be complete
    } finally {
      cpuingRef.current = false;
      setCpuingPick(false);
    }
  }, [draft, id]);

  // Trigger CPU auto-pick when it's a CPU team's turn
  useEffect(() => {
    if (!draft || draft.draft.status !== "in_progress") return;
    if (!draft.current_team_id) return;
    if (isUserOnClock()) return;

    const timer = setTimeout(() => doCpuPick(), 600);
    return () => clearTimeout(timer);
  }, [draft?.current_team_id, draft?.draft?.status, draft?.draft?.current_pick, draft?.draft?.current_round, doCpuPick]);

  // Auto-pick when the user's own timer expires. Previously driven by
  // watching the page-level ticking `timeLeft` state cross to 0 (removed
  // -- see PickCountdown.tsx for why that state doesn't live here
  // anymore) -- a single setTimeout scheduled for the exact deadline does
  // the same job without needing a 500ms tick anywhere on this page. Only
  // reschedules when a new pick actually starts or turn ownership
  // changes, not on every poll (current_pick_started_at/timer_seconds
  // are stable across polls of the same in-progress pick).
  useEffect(() => {
    if (!draft || !isUserOnClock()) return;
    const startedAt = draft.draft.current_pick_started_at;
    const timer = draft.draft.timer_seconds;
    if (!startedAt || !timer || timer <= 0) return;

    const doAutoPick = () => {
      draftsApi.autoPick(id).then(() => fetchState()).catch(() => {});
    };
    const msLeft = new Date(startedAt).getTime() + timer * 1000 - Date.now();
    if (msLeft <= 0) {
      doAutoPick();
      return;
    }
    const t = setTimeout(doAutoPick, msLeft);
    return () => clearTimeout(t);
  }, [draft?.draft.current_pick_started_at, draft?.draft.timer_seconds, draft?.current_team_id, myTeamId, id, fetchState]);

  // Auto-pick from queue when it's user's turn
  useEffect(() => {
    if (!draft || !isUserOnClock() || cpuingRef.current || queue.length === 0) return;
    // Find the first queued player still available
    const draftedIds = new Set(draft.picks.filter(p => p.player).map(p => p.player!.id));
    const availableQueued = queue.filter(p => !draftedIds.has(p.id));
    if (availableQueued.length === 0) return;
    // Auto-pick after a short delay so user can override
    cpuingRef.current = true;
    setCpuingPick(true);
    const timeout = setTimeout(async () => {
      try {
        const top = availableQueued[0];
        await draftsApi.makePick(id, draft.current_team_id!, top.id);
        setQueue(prev => prev.filter(p => p.id !== top.id));
        await fetchState();
      } catch {} finally { cpuingRef.current = false; setCpuingPick(false); }
    }, 1500);
    return () => { clearTimeout(timeout); cpuingRef.current = false; setCpuingPick(false); };
  }, [draft?.current_team_id, draft?.draft?.status, draft?.draft?.current_pick, myTeamId, queue.length]);

  // "Auto-pick for me" toggle (mobile draft room): when on, treat the
  // user's own turn like a CPU team's -- pick immediately rather than
  // waiting for the timer to run out. The queue-auto-pick effect above
  // isn't gated behind this toggle (having something queued already
  // means "draft this for me" on its own), so this only covers the
  // empty-queue case -- deferring to the same backend auto-pick the CPU
  // teams use.
  useEffect(() => {
    if (!autoPickForMe || !draft || !isUserOnClock() || cpuingRef.current) return;
    const draftedIds = new Set(draft.picks.filter(p => p.player).map(p => p.player!.id));
    const hasQueuedAvailable = queue.some(p => !draftedIds.has(p.id));
    if (hasQueuedAvailable) return; // the queue effect above will handle it

    cpuingRef.current = true;
    setCpuingPick(true);
    const timeout = setTimeout(async () => {
      try {
        await draftsApi.autoPick(id);
        await fetchState();
      } catch {
        // draft may be complete
      } finally {
        cpuingRef.current = false;
        setCpuingPick(false);
      }
    }, 800);
    return () => { clearTimeout(timeout); cpuingRef.current = false; setCpuingPick(false); };
  }, [autoPickForMe, draft?.current_team_id, draft?.draft?.status, draft?.draft?.current_pick, myTeamId, queue.length]);

  const handleSetTimer = async (seconds: number) => {
    try {
      await draftsApi.setTimer(id, seconds);
      await fetchState();
      setShowTimerSettings(false);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to set timer");
    }
  };

  const toggleQueue = useCallback((player: Player) => {
    setQueue(prev => {
      const exists = prev.find(p => p.id === player.id);
      if (exists) return prev.filter(p => p.id !== player.id);
      return [...prev, player];
    });
  }, []);

  const isQueued = useCallback((playerId: string) => queue.some(p => p.id === playerId), [queue]);

  // Build team rosters
  const teamRosters: Record<string, DraftPick[]> = {};
  if (draft) {
    draft.picks.filter(p => p.player).forEach(p => {
      if (!teamRosters[p.team.id]) teamRosters[p.team.id] = [];
      teamRosters[p.team.id].push(p);
    });
  }

  // Loading state
  if (loading) {
    return (
      <div className="min-h-screen bg-surface-900 flex items-center justify-center">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 border-2 border-gold-400 border-t-transparent rounded-full animate-spin" />
          <span className="text-surface-400">Loading draft room...</span>
        </div>
      </div>
    );
  }

  if (error && !draft) {
    return (
      <div className="min-h-screen bg-surface-900 flex items-center justify-center">
        <div className="text-center max-w-md">
          <div className="w-16 h-16 rounded-2xl bg-surface-800 border border-surface-700 flex items-center justify-center mx-auto mb-4">
            <Swords className="w-8 h-8 text-gold-400/60" />
          </div>
          <h2 className="text-xl font-semibold text-white mb-2">Draft Room</h2>
          <p className="text-surface-400 text-sm mb-4">{error}</p>
          <Link href="/dashboard" className="text-gold-400 hover:text-gold-300 text-sm font-medium">
            Back to Dashboard
          </Link>
        </div>
      </div>
    );
  }

  // PENDING state
  if (draft && draft.draft.status === "pending") {
    return (
      <div className="min-h-screen bg-surface-900">
        <div className="max-w-425 mx-auto px-4 sm:px-6 lg:px-8 py-10">
          <Link href={`/leagues/${draft.draft.league_id}`} className="inline-flex items-center gap-1 text-surface-400 hover:text-gold-400 transition-colors text-sm mb-8">
            <ChevronLeft className="w-4 h-4" /> Back to League
          </Link>
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <div className="w-24 h-24 rounded-3xl bg-surface-800 border border-surface-700 flex items-center justify-center mb-6">
              <Swords className="w-12 h-12 text-gold-400/60" />
            </div>
            <h1 className="text-3xl font-bold text-white mb-2">Draft Ready</h1>
            <p className="text-surface-400 text-sm mb-2">
              {draft.draft.num_teams} teams · {draft.draft.total_rounds} rounds · Snake
            </p>
            <p className="text-surface-500 text-xs mb-8">
              {draft.draft.draft_type === "snake" ? "Serpentine order, randomized" : "Budget auction draft"}
            </p>
            {/* Team claiming before start */}
            {draft.team_order && draft.team_order.length > 0 && (
              <div className="mb-8 w-full max-w-md">
                <h3 className="text-sm font-semibold text-surface-400 uppercase tracking-wider mb-3">Select Your Team</h3>
                <div className="grid grid-cols-2 gap-2">
                  {draft.team_order.filter((tId, i, arr) => arr.indexOf(tId) === i).map((teamId) => {
                    const team = draft.teams[teamId];
                    const isMine = myTeamId === teamId;
                    return (
                      <button
                        key={teamId}
                        onClick={() => isMine ? unclaimTeam() : claimTeam(teamId)}
                        className={`px-4 py-3 rounded-xl text-sm font-semibold border transition-all ${
                          isMine
                            ? "bg-gold-400/20 border-gold-400/40 text-gold-400 ring-1 ring-gold-400/30"
                            : "bg-surface-800 border-surface-700 text-surface-300 hover:border-gold-400/30 hover:text-white"
                        }`}
                      >
                        <div className="flex items-center justify-center gap-2">
                          {team?.name || `Team ${teamId.slice(0, 4)}`}
                          {isMine && <Star className="w-3.5 h-3.5 fill-gold-400" />}
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
            <div className="flex gap-4">
              <button
                onClick={handleStartDraft}
                disabled={actionLoading === "start"}
                className="inline-flex items-center gap-2 bg-gold-400 hover:bg-gold-300 text-surface-900 px-8 py-3.5 rounded-xl font-bold transition-all hover:shadow-xl hover:shadow-gold-400/30 active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {actionLoading === "start" ? (
                  <><Loader2 className="w-5 h-5 animate-spin" /> Starting...</>
                ) : (
                  <><Play className="w-5 h-5" /> Start Draft</>
                )}
              </button>
              <button
                onClick={handleRunMock}
                disabled={actionLoading === "mock"}
                className="inline-flex items-center gap-2 border border-surface-600 hover:border-surface-500 text-surface-300 hover:text-white px-8 py-3.5 rounded-xl font-bold transition-all disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {actionLoading === "mock" ? (
                  <><Loader2 className="w-5 h-5 animate-spin" /> Running...</>
                ) : (
                  <><Sparkles className="w-5 h-5" /> Auto-Fill CPUs</>
                )}
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // --- DRAFT IN PROGRESS / COMPLETED ---
  const draftInfo = draft!.draft;
  const allPicks = draft!.picks.sort((a, b) => a.pick_number - b.pick_number);
  const isCompleted = draftInfo.status === "completed";
  const team_order = draft!.team_order || [];

  // The backend only creates a Pick row once a pick is actually made --
  // there's no placeholder row for the upcoming pick, so it can never be
  // found via allPicks.findIndex((p) => !p.player) (that used to be the
  // logic here; it always returned -1, which silently broke the "on the
  // clock" banner, the board's active-cell glow, and the "on deck" teams
  // below). Instead, derive the 0-based global pick index the same way
  // draft_manager.py does it server-side (current_round/current_pick are
  // the DB-authoritative, CAS-protected source of truth -- see
  // draft_manager.py's advance_pick, which uses this identical formula),
  // rather than re-inferring it from allPicks.length.
  const currentPickIndex =
    (draftInfo.current_round - 1) * draftInfo.num_teams + (draftInfo.current_pick - 1);
  const currentPick =
    !isCompleted && currentPickIndex < draftInfo.total_picks
      ? {
          id: `pending-${currentPickIndex}`,
          round: draftInfo.current_round,
          pick_number: currentPickIndex + 1,
          player: null,
          team: {
            id: draft?.current_team_id || "",
            name: draft?.current_team_name || "Unknown",
          },
        }
      : null;

  // Last pick made
  const completedPicks = allPicks.filter(p => p.player);
  const lastPick = completedPicks.length > 0 ? completedPicks[completedPicks.length - 1] : null;

  // 2-Man team on-the-clock indicator: a display convention only (either
  // owner or co-owner can already submit the pick via the backend's own
  // team-scoped authorization -- see draft_manager.make_pick, which has
  // no concept of "which human" at all). Alternates by parity of how many
  // times this specific team has already picked, so both managers get a
  // predictable, even turn order rather than whoever's faster every round.
  const currentTeamInfo = draft?.current_team_id ? draft.teams[draft.current_team_id] : null;
  const currentTeamHasCoOwner = !!currentTeamInfo?.co_owner_id;
  const picksByCurrentTeam = completedPicks.filter(p => p.team.id === draft?.current_team_id).length;
  const onClockManagerIsOwner = picksByCurrentTeam % 2 === 0;

  // Next teams up (on deck) — show next 2 unique teams
  const nextTwoTeamNames: string[] = [];
  if (currentPick && !isCompleted) {
    const seen = new Set<string>();
    for (let i = currentPickIndex + 1; i < team_order.length && nextTwoTeamNames.length < 2; i++) {
      const tid = team_order[i];
      if (tid && !seen.has(tid)) {
        seen.add(tid);
        const t = draft?.teams[tid];
        nextTwoTeamNames.push(t?.name || "Unknown");
      }
    }
  }

  // First-round team order for board column headers
  const firstRoundTeams = draft && team_order.length > 0
    ? team_order.slice(0, draftInfo.num_teams).map(tid => ({ id: tid, ...draft.teams[tid] })).filter(Boolean)
    : [];

  const currentRound = isCompleted ? draftInfo.total_rounds : draftInfo.current_round;

  // Build my team roster by position
  const myPicks = myTeamId ? (teamRosters[myTeamId] || []) : [];
  const myRosterByPos: Record<string, DraftPick[]> = {};
  myPicks.forEach(p => {
    const pos = p.player?.position || "UNKNOWN";
    if (!myRosterByPos[pos]) myRosterByPos[pos] = [];
    myRosterByPos[pos].push(p);
  });

  return (
    <div className="min-h-screen bg-surface-900">
      {/* Error banner */}
      {error && (
        <div className="bg-red-500/10 border-b border-red-500/20 px-4 py-2 text-center" role="alert">
          <span className="text-red-400 text-sm">{error}</span>
          <button onClick={() => setError("")} className="ml-2 text-red-300 hover:text-red-200" aria-label="Dismiss error">×</button>
        </div>
      )}

      {/* Draft complete — nothing used to point people anywhere from here */}
      {isCompleted && (
        <div className="bg-gold-400/10 border-b border-gold-400/25 px-4 py-3">
          <div className="max-w-425 mx-auto flex flex-col sm:flex-row items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-gold-300">
              <Trophy className="w-5 h-5" />
              <span className="font-semibold">Draft complete!</span>
              <span className="text-surface-300 text-sm hidden sm:inline">
                Head to the league to see standings and matchups.
              </span>
            </div>
            <Link
              href={`/leagues/${draftInfo.league_id}`}
              className="inline-flex items-center gap-1.5 bg-gold-400 hover:bg-gold-300 text-surface-900 px-4 py-2 rounded-xl text-sm font-semibold transition-all"
            >
              View League
              <ChevronLeft className="w-4 h-4 rotate-180" />
            </Link>
          </div>
        </div>
      )}

      {/* Draft Header */}
      <DraftHeader
        leagueId={draftInfo.league_id}
        isCompleted={isCompleted}
        currentRound={currentRound}
        totalRounds={draftInfo.total_rounds}
        totalPicks={draftInfo.total_picks}
        completedPicks={completedPicks.length}
        timerSeconds={draftInfo.timer_seconds}
        pickStartedAt={draft?.draft.current_pick_started_at || null}
        showTimerSettings={showTimerSettings}
        viewMode={viewMode}
        actionLoading={actionLoading}
        onViewModeChange={setViewMode}
        onSetTimer={handleSetTimer}
        onToggleTimerSettings={() => setShowTimerSettings(!showTimerSettings)}
        onRunMock={handleRunMock}
        teamOrder={team_order}
        teams={draft?.teams || {}}
        currentTeamId={draft?.current_team_id || null}
        currentPickGlobalIndex={currentPickIndex}
        numTeams={draftInfo.num_teams}
        myTeamId={myTeamId}
        selectedTeamId={selectedTeamId}
        onSelectTeamId={setSelectedTeamId}
      />

      {/* BODY — Two modes */}
      {/* max-w-425 (1700px), not max-w-7xl (1280px) -- see DraftHeader.tsx's
          comment on its own matching container. The desktop 3-column
          layout below (two fixed 300px side panels + PlayerPool) needs
          real room; at 1280px the center player list's name column was
          measured at 14px wide (verified via CDP), which is what the
          reported "player names overlapping" bug actually was. */}
      <div className="max-w-425 mx-auto px-4 sm:px-6 lg:px-8 py-4">
        {/* Panel layout for draft mode */}
        {viewMode === "draft" && (
          <>
          <MobileDraftRoom
            teamOrder={team_order}
            teams={draft?.teams || {}}
            currentTeamId={draft?.current_team_id || null}
            currentPickGlobalIndex={currentPickIndex}
            numTeams={draftInfo.num_teams}
            totalPicks={draftInfo.total_picks}
            currentRound={currentRound}
            totalRounds={draftInfo.total_rounds}
            isCompleted={isCompleted}
            myTeamId={myTeamId}
            currentTeamHasCoOwner={currentTeamHasCoOwner}
            onClockManagerIsOwner={onClockManagerIsOwner}
            lastPick={lastPick}
            availablePlayers={available}
            myRosterByPos={myRosterByPos}
            teamRosters={teamRosters}
            selectedTeamId={selectedTeamId}
            onSelectTeamId={setSelectedTeamId}
            filteredPlayers={filteredPlayers}
            searchQuery={searchQuery}
            onSearchQueryChange={setSearchQuery}
            positionFilter={positionFilter}
            onPositionFilterChange={setPositionFilter}
            sortBy={sortBy}
            onSortByChange={setSortBy}
            positionCounts={positionCounts}
            availableCount={available.length}
            isUserOnClock={isUserOnClock()}
            actionLoading={actionLoading}
            onMakePick={handleMakePick}
            onToggleQueue={toggleQueue}
            isQueued={isQueued}
            queue={availableQueue}
            pickStartedAt={draft?.draft.current_pick_started_at || null}
            timerSeconds={draftInfo.timer_seconds}
            autoPickForMe={autoPickForMe}
            onToggleAutoPickForMe={() => setAutoPickForMe((prev) => !prev)}
            onPlayerHover={handlePlayerHover}
            onShowBoard={() => setViewMode("board")}
          />
          <div className="hidden xl:flex xl:flex-row gap-4">
            {/* LEFT: Pick Queue/Autopick + My Team + League Rosters */}
            <div className="w-[300px] shrink-0 space-y-4">
              <DraftQueuePanel
                queue={availableQueue}
                isUserOnClock={isUserOnClock()}
                actionLoading={actionLoading}
                onMakePick={handleMakePick}
                onToggleQueue={toggleQueue}
                autoPickForMe={autoPickForMe}
                onToggleAutoPickForMe={() => setAutoPickForMe((prev) => !prev)}
                onPlayerHover={handlePlayerHover}
              />
              <TeamRosters
                myTeamId={myTeamId}
                team_order={team_order}
                teams={draft?.teams || {}}
                teamRosters={teamRosters}
                selectedTeamId={selectedTeamId}
                onSelectTeamId={setSelectedTeamId}
                onClaimTeam={claimTeam}
                onUnclaimTeam={unclaimTeam}
                onPlayerHover={handlePlayerHover}
              />
            </div>

            {/* CENTER: Player pool */}
            <PlayerPool
              filteredPlayers={filteredPlayers}
              searchQuery={searchQuery}
              onSearchQueryChange={setSearchQuery}
              positionFilter={positionFilter}
              onPositionFilterChange={setPositionFilter}
              sortBy={sortBy}
              onSortByChange={setSortBy}
              positionCounts={positionCounts}
              availableCount={available.length}
              isUserOnClock={isUserOnClock()}
              isCompleted={isCompleted}
              actionLoading={actionLoading}
              onMakePick={handleMakePick}
              onToggleQueue={toggleQueue}
              isQueued={isQueued}
              availableQueue={availableQueue}
              showQueue={showQueue}
              onShowQueueChange={setShowQueue}
              currentPick={currentPick}
              pickStartedAt={draft?.draft.current_pick_started_at || null}
              timerSeconds={draftInfo.timer_seconds}
              totalPicks={draftInfo.total_picks}
              cpuingPick={cpuingPick}
              draftCurrentTeamName={draft?.current_team_name || null}
              myTeamId={myTeamId}
              currentTeamHasCoOwner={currentTeamHasCoOwner}
              onClockManagerIsOwner={onClockManagerIsOwner}
              lastPick={lastPick}
              nextTwoTeamNames={nextTwoTeamNames}
              onPlayerHover={handlePlayerHover}
            />

            {/* RIGHT: Recent Picks feed */}
            <div className="w-[300px] shrink-0">
              <div className="xl:sticky xl:top-20">
                <RecentPicksPanel
                  picks={[...completedPicks].reverse().slice(0, 25)}
                  myTeamId={myTeamId}
                  onPlayerHover={handlePlayerHover}
                />
              </div>
            </div>
          </div>
          </>
        )}

        {/* BOARD MODE: Team Column × Round Row Grid */}
        {viewMode === "board" && (
          <>
            {/* Large, prominent, top-of-page -- board grids can run long
                (many rounds x many teams), and the old bottom-only mobile
                button required scrolling all the way through it first.
                Shown on both mobile and desktop now (desktop previously
                had no dedicated back-to-draft control at all outside the
                small header view-mode tabs). */}
            <button
              onClick={() => setViewMode("draft")}
              className="w-full mb-4 py-4 bg-gold-400 hover:bg-gold-300 text-surface-900 rounded-xl text-base font-bold transition-all flex items-center justify-center gap-2 shadow-lg shadow-gold-400/10"
            >
              <List className="w-5 h-5" /> Back to Draft
            </button>
            {/* Mobile: the round x team grid is unreadable at phone width
                (too many narrow columns) -- a stack of per-team roster
                cards (the same style the "Rosters" tab already uses)
                instead. Desktop keeps the real grid, which is what
                actually needs the wide screen. */}
            <div className="xl:hidden">
              <MobileBoardView
                team_order={team_order}
                teams={draft?.teams || {}}
                teamRosters={teamRosters}
                myTeamId={myTeamId}
                onPlayerHover={handlePlayerHover}
              />
            </div>
            <div className="hidden xl:block">
              <BoardView
                isCompleted={isCompleted}
                draftInfo={draftInfo}
                team_order={team_order}
                teams={draft?.teams || {}}
                allPicks={allPicks}
                currentPick={currentPick}
                myTeamId={myTeamId}
                firstRoundTeams={firstRoundTeams}
                onPlayerHover={handlePlayerHover}
              />
            </div>
          </>
        )}

        {/* PICK HISTORY MODE: full chronological list -- desktop-only entry
            point (DraftHeader's History tab is hidden below lg), but the
            viewMode itself works from any screen size. */}
        {viewMode === "history" && (
          <PickHistoryList
            picks={completedPicks}
            numTeams={draftInfo.num_teams}
            myTeamId={myTeamId}
            onPlayerHover={handlePlayerHover}
          />
        )}

      </div>

      {/* Fixed hover card overlay — escapes all containers */}
      <PlayerCardOverlay player={hoveredPlayer} position={hoverPos} onDismiss={() => handlePlayerHover(null, null)} />
    </div>
  );
}
