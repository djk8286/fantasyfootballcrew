"use client";

import { useState, useEffect, useCallback, useRef } from "react";
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
  Grid3X3,
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
  teams: Record<string, { name: string }>;
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
  const [timeLeft, setTimeLeft] = useState<number | null>(null);
  const [cpuingPick, setCpuingPick] = useState(false);
  const [showTimerSettings, setShowTimerSettings] = useState(false);
  const [viewMode, setViewMode] = useState<"draft" | "board">("draft");
  const [expandedTeams, setExpandedTeams] = useState<Record<string, boolean>>({});
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
  const [showQueue, setShowQueue] = useState(false);
  const [myTeamId, setMyTeamId] = useState<string | null>(null);

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
      const skipIds = myTeamId ? [myTeamId] : [];
      await draftsApi.runMock(id, skipIds.length > 0 ? skipIds : undefined);
      await fetchState();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Mock draft failed");
    }
    setActionLoading("");
  };

  const handleMakePick = async (playerId: string) => {
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
  };

  // Timer countdown
  useEffect(() => {
    if (!draft || draft.draft.status !== "in_progress" || !draft.draft.current_pick_started_at) {
      setTimeLeft(null);
      return;
    }
    const timer = draft.draft.timer_seconds;
    if (!timer || timer <= 0) { setTimeLeft(null); return; }
    const updateTimer = () => {
      const started = new Date(draft.draft.current_pick_started_at!).getTime();
      const elapsed = (Date.now() - started) / 1000;
      setTimeLeft(Math.max(0, Math.ceil(timer - elapsed)));
    };
    updateTimer();
    const interval = setInterval(updateTimer, 500);
    return () => clearInterval(interval);
  }, [draft?.draft.status, draft?.draft.current_pick_started_at, draft?.draft.timer_seconds]);

  const isUserOnClock = (): boolean => {
    if (!draft || !draft.current_team_id) return false;
    return myTeamId === draft.current_team_id;
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

  // Auto-pick when user's timer expires
  useEffect(() => {
    if (!draft || timeLeft === null || timeLeft > 0 || !isUserOnClock()) return;
    const doAutoPick = async () => {
      try { await draftsApi.autoPick(id); await fetchState(); } catch {}
    };
    doAutoPick();
  }, [timeLeft]);

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

  const handleSetTimer = async (seconds: number) => {
    try {
      await draftsApi.setTimer(id, seconds);
      await fetchState();
      setShowTimerSettings(false);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to set timer");
    }
  };

  const toggleQueue = (player: Player) => {
    setQueue(prev => {
      const exists = prev.find(p => p.id === player.id);
      if (exists) return prev.filter(p => p.id !== player.id);
      return [...prev, player];
    });
  };

  const isQueued = (playerId: string) => queue.some(p => p.id === playerId);

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
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
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

  const currentPickIndex = allPicks.findIndex((p) => !p.player);
  const currentPick = currentPickIndex >= 0 ? allPicks[currentPickIndex] : null;

  // Last pick made
  const completedPicks = allPicks.filter(p => p.player);
  const lastPick = completedPicks.length > 0 ? completedPicks[completedPicks.length - 1] : null;

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

  // Filter + search players
  const available = draft!.available_players || [];
  const draftedIds = new Set(allPicks.filter(p => p.player).map(p => p.player!.id));
  const filteredPlayers = available.filter((p) => {
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
  });

  // Filter queue to only show still-available players
  const availableQueue = queue.filter(p => !draftedIds.has(p.id));

  const positionCounts: Record<string, number> = {};
  available.forEach((p) => { positionCounts[p.position] = (positionCounts[p.position] || 0) + 1; });

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
        <div className="bg-red-500/10 border-b border-red-500/20 px-4 py-2 text-center">
          <span className="text-red-400 text-sm">{error}</span>
          <button onClick={() => setError("")} className="ml-2 text-red-300 hover:text-red-200">×</button>
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
        timeLeft={timeLeft}
        showTimerSettings={showTimerSettings}
        viewMode={viewMode}
        actionLoading={actionLoading}
        onViewModeChange={setViewMode}
        onSetTimer={handleSetTimer}
        onToggleTimerSettings={() => setShowTimerSettings(!showTimerSettings)}
        onRunMock={handleRunMock}
      />

      {/* BODY — Two modes */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
        {/* Panel layout for draft mode */}
        {viewMode === "draft" && (
          <div className="flex flex-col xl:flex-row gap-4">
            {/* MAIN: Player pool + Queue */}
            <PlayerPool
              filteredPlayers={filteredPlayers}
              searchQuery={searchQuery}
              onSearchQueryChange={setSearchQuery}
              positionFilter={positionFilter}
              onPositionFilterChange={setPositionFilter}
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
              timeLeft={timeLeft}
              timerSeconds={draftInfo.timer_seconds}
              totalPicks={draftInfo.total_picks}
              cpuingPick={cpuingPick}
              draftCurrentTeamName={draft?.current_team_name || null}
              myTeamId={myTeamId}
              lastPick={lastPick}
              nextTwoTeamNames={nextTwoTeamNames}
              onPlayerHover={handlePlayerHover}
            />

            {/* RIGHT PANEL: My Team + Team Rosters */}
            <TeamRosters
              myTeamId={myTeamId}
              myPicks={myPicks}
              myRosterByPos={myRosterByPos}
              team_order={team_order}
              teams={draft?.teams || {}}
              teamRosters={teamRosters}
              isCompleted={isCompleted}
              currentTeamId={draft?.current_team_id || null}
              expandedTeams={expandedTeams}
              onToggleExpand={(teamId) =>
                setExpandedTeams((prev) => ({ ...prev, [teamId]: !prev[teamId] }))
              }
              onClaimTeam={claimTeam}
              onUnclaimTeam={unclaimTeam}
            />
          </div>
        )}

        {/* BOARD MODE: Team Column × Round Row Grid */}
        {viewMode === "board" && (
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
        )}

        {/* Mobile: Draft Board toggle at bottom */}
        {viewMode === "draft" && (
          <div className="mt-4 xl:hidden">
            <button onClick={() => setViewMode("board")}
              className="w-full py-3 bg-surface-800 border border-surface-700 rounded-xl text-sm font-semibold text-surface-300 hover:text-white transition-all flex items-center justify-center gap-2"
            >
              <Grid3X3 className="w-4 h-4" /> View Draft Board
            </button>
          </div>
        )}
        {viewMode === "board" && (
          <div className="mt-4 xl:hidden">
            <button onClick={() => setViewMode("draft")}
              className="w-full py-3 bg-surface-800 border border-surface-700 rounded-xl text-sm font-semibold text-surface-300 hover:text-white transition-all flex items-center justify-center gap-2"
            >
              <List className="w-4 h-4" /> Back to Draft
            </button>
          </div>
        )}
      </div>

      {/* Fixed hover card overlay — escapes all containers */}
      <PlayerCardOverlay player={hoveredPlayer} position={hoverPos} />
    </div>
  );
}
