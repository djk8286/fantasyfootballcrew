"use client";

import { useState, useEffect } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { standingsApi, leaguesApi } from "@/lib/api-client";
import { ChevronLeft, ChevronRight as ChevronRightIcon, Calendar, Swords } from "lucide-react";

// ─── Interfaces ───────────────────────────────────────────────

interface LeagueData {
  id: string;
  name: string;
}

interface ScheduleTeamEntry {
  id: string;
  name: string;
  score: number | null;
  projected_score: number | null;
  is_projected: boolean;
}

interface ScheduleMatchup {
  team_a: ScheduleTeamEntry;
  team_b: ScheduleTeamEntry;
}

interface ScheduleWeek {
  week: number;
  matchups: ScheduleMatchup[];
}

// A team's real per-player score breakdown for one week -- see
// standings/page.tsx's identical shape (both read the same
// /standings/weekly endpoint). Kept as a separate fetch from `schedule`
// above (a whole-season, team-totals-only overview) since per-player
// detail is only meaningful for the one week currently being viewed.
interface PlayerBreakdownEntry {
  name: string;
  score: number;
  position: string;
}
interface TeamWeeklyScore {
  team_id: string;
  lineup_data: { breakdown?: Record<string, PlayerBreakdownEntry> } | null;
}

const CURRENT_YEAR = new Date().getFullYear();

export default function SchedulePage() {
  const params = useParams();
  const leagueId = params.id as string;

  const [league, setLeague] = useState<LeagueData | null>(null);
  const [schedule, setSchedule] = useState<ScheduleWeek[]>([]);
  const [selectedWeek, setSelectedWeek] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  // Real per-player breakdown for the currently-viewed week only --
  // fetched separately (see TeamWeeklyScore above), null until it loads
  // or if this week has never been calculated (bye/future week).
  const [breakdownByTeam, setBreakdownByTeam] = useState<Map<string, Record<string, PlayerBreakdownEntry>>>(new Map());
  const [expandedMatchup, setExpandedMatchup] = useState<number | null>(null);

  useEffect(() => {
    Promise.all([
      leaguesApi.get(leagueId) as Promise<LeagueData>,
      standingsApi.getSchedule(leagueId, CURRENT_YEAR) as Promise<{ schedule: ScheduleWeek[] }>,
    ])
      .then(([l, s]) => {
        setLeague(l);
        setSchedule(s.schedule || []);
        // Land on the first week that isn't fully decided yet, if any.
        const upcoming = (s.schedule || []).find((wk) =>
          wk.matchups.some((m) => m.team_a.is_projected || m.team_b.is_projected),
        );
        setSelectedWeek(upcoming?.week ?? 1);
      })
      .catch(() => setError("Failed to load schedule"))
      .finally(() => setLoading(false));
  }, [leagueId]);

  // Real per-player scores for the selected week -- the season-wide
  // `schedule` fetch above only ever carries team totals/projections.
  useEffect(() => {
    if (!leagueId || !selectedWeek) return;
    setExpandedMatchup(null); // collapse on week change, same as before this existed
    standingsApi
      .getWeeklyScores(leagueId, selectedWeek, CURRENT_YEAR)
      .then((data) => {
        const teamScores = (data as { team_scores?: TeamWeeklyScore[] })?.team_scores || [];
        setBreakdownByTeam(new Map(
          teamScores
            .filter((ts) => ts.lineup_data?.breakdown)
            .map((ts) => [ts.team_id, ts.lineup_data!.breakdown as Record<string, PlayerBreakdownEntry>]),
        ));
      })
      .catch(() => setBreakdownByTeam(new Map()));
  }, [leagueId, selectedWeek]);

  if (loading) {
    return (
      <div className="min-h-screen bg-surface-900 flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-gold-400 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-surface-900 flex items-center justify-center">
        <p className="text-red-400">{error}</p>
      </div>
    );
  }

  const week = schedule.find((wk) => wk.week === selectedWeek);
  const maxWeek = schedule.length > 0 ? schedule[schedule.length - 1].week : 1;

  return (
    <div className="min-h-screen bg-surface-900">
      <div className="sticky top-0 z-40 bg-surface-900/95 backdrop-blur-md border-b border-surface-700">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-3 flex items-center gap-3">
          <Link href={`/leagues/${leagueId}`} className="text-surface-400 hover:text-white transition-colors">
            <ChevronLeft className="w-5 h-5" />
          </Link>
          <h1 className="text-lg font-semibold text-white">{league?.name} — Schedule</h1>
        </div>
      </div>

      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
        {/* Week selector */}
        <div className="flex items-center gap-2 overflow-x-auto pb-2">
          {schedule.map((wk) => (
            <button
              key={wk.week}
              onClick={() => setSelectedWeek(wk.week)}
              className={`shrink-0 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                wk.week === selectedWeek
                  ? "bg-gold-400 text-surface-900"
                  : "bg-surface-800 border border-surface-700 text-surface-400 hover:text-white"
              }`}
            >
              Week {wk.week}
            </button>
          ))}
        </div>

        {/* Matchups for the selected week */}
        <div className="bg-surface-800 border border-surface-700 rounded-2xl p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-white flex items-center gap-2">
              <Calendar className="w-4 h-4 text-gold-400" />
              Week {selectedWeek}
            </h2>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setSelectedWeek((w) => Math.max(1, w - 1))}
                disabled={selectedWeek <= 1}
                title="Previous week"
                aria-label="Previous week"
                className="p-1 rounded text-surface-500 hover:text-white disabled:opacity-30 transition-colors"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <button
                onClick={() => setSelectedWeek((w) => Math.min(maxWeek, w + 1))}
                disabled={selectedWeek >= maxWeek}
                title="Next week"
                aria-label="Next week"
                className="p-1 rounded text-surface-500 hover:text-white disabled:opacity-30 transition-colors"
              >
                <ChevronRightIcon className="w-4 h-4" />
              </button>
            </div>
          </div>

          {!week || week.matchups.length === 0 ? (
            <p className="text-surface-500 text-sm">No matchups for this week.</p>
          ) : (
            <div className="space-y-3">
              {week.matchups.map((m, i) => {
                const decided = !m.team_a.is_projected && !m.team_b.is_projected;
                const aWins = decided && (m.team_a.score ?? 0) > (m.team_b.score ?? 0);
                const bWins = decided && (m.team_b.score ?? 0) > (m.team_a.score ?? 0);
                const aBreakdown = breakdownByTeam.get(m.team_a.id);
                const bBreakdown = breakdownByTeam.get(m.team_b.id);
                const hasBreakdown = !!(aBreakdown || bBreakdown);
                const isExpanded = expandedMatchup === i;
                return (
                  <div key={i} className="border border-surface-700 rounded-xl p-4">
                    <div className="flex items-center justify-between gap-3">
                      <Link
                        href={`/leagues/${leagueId}/teams/${m.team_a.id}`}
                        className={`flex-1 min-w-0 text-sm font-medium truncate transition-colors ${
                          aWins ? "text-green-400" : "text-white hover:text-gold-400"
                        }`}
                      >
                        {m.team_a.name}
                      </Link>
                      <span className={`text-lg font-bold shrink-0 ${aWins ? "text-green-400" : "text-white"}`}>
                        {m.team_a.score ?? m.team_a.projected_score ?? "—"}
                      </span>
                      <Swords className="w-3.5 h-3.5 text-surface-600 shrink-0" />
                      <span className={`text-lg font-bold shrink-0 ${bWins ? "text-green-400" : "text-white"}`}>
                        {m.team_b.score ?? m.team_b.projected_score ?? "—"}
                      </span>
                      <Link
                        href={`/leagues/${leagueId}/teams/${m.team_b.id}`}
                        className={`flex-1 min-w-0 text-sm font-medium truncate text-right transition-colors ${
                          bWins ? "text-green-400" : "text-white hover:text-gold-400"
                        }`}
                      >
                        {m.team_b.name}
                      </Link>
                    </div>
                    {(m.team_a.is_projected || m.team_b.is_projected) && (
                      <p className="text-[10px] text-surface-600 uppercase tracking-wider text-center mt-2">
                        Projected — based on season average so far
                      </p>
                    )}
                    {/* Per-player scores alongside the team totals above
                        -- real current scores (calculate_week runs on
                        every stats sync, so this reflects a game the
                        moment it's final, not just once the whole
                        week's slate wraps up), not just team totals. */}
                    {hasBreakdown && (
                      <>
                        <button
                          onClick={() => setExpandedMatchup(isExpanded ? null : i)}
                          className="mt-2 text-[11px] text-surface-500 hover:text-gold-400 transition-colors font-medium block mx-auto"
                        >
                          {isExpanded ? "▾ Hide player scores" : "▸ Show player scores"}
                        </button>
                        {isExpanded && (
                          <div className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                            {[
                              { label: m.team_a.name, breakdown: aBreakdown },
                              { label: m.team_b.name, breakdown: bBreakdown },
                            ].map(({ label, breakdown }) => (
                              <div key={label} className="bg-surface-900/50 rounded-lg p-2.5">
                                <p className="text-surface-500 font-semibold uppercase tracking-wider text-[10px] mb-1.5 truncate">
                                  {label}
                                </p>
                                {breakdown ? (
                                  <ul className="space-y-1">
                                    {Object.entries(breakdown)
                                      .sort(([, a], [, b]) => b.score - a.score)
                                      .map(([pid, p]) => (
                                        <li key={pid} className="flex items-center justify-between gap-2">
                                          <span className="text-surface-300 truncate">
                                            <span className="text-surface-500">{p.position}</span> {p.name}
                                          </span>
                                          <span className="text-white font-mono tabular-nums shrink-0">
                                            {p.score.toFixed(1)}
                                          </span>
                                        </li>
                                      ))}
                                  </ul>
                                ) : (
                                  <p className="text-surface-600 italic">No breakdown yet</p>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                      </>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
