/**
 * One source of truth for "which NFL week is it" on the frontend.
 *
 * The backend's /nfl/current-week (Sleeper's live state, also what
 * scoring and the AI prompt use) is the authority; this module caches one
 * in-flight/settled request per page load so every component that asks
 * (header, lineup, team, player, AI pages) gets the same answer, and
 * holds the rules for turning it plus a ?week= URL param into the week a
 * page shows.
 */

export interface NflState {
  season: number;
  week: number;
  season_type?: string;
}

export const MIN_WEEK = 1;
export const MAX_WEEK = 18;

export function clampWeek(week: number): number {
  return Math.min(MAX_WEEK, Math.max(MIN_WEEK, Math.trunc(week)));
}

/** A ?week= value as a week number, or null when absent or not 1-18. */
export function parseWeekParam(value: string | null | undefined): number | null {
  if (value == null || !/^\d{1,2}$/.test(value.trim())) return null;
  const n = Number(value.trim());
  return n >= MIN_WEEK && n <= MAX_WEEK ? n : null;
}

/**
 * The week a lineup-style page should open on: the ?week= param when it's
 * valid, else week 1 for a league that hasn't drafted, else the live NFL
 * week (week 1 if that couldn't be fetched).
 */
export function initialWeek(opts: { param: string | null | undefined; state: NflState | null; draftComplete: boolean }): number {
  const fromUrl = parseWeekParam(opts.param);
  if (fromUrl !== null) return fromUrl;
  if (!opts.draftComplete) return 1;
  return opts.state?.week ? clampWeek(opts.state.week) : 1;
}

/** The current URL's search string with week set (other params kept). */
export function withWeekParam(search: string, week: number): string {
  const params = new URLSearchParams(search);
  params.set("week", String(week));
  return `?${params.toString()}`;
}

let cached: { at: number; promise: Promise<NflState | null> } | null = null;
const TTL_MS = 60_000;

/**
 * The live NFL state, fetched at most once a minute and shared by every
 * caller. Resolves null (never rejects) when the request fails, and a
 * failure isn't cached.
 */
export function getCurrentNflState(fetcher: () => Promise<NflState>, now: number = Date.now()): Promise<NflState | null> {
  if (cached && now - cached.at < TTL_MS) return cached.promise;
  const promise = fetcher().catch(() => {
    if (cached?.promise === promise) cached = null;
    return null;
  });
  cached = { at: now, promise };
  return promise;
}

export function resetCurrentNflStateCache(): void {
  cached = null;
}
