/** Pure helpers for the league home page. */

export interface HomeSide {
  team_id: string;
  name: string;
  score: number | null;
  projected: number | null;
}

export interface Recap {
  week: number;
  result: "W" | "L" | "T";
  score: number;
  opponent_score: number;
  opponent_team_id: string;
  opponent_name: string;
  optimal_score: number | null;
  bench_points: number | null;
}

export interface HomeLeague {
  visibility: string;
  team_count: number;
  max_teams: number;
  league_type: string;
  scoring: string;
  draft_status: string;
}

/** Points worth calling out. Smaller gaps are noise. */
export const BENCH_THRESHOLD = 5;

const TYPE_LABELS: Record<string, string> = {
  standard: "Standard",
  two_man: "2-Man",
  conference: "Conference",
  guillotine: "Guillotine",
  dual_squad: "Dual-Squad",
};
const VISIBILITY_LABELS: Record<string, string> = { open: "Open", invite_only: "Invite only", private: "Private" };
const DRAFT_LABELS: Record<string, string> = { not_started: "Draft not started", in_progress: "Drafting now", completed: "Draft done" };

/** Setting chips under the league name. */
export function leagueChips(l: HomeLeague): string[] {
  const size = l.team_count < l.max_teams ? `${l.team_count} of ${l.max_teams} teams` : `${l.max_teams} teams`;
  return [
    VISIBILITY_LABELS[l.visibility] ?? l.visibility,
    size,
    TYPE_LABELS[l.league_type] ?? l.league_type,
    l.scoring,
    DRAFT_LABELS[l.draft_status] ?? l.draft_status,
  ];
}

/** Which version of the page to show. */
export function homeMode(draftStatus: string): "predraft" | "drafting" | "season" {
  if (draftStatus === "not_started") return "predraft";
  if (draftStatus === "in_progress") return "drafting";
  return "season";
}

/** The number each side leads with: the score once games start, else the projection. */
export function headline(side: HomeSide): number | null {
  return side.score ?? side.projected;
}

/** Share of the bar that belongs to "me", 0 to 1. Even split when there is nothing to compare. */
export function barShare(me: number | null, opp: number | null): number {
  const a = Math.max(0, me ?? 0);
  const b = Math.max(0, opp ?? 0);
  return a + b === 0 ? 0.5 : a / (a + b);
}

/** Rough win chance from two projections. Weekly team scores swing about 25 points. */
export function winChance(me: number | null, opp: number | null): number | null {
  if (me == null || opp == null) return null;
  const z = (me - opp) / (25 * Math.SQRT2);
  // Logistic approximation of the normal CDF.
  const p = 1 / (1 + Math.exp(-1.702 * z));
  return Math.round(p * 100);
}

/** Recap card text, or null when last week needs no comment. */
export function recapLine(r: Recap | null): string | null {
  if (!r) return null;
  const bench = r.bench_points ?? 0;
  if (r.result === "W" && bench < BENCH_THRESHOLD) return null;
  const verb = r.result === "W" ? "won" : r.result === "L" ? "lost" : "tied";
  const parts = [`You ${verb} ${r.score.toFixed(1)} to ${r.opponent_score.toFixed(1)}.`];
  if (bench >= BENCH_THRESHOLD && r.optimal_score != null) {
    parts.push(`${bench.toFixed(1)} points stayed on your bench.`);
    parts.push(`Your best lineup would have scored ${r.optimal_score.toFixed(1)}.`);
    if (r.result === "L" && r.optimal_score > r.opponent_score) parts.push("That lineup wins.");
  }
  return parts.join(" ");
}

export function recordLine(r: { wins: number; losses: number; ties: number }): string {
  return r.ties ? `${r.wins}-${r.losses}-${r.ties}` : `${r.wins}-${r.losses}`;
}

/** "QA Test League Team 4" reads as "Team 4" inside QA Test League. Custom names stay whole. */
export function shortTeamName(name: string, leagueName: string): string {
  const prefix = `${leagueName} `;
  return name.startsWith(prefix) && name.length > prefix.length ? name.slice(prefix.length) : name;
}
