/** Pure helpers for the team page: roster grouping, the schedule list and header text. */

export const ROSTER_GROUPS = ["QB", "RB", "WR", "TE", "K", "DEF", "DL", "LB", "DB"] as const;

export interface RosterRow {
  id: string;
  position: string;
  slot: string;
}

/** Players grouped by position in roster order. Starters lead each group. Unknown positions go last. */
export function groupRoster<T extends RosterRow>(rows: readonly T[]): { position: string; players: T[] }[] {
  const order = (pos: string) => {
    const i = (ROSTER_GROUPS as readonly string[]).indexOf(pos);
    return i === -1 ? ROSTER_GROUPS.length : i;
  };
  const groups = new Map<string, T[]>();
  for (const r of rows) groups.set(r.position, [...(groups.get(r.position) ?? []), r]);
  return [...groups.entries()]
    .sort(([a], [b]) => order(a) - order(b) || a.localeCompare(b))
    .map(([position, players]) => ({
      position,
      players: [...players].sort((a, b) => Number(a.slot === "BN") - Number(b.slot === "BN")),
    }));
}

export interface ScheduleSide {
  id: string;
  name: string;
  score: number | null;
}

export interface ScheduleWeek {
  week: number;
  status?: "upcoming" | "live" | "final" | "unknown";
  matchups: { team_a: ScheduleSide; team_b: ScheduleSide }[];
}

export interface ScheduleRow {
  week: number;
  opponent: ScheduleSide | null;
  me: number | null;
  them: number | null;
  status: "upcoming" | "live" | "final";
  result: "W" | "L" | "T" | null;
  next: boolean;
}

/** One row per week from the league's first week. No pairing = bye.
 * Only final weeks get a W, L or T. The first upcoming week is "next". */
export function scheduleRows(weeks: readonly ScheduleWeek[], teamId: string): ScheduleRow[] {
  let nextSet = false;
  return weeks.map((w) => {
    const m = w.matchups.find((x) => x.team_a.id === teamId || x.team_b.id === teamId);
    const mine = m ? (m.team_a.id === teamId ? m.team_a : m.team_b) : null;
    const opp = m ? (m.team_a.id === teamId ? m.team_b : m.team_a) : null;
    const status = w.status === "final" || w.status === "live" ? w.status : w.status === "upcoming" ? "upcoming" : mine?.score != null ? "final" : "upcoming";
    const me = mine?.score ?? null;
    const them = opp?.score ?? null;
    const result = status === "final" && me !== null && them !== null ? (me > them ? "W" : me < them ? "L" : "T") : null;
    const next = status === "upcoming" && !nextSet && !!opp;
    if (next) nextSet = true;
    return { week: w.week, opponent: opp, me, them, status, result, next };
  });
}

export function ordinal(n: number): string {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return `${n}${s[(v - 20) % 10] || s[v] || s[0]}`;
}

export function recordText(r: { wins: number; losses: number; ties: number }): string {
  return `${r.wins}-${r.losses}${r.ties ? `-${r.ties}` : ""}`;
}

/** "Weeks 1 to 5 came before the draft." or null when the league started in Week 1. */
export function preDraftNote(startWeek: number): string | null {
  if (startWeek <= 1) return null;
  return startWeek === 2 ? "Week 1 came before the draft." : `Weeks 1 to ${startWeek - 1} came before the draft.`;
}
