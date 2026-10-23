import type { GSummary } from "./guillotine";

/**
 * What the standings page shows, as one value: the rows, the Guillotine
 * summary, when they loaded, and whether the last reload failed. A failed
 * reload keeps the previous rows and load time, so the freshness chip
 * never reads "just now" over an empty table.
 */
export interface StandingsSnapshot<R> {
  rows: R[];
  guillotine: GSummary | null;
  /** Date.now() when the shown rows started loading; undefined before the first load. */
  at: number | undefined;
  refreshFailed: boolean;
}

export interface LoadedStandings<R> {
  rows: R[];
  guillotine: GSummary | null;
  at: number;
}

export const EMPTY_SNAPSHOT: StandingsSnapshot<never> = { rows: [], guillotine: null, at: undefined, refreshFailed: false };

/**
 * The next snapshot after a reload. `loaded` is null when the standings
 * fetch failed. `othersFailed` covers the rest of the reload (the week's
 * scores): new rows still show, but the load time stays put and the
 * reload counts as failed.
 */
export function applyStandingsLoad<R>(
  prev: StandingsSnapshot<R>,
  loaded: LoadedStandings<R> | null,
  othersFailed = false,
): StandingsSnapshot<R> {
  if (!loaded) return { ...prev, refreshFailed: true };
  if (othersFailed) return { ...prev, rows: loaded.rows, guillotine: loaded.guillotine, refreshFailed: true };
  return { rows: loaded.rows, guillotine: loaded.guillotine, at: loaded.at, refreshFailed: false };
}

export interface StandingsFetchApi {
  getTeams: (leagueId: string) => Promise<unknown>;
  getStandings: (leagueId: string) => Promise<unknown>;
}

export interface FetchedStandings<T, E> {
  teams: T[];
  entries: E[];
  guillotine: GSummary | null;
  at: number;
}

/**
 * Teams plus standings for one league. Rejects when either request fails
 * or the standings body has no rows array, instead of handing back an
 * empty table that looks like real data.
 */
export async function fetchStandings<T, E>(
  api: StandingsFetchApi,
  leagueId: string,
  now: () => number = Date.now,
): Promise<FetchedStandings<T, E>> {
  const at = now();
  const [teams, body] = await Promise.all([api.getTeams(leagueId), api.getStandings(leagueId)]);
  const entries = (body as { standings?: unknown } | null)?.standings;
  if (!Array.isArray(teams)) throw new Error("Teams response has no list");
  if (!Array.isArray(entries)) throw new Error("Standings response has no rows");
  const guillotine = (body as { guillotine?: GSummary | null }).guillotine ?? null;
  return { teams: teams as T[], entries: entries as E[], guillotine, at };
}
