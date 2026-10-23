"use client";

import { useCallback, useEffect, useState } from "react";
import { dashboardApi, nflApi, standingsApi, teamsApi } from "@/lib/api-client";
import {
  deriveGuillotine,
  finaleWeekRange,
  type GGame,
  type GMatchup,
  type GScore,
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
  matchups?: GMatchup[];
}
interface NflScores {
  week?: number;
  year?: number;
  games?: GGame[];
}

export interface GuillotineData {
  state: GuillotineState;
  /** Last finale week with a played matchup, for the champion banner. */
  finaleWeeks: number[];
  live: boolean;
}

/** Everything the skin needs, from endpoints the page already uses. */
export function useGuillotineData(leagueId: string, enabled: boolean, seasonPoints: Map<string, number>) {
  const [data, setData] = useState<GuillotineData | null>(null);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    const [nfl, rawTeams] = await Promise.all([nflApi.getCurrentWeek(), teamsApi.getByLeague(leagueId) as Promise<RawTeam[]>]);
    const seasonOver = nfl.season_type === "post" || nfl.season_type === "off";
    const week = seasonOver ? LAST_REGULAR_WEEK : Math.min(nfl.week, LAST_REGULAR_WEEK);
    const year = nfl.season;
    const teams: GTeam[] = rawTeams.map((t) => ({
      id: t.id,
      name: t.name,
      avatar_url: t.avatar_url ?? null,
      eliminated_week: t.eliminated_week ?? null,
      created_at: t.created_at,
      points_for: seasonPoints.get(t.id) ?? 0,
    }));
    const weekly = (w: number) =>
      (standingsApi.getWeeklyScores(leagueId, w, year) as Promise<Weekly>).catch(() => null);

    const alive = teams.filter((t) => t.eliminated_week == null).length;
    const finale = alive === 2 && teams.length > 2;
    const finaleRange = finale ? finaleWeekRange(teams, seasonOver ? LAST_REGULAR_WEEK : week - 1) : [];

    const [cur, prev, nflScores, ...finaleData] = await Promise.all([
      seasonOver ? Promise.resolve(null) : weekly(week),
      week > 1 && !finale ? weekly(week - 1) : Promise.resolve(null),
      (dashboardApi.getNflScores() as Promise<NflScores>).catch(() => null),
      ...finaleRange.map(weekly),
    ]);

    const games = nflScores && nflScores.week === week && nflScores.year === year ? nflScores.games ?? null : null;
    const finaleWeeks = finaleData.map((d) => d?.matchups ?? []);
    const state = deriveGuillotine({
      week,
      teams,
      scores: cur?.team_scores ?? [],
      prevScores: prev?.team_scores ?? [],
      games,
      finaleWeeks,
      seasonOver,
    });
    const played = finaleRange.filter((_, i) => finaleWeeks[i].length > 0);
    const live = !!games?.some((g) => g.status_state === "in");
    setData({ state, finaleWeeks: played, live });
    setError(false);
  }, [leagueId, seasonPoints]);

  useEffect(() => {
    if (!enabled) return;
    load().catch(() => setError(true));
  }, [enabled, load]);

  return { data, error, reload: load };
}
