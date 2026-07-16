"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { standingsApi, leaguesApi } from "@/lib/api-client";
import { getAvatarStyle } from "@/lib/team-avatars";
import RankBadge from "@/components/ui/RankBadge";
import {
  ChevronRight,
  Trophy,
  Users,
  Loader2,
  AlertTriangle,
  RefreshCw,
  Calculator,
  Award,
  ChevronDown,
} from "lucide-react";

// ─── Interfaces ───────────────────────────────────────────────

interface Standing {
  id: string;
  name: string;
  owner_id: string | null;
  is_cpu: boolean;
  wins: number;
  losses: number;
  ties: number;
  points_for: number;
  points_against: number;
  avatar_url: string | null;
}

interface Matchup {
  home_team: string;
  home_team_id: string;
  home_score: number;
  away_team: string;
  away_team_id: string;
  away_score: number;
  week: number;
}

interface WeeklyScoresResponse {
  week: number;
  year: number;
  matchups: Matchup[];
}

interface LeagueData {
  id: string;
  name: string;
  commissioner_id: string;
  co_commissioner_ids: string[] | null;
  league_type: string;
  max_teams: number;
  team_count: number | null;
  draft_status: string;
  description: string | null;
}

// ─── Helpers ──────────────────────────────────────────────────

const CURRENT_YEAR = new Date().getFullYear();

function getCurrentUserId(): string {
  if (typeof window === "undefined") return "placeholder";
  return localStorage.getItem("ffc_user_id") || "placeholder";
}

function getMyTeamId(leagueId: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    const stored = JSON.parse(localStorage.getItem("ffc_user_teams") || "{}");
    return stored[leagueId] || null;
  } catch {
    return null;
  }
}

// ─── Component ────────────────────────────────────────────────

export default function StandingsPage() {
  const params = useParams();
  const leagueId = params.id as string;

  const [league, setLeague] = useState<LeagueData | null>(null);
  const [standings, setStandings] = useState<Standing[]>([]);
  const [weeklyData, setWeeklyData] = useState<WeeklyScoresResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Week selector
  const [selectedWeek, setSelectedWeek] = useState(1);
  const [maxWeek, setMaxWeek] = useState(1);

  // Calculate state
  const [calculating, setCalculating] = useState(false);
  const [calcMessage, setCalcMessage] = useState("");

  const myTeamId = getMyTeamId(leagueId);
  const currentUserId = getCurrentUserId();
  const isCommissioner =
    league && currentUserId === league.commissioner_id;
  const isCoCommissioner =
    league && league.co_commissioner_ids?.includes(currentUserId);
  const isLeagueManager = isCommissioner || isCoCommissioner;

  // ─── Data fetching ─────────────────────────────────────

  useEffect(() => {
    if (!leagueId) return;

    Promise.all([
      leaguesApi.get(leagueId).catch(() => null),
      standingsApi.getStandings(leagueId).catch(() => [] as Standing[]),
    ])
      .then(([leagueData, standingData]) => {
        if (!leagueData) {
          setError("League not found");
          return;
        }
        setLeague(leagueData as LeagueData);
        const st = Array.isArray(standingData) ? (standingData as Standing[]) : [];
        setStandings(st);

        // Determine max week — try to infer from data or default to 1
        const wk = st.length > 0 ? Math.max(1, Math.ceil((st[0] as any)?.week || 1)) : 1;
        setMaxWeek(wk);
        setSelectedWeek(wk);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Failed to load standings");
      })
      .finally(() => setLoading(false));
  }, [leagueId]);

  // Fetch weekly scores when week changes
  useEffect(() => {
    if (!leagueId || !selectedWeek) return;

    standingsApi
      .getWeeklyScores(leagueId, selectedWeek, CURRENT_YEAR)
      .then((data) => {
        setWeeklyData(data as WeeklyScoresResponse);
      })
      .catch(() => {
        setWeeklyData(null);
      });
  }, [leagueId, selectedWeek]);

  // ─── Actions ────────────────────────────────────────────

  const handleCalculate = async () => {
    if (!leagueId) return;
    setCalculating(true);
    setCalcMessage("");
    try {
      const result = await standingsApi.calculateWeek(leagueId, selectedWeek, CURRENT_YEAR);
      setCalcMessage(`Week ${selectedWeek} scores calculated successfully!`);
      // Refresh standings and weekly data
      const newStandings = await standingsApi.getStandings(leagueId);
      setStandings(Array.isArray(newStandings) ? (newStandings as Standing[]) : []);
      const newWeekly = await standingsApi.getWeeklyScores(leagueId, selectedWeek, CURRENT_YEAR);
      setWeeklyData(newWeekly as WeeklyScoresResponse);
      // Clear message after 3 seconds
      setTimeout(() => setCalcMessage(""), 3000);
    } catch (err) {
      setCalcMessage(
        err instanceof Error ? `Error: ${err.message}` : "Failed to calculate scores"
      );
    }
    setCalculating(false);
  };

  const handleRefresh = async () => {
    setLoading(true);
    try {
      const data = await standingsApi.getStandings(leagueId);
      setStandings(Array.isArray(data) ? (data as Standing[]) : []);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to refresh");
    }
    setLoading(false);
  };

  // ─── Helpers ────────────────────────────────────────────

  function getOwnerLabel(team: Standing): string {
    if (team.is_cpu || team.owner_id === "cpu") return "CPU";
    if (team.owner_id === "placeholder") return "Unclaimed";
    if (team.owner_id === currentUserId) return "You";
    return "Joined";
  }

  function isMyTeam(team: Standing): boolean {
    return team.id === myTeamId || team.owner_id === currentUserId;
  }

  // ─── Loading ────────────────────────────────────────────

  if (loading) {
    return (
      <div className="min-h-screen bg-surface-900 flex items-center justify-center">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 border-2 border-gold-400 border-t-transparent rounded-full animate-spin" />
          <span className="text-surface-400">Loading standings...</span>
        </div>
      </div>
    );
  }

  if (error && !league) {
    return (
      <div className="min-h-screen bg-surface-900 flex items-center justify-center">
        <div className="text-center">
          <AlertTriangle className="w-12 h-12 text-surface-600 mx-auto mb-3" />
          <h2 className="text-xl font-semibold text-white mb-2">Standings unavailable</h2>
          <p className="text-surface-400 text-sm mb-4">{error}</p>
          <Link
            href={`/leagues/${leagueId}`}
            className="text-gold-400 hover:text-gold-300 text-sm font-medium"
          >
            Back to League
          </Link>
        </div>
      </div>
    );
  }

  const sortedStandings = [...standings].sort(
    (a, b) => b.wins - a.wins || a.losses - b.losses || b.points_for - a.points_for
  );

  return (
    <div className="min-h-screen bg-surface-900">
      {/* Back link */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-6">
        <Link
          href={`/leagues/${leagueId}`}
          className="inline-flex items-center gap-1 text-surface-400 hover:text-gold-400 transition-colors text-sm"
        >
          <ChevronRight className="w-4 h-4 rotate-180" />
          Back to {league?.name || "League"}
        </Link>
      </div>

      {/* Header */}
      <section className="relative overflow-hidden border-b border-surface-700">
        <div className="absolute inset-0 bg-gradient-to-b from-surface-850 via-surface-900 to-surface-900" />
        <div className="absolute top-0 right-0 w-[500px] h-[500px] bg-gold-400/5 rounded-full blur-3xl" />

        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 md:py-10">
          <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gold-400/10 border border-gold-400/20 flex items-center justify-center">
                <Trophy className="w-5 h-5 text-gold-400" />
              </div>
              <div>
                <h1 className="text-2xl md:text-3xl font-bold text-white tracking-tight">
                  Standings
                </h1>
                <p className="text-surface-400 text-sm">
                  {league?.name} &middot; {sortedStandings.length} teams
                </p>
              </div>
            </div>

            <div className="flex items-center gap-3">
              {/* Week selector */}
              <div className="relative">
                <select
                  value={selectedWeek}
                  onChange={(e) => setSelectedWeek(Number(e.target.value))}
                  className="appearance-none bg-surface-800 border border-surface-600 text-white rounded-lg pl-4 pr-10 py-2.5 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-gold-400/50 focus:border-gold-400/50 cursor-pointer"
                >
                  {Array.from({ length: maxWeek + 4 }, (_, i) => i + 1).map(
                    (wk) => (
                      <option key={wk} value={wk}>
                        Week {wk}
                      </option>
                    )
                  )}
                </select>
                <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-surface-400 pointer-events-none" />
              </div>

              <button
                onClick={handleRefresh}
                className="inline-flex items-center gap-1.5 border border-surface-600 hover:border-surface-500 text-surface-300 hover:text-white px-3 py-2.5 rounded-lg text-sm transition-all"
                title="Refresh standings"
              >
                <RefreshCw className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
      </section>

      {/* Calculate week scores (commissioner only) */}
      {isLeagueManager && (
        <section className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-6">
          <div className="bg-surface-850 border border-surface-700 rounded-2xl p-4 md:p-5">
            <div className="flex flex-col sm:flex-row sm:items-center gap-3">
              <div className="flex items-center gap-2 flex-1">
                <Calculator className="w-4 h-4 text-gold-400 shrink-0" />
                <span className="text-sm text-surface-300">
                  Commissioner Tool: Calculate scores for{" "}
                  <strong className="text-white">Week {selectedWeek}</strong>
                </span>
              </div>
              <button
                onClick={handleCalculate}
                disabled={calculating}
                className="inline-flex items-center justify-center gap-2 bg-gold-400 hover:bg-gold-300 text-surface-900 px-5 py-2.5 rounded-xl font-bold text-sm transition-all hover:shadow-xl hover:shadow-gold-400/30 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {calculating ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Calculating...
                  </>
                ) : (
                  <>
                    <Award className="w-4 h-4" />
                    Calculate Week {selectedWeek} Scores
                  </>
                )}
              </button>
            </div>
            {calcMessage && (
              <div
                className={`mt-3 text-sm px-3 py-2 rounded-lg ${
                  calcMessage.startsWith("Error")
                    ? "bg-red-500/10 text-red-400 border border-red-500/20"
                    : calcMessage.startsWith("Week")
                    ? "bg-green-500/10 text-green-400 border border-green-500/20"
                    : "bg-surface-800 text-surface-300 border border-surface-700"
                }`}
              >
                {calcMessage}
              </div>
            )}
          </div>
        </section>
      )}

      {/* Main content: Standings + Weekly matchups */}
      <section className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {sortedStandings.length > 0 ? (
          <div className="grid grid-cols-1 xl:grid-cols-5 gap-8">
            {/* Standings Table */}
            <div className="xl:col-span-3">
              <div className="overflow-x-auto rounded-xl border border-surface-700">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-surface-800 border-b border-surface-700">
                      <th className="text-left px-4 py-3.5 text-surface-400 font-medium text-xs uppercase tracking-wider w-12">
                        Rank
                      </th>
                      <th className="text-left px-4 py-3.5 text-surface-400 font-medium text-xs uppercase tracking-wider">
                        Team
                      </th>
                      <th className="text-center px-3 py-3.5 text-surface-400 font-medium text-xs uppercase tracking-wider w-10">
                        W
                      </th>
                      <th className="text-center px-3 py-3.5 text-surface-400 font-medium text-xs uppercase tracking-wider w-10">
                        L
                      </th>
                      <th className="text-center px-3 py-3.5 text-surface-400 font-medium text-xs uppercase tracking-wider w-10">
                        T
                      </th>
                      <th className="text-right px-4 py-3.5 text-surface-400 font-medium text-xs uppercase tracking-wider">
                        Pts For
                      </th>
                      <th className="text-right px-4 py-3.5 text-surface-400 font-medium text-xs uppercase tracking-wider">
                        Pts Against
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-surface-700">
                    {sortedStandings.map((team, idx) => {
                      const rank = idx + 1;
                      const myTeam = isMyTeam(team);
                      const ownerLabel = getOwnerLabel(team);
                      const avatar = getAvatarStyle(team.avatar_url);

                      return (
                        <tr
                          key={team.id}
                          className={`transition-colors ${
                            myTeam
                              ? "bg-gold-400/5 border-l-2 border-l-gold-400"
                              : rank === 1
                              ? "bg-gold-400/3"
                              : "bg-surface-900 hover:bg-surface-800/80"
                          }`}
                        >
                          <td className="px-4 py-4">
                            <RankBadge rank={rank} />
                          </td>
                          <td className="px-4 py-4">
                            <div className="flex items-center gap-3">
                              <div
                                className="w-9 h-9 rounded-full flex items-center justify-center text-base shrink-0 border border-white/10"
                                style={{ backgroundColor: avatar.bg }}
                              >
                                {avatar.icon}
                              </div>
                              <div className="min-w-0">
                                <div className="flex items-center gap-2">
                                  <span className="font-semibold text-white truncate max-w-[180px]">
                                    {team.name}
                                  </span>
                                  {myTeam && (
                                    <span className="text-[10px] text-gold-400 font-semibold uppercase tracking-wider bg-gold-400/10 px-1.5 py-0.5 rounded shrink-0">
                                      Your Team
                                    </span>
                                  )}
                                </div>
                                <span
                                  className={`text-xs ${
                                    myTeam ? "text-gold-400/70" : "text-surface-500"
                                  }`}
                                >
                                  {ownerLabel}
                                </span>
                              </div>
                            </div>
                          </td>
                          <td className="px-3 py-4 text-center">
                            <span className="text-white font-bold font-mono tabular-nums text-base">
                              {team.wins}
                            </span>
                          </td>
                          <td className="px-3 py-4 text-center">
                            <span className="text-white font-bold font-mono tabular-nums text-base">
                              {team.losses}
                            </span>
                          </td>
                          <td className="px-3 py-4 text-center text-surface-400 font-mono tabular-nums">
                            {team.ties}
                          </td>
                          <td className="px-4 py-4 text-right text-white font-bold font-mono tabular-nums">
                            {team.points_for?.toFixed(1) || "0.0"}
                          </td>
                          <td className="px-4 py-4 text-right text-surface-400 font-mono tabular-nums">
                            {team.points_against?.toFixed(1) || "0.0"}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Weekly Matchups */}
            <div className="xl:col-span-2">
              <div className="bg-surface-800 border border-surface-700 rounded-xl overflow-hidden">
                <div className="px-5 py-4 border-b border-surface-700">
                  <div className="flex items-center gap-2">
                    <Users className="w-4 h-4 text-gold-400" />
                    <h2 className="text-sm font-bold text-white">
                      Week {selectedWeek} Matchups
                    </h2>
                  </div>
                  <p className="text-surface-500 text-xs mt-1">
                    {weeklyData?.matchups?.length || 0} matchup
                    {(weeklyData?.matchups?.length || 0) !== 1 ? "es" : ""} this week
                  </p>
                </div>

                {weeklyData && weeklyData.matchups && weeklyData.matchups.length > 0 ? (
                  <div className="divide-y divide-surface-700">
                    {weeklyData.matchups.map((m, i) => (
                      <div
                        key={i}
                        className="px-5 py-4 hover:bg-surface-750 transition-colors"
                      >
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-2 min-w-0 flex-1">
                            <span
                              className={`text-sm font-medium truncate max-w-[130px] ${
                                m.home_team_id === myTeamId
                                  ? "text-gold-400"
                                  : "text-white"
                              }`}
                            >
                              {m.home_team}
                            </span>
                            <span className="text-gold-400 font-bold font-mono text-lg tabular-nums shrink-0">
                              {m.home_score?.toFixed(1) || "0.0"}
                            </span>
                          </div>
                        </div>
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2 min-w-0 flex-1">
                            <span
                              className={`text-sm font-medium truncate max-w-[130px] ${
                                m.away_team_id === myTeamId
                                  ? "text-gold-400"
                                  : "text-surface-300"
                              }`}
                            >
                              @ {m.away_team}
                            </span>
                            <span className="text-gold-400 font-bold font-mono text-lg tabular-nums shrink-0">
                              {m.away_score?.toFixed(1) || "0.0"}
                            </span>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="px-5 py-10 text-center">
                    <AlertTriangle className="w-8 h-8 text-surface-600 mx-auto mb-2" />
                    <p className="text-surface-500 text-sm">
                      {isLeagueManager
                        ? `No scores for Week ${selectedWeek} yet. Use the "Calculate Week ${selectedWeek} Scores" button above.`
                        : `No matchups available for Week ${selectedWeek}.`}
                    </p>
                  </div>
                )}
              </div>
            </div>
          </div>
        ) : (
          <div className="bg-surface-800 border border-surface-700 rounded-xl p-12 text-center">
            <Trophy className="w-12 h-12 text-surface-600 mx-auto mb-3" />
            <h3 className="text-white font-semibold mb-1">No standings data</h3>
            <p className="text-surface-400 text-sm">
              {isLeagueManager
                ? "Calculate scores for a week to generate standings."
                : "Standings will appear once scores are calculated."}
            </p>
          </div>
        )}
      </section>
    </div>
  );
}
