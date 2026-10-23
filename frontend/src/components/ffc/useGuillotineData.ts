"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { dashboardApi, nflApi, standingsApi, teamsApi } from "@/lib/api-client";
import {
  deriveGuillotine,
  type GGame,
  type GScore,
  type GSummary,
  type GTeam,
  type GuillotineState,
} from "@/lib/guillotine";

/** Last NFL regular-season week; the scheduler scores weeks 1..18. */
export const LAST_REGULAR_WEEK = 18;

interface RawTeam {
  id: string;
  name: string;
  avatar_url?: string | null;
  eliminated_week?: number | null;
  created_at: string;
}
interface Weekly {
  team_scores?: GScore[];
}
interface NflScores {
  week?: number;
  year?: number;
  games?: GGame[];
}

export interface GuillotineData {
  state: GuillotineState;
  live: boolean;
}

/** The calls the loader makes, so tests can swap in fakes. */
export interface GuillotineApi {
  getCurrentWeek: () => Promise<{ season: number; week: number; season_type: string }>;
  getTeams: (leagueId: string) => Promise<RawTeam[]>;
  getWeeklyScores: (leagueId: string, week: number, year: number) => Promise<Weekly>;
  getNflScores: () => Promise<NflScores>;
}

const liveApi: GuillotineApi = {
  getCurrentWeek: () => nflApi.getCurrentWeek(),
  getTeams: (id) => teamsApi.getByLeague(id) as Promise<RawTeam[]>,
  getWeeklyScores: (id, week, year) => standingsApi.getWeeklyScores(id, week, year) as Promise<Weekly>,
  getNflScores: () => dashboardApi.getNflScores() as Promise<NflScores>,
};

/**
 * Everything the skin needs. Any required fetch that fails rejects the
 * whole load, so the page shows an error instead of a cut line, a team
 * on the block or a champion built from partial data. Only the NFL game
 * list is optional; without it the phase falls back to scores.
 */
export async function loadGuillotineData(
  api: GuillotineApi,
  leagueId: string,
  seasonPoints: Map<string, number>,
  summary: GSummary | null,
): Promise<GuillotineData> {
  if (!summary) throw new Error("standings did not include the Guillotine summary");
  const [nfl, rawTeams] = await Promise.all([api.getCurrentWeek(), api.getTeams(leagueId)]);
  const decided = summary.champion_team_id != null;
  const seasonType = nfl.season_type;
  // "post" and "off" follow the regular season, so week 18 is the last
  // one that matters. "pre" comes before week 1 of a new season.
  const week = decided || seasonType === "post" || seasonType === "off"
    ? LAST_REGULAR_WEEK
    : seasonType === "pre"
      ? 1
      : Math.max(1, Math.min(nfl.week, LAST_REGULAR_WEEK));
  const year = nfl.season;
  const teams: GTeam[] = rawTeams.map((t) => ({
    id: t.id,
    name: t.name,
    avatar_url: t.avatar_url ?? null,
    eliminated_week: t.eliminated_week ?? null,
    created_at: t.created_at,
    points_for: seasonPoints.get(t.id) ?? 0,
  }));
  const alive = teams.filter((t) => t.eliminated_week == null).length;
  const finale = alive === 2 && teams.length > 2;
  const weekly = (w: number) => api.getWeeklyScores(leagueId, w, year);

  const [cur, prev, nflScores] = await Promise.all([
    decided ? Promise.resolve(null) : weekly(week),
    week > 1 && !finale && !decided ? weekly(week - 1) : Promise.resolve(null),
    api.getNflScores().catch(() => null),
  ]);

  const games = nflScores && nflScores.week === week && nflScores.year === year ? nflScores.games ?? null : null;
  const state = deriveGuillotine({
    week,
    teams,
    scores: cur?.team_scores ?? [],
    prevScores: prev?.team_scores ?? [],
    games,
    summary,
  });
  const live = !decided && !!games?.some((g) => g.status_state === "in");
  return { state, live };
}

/** Loads the skin for a Guillotine league. On any failure data is null
 * and error is true. Results from a superseded load are dropped. */
export function useGuillotineData(
  leagueId: string,
  enabled: boolean,
  seasonPoints: Map<string, number>,
  summary: GSummary | null,
  api: GuillotineApi = liveApi,
) {
  const [data, setData] = useState<GuillotineData | null>(null);
  const [error, setError] = useState(false);
  const seq = useRef(0);

  const reload = useCallback(async () => {
    const mine = ++seq.current;
    try {
      const next = await loadGuillotineData(api, leagueId, seasonPoints, summary);
      if (mine !== seq.current) return;
      setData(next);
      setError(false);
    } catch {
      if (mine !== seq.current) return;
      setData(null);
      setError(true);
    }
  }, [api, leagueId, seasonPoints, summary]);

  useEffect(() => {
    if (!enabled) return;
    void reload();
  }, [enabled, reload]);

  return { data, error, reload };
}
