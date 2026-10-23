// Guillotine standings state, derived from data the API already returns.
// Mirrors backend guillotine_service.process_league_guillotine: the lowest
// weekly score is cut, ties go to fewer season points, then the
// earliest-created team. Cuts stop at 2 alive teams.

export type GuillotinePhase = "prekickoff" | "live" | "pending" | "finale" | "champion";
export type CutLineVariant = "neutral" | "preview" | "live" | "pending" | null;

export interface GTeam {
  id: string;
  name: string;
  avatar_url?: string | null;
  eliminated_week: number | null;
  created_at: string;
  points_for: number;
  meta?: string | null;
}

export interface GScore {
  team_id: string;
  total_score: number;
  projected_score: number | null;
}

export interface GGame {
  status_state?: string | null;
  completed: boolean;
}

export interface GMatchup {
  home_team_id: string;
  home_score: number;
  away_team_id: string;
  away_score: number;
}

export interface AliveRow {
  team: GTeam;
  rank: number;
  score: number | null;
  projected: number | null;
  clearBy: number | null;
  onBlock: boolean;
}

export interface OutRow {
  team: GTeam;
  place: number;
  cutWeek: number;
}

export interface SeriesRecord {
  wins: number;
  losses: number;
  ties: number;
  points: number;
}

export interface Finalist {
  team: GTeam;
  score: number | null;
  projected: number | null;
  series: SeriesRecord;
  leading: boolean;
}

export interface FinaleState {
  week: number;
  finalists: [Finalist, Finalist];
  seriesPlayed: number;
  seriesTied: boolean;
  /** "Crew Destroyers leads the series 3–1 · +26.5 finale pts" */
  leadLine: string;
  /** Phone variant without the points tail. */
  leadLineShort: string;
  /** "SERIES TIED 2–2" when the series is level after at least one week. */
  tiedLabel: string | null;
  /** Tooltip on the SERIES TIED tag. */
  tiedTip: string | null;
}

export interface GuillotineState {
  phase: GuillotinePhase;
  /** Week the table is about: the live week, or the week waiting on its cut. */
  week: number;
  totalTeams: number;
  aliveCount: number;
  noCutsYet: boolean;
  cutLine: CutLineVariant;
  alive: AliveRow[];
  out: OutRow[];
  block: { team: GTeam; score: number; behindBy: number | null; behindName: string | null } | null;
  finale: FinaleState | null;
}

export interface GuillotineInput {
  week: number;
  teams: GTeam[];
  scores: GScore[];
  /** This week's NFL games, or null when they couldn't be loaded. */
  games: GGame[] | null;
  /** Last week's scores, to catch a cut the rollover held back. */
  prevScores?: GScore[];
  /** Finale weeks already played, oldest first. */
  finaleWeeks?: GMatchup[][];
  /** The regular season has rolled over: the finale is decided. */
  seasonOver?: boolean;
}

const round1 = (n: number) => Math.round(n * 10) / 10;
export const fmt1 = (n: number) => round1(n).toFixed(1);
const DASH = "\u2013";

export function gameStarted(g: GGame): boolean {
  return g.completed || g.status_state === "in" || g.status_state === "post";
}

/** Postponed or canceled games come back "post" without completing. */
function offSchedule(g: GGame): boolean {
  return !g.completed && g.status_state != null && g.status_state !== "pre" && g.status_state !== "in";
}

export function ordinal(n: number): string {
  const mod100 = n % 100;
  if (mod100 >= 11 && mod100 <= 13) return `${n}th`;
  return `${n}${{ 1: "st", 2: "nd", 3: "rd" }[n % 10] ?? "th"}`;
}

/** Highest first. Ties put the team the backend would cut lower: fewer
 * season points, then the earlier-created team. */
export function compareLive(a: { score: number; team: GTeam }, b: { score: number; team: GTeam }): number {
  return (
    b.score - a.score ||
    b.team.points_for - a.team.points_for ||
    Date.parse(b.team.created_at) - Date.parse(a.team.created_at)
  );
}

export function finaleSeries(aId: string, bId: string, weeks: GMatchup[][]): { a: SeriesRecord; b: SeriesRecord; played: number } {
  const a: SeriesRecord = { wins: 0, losses: 0, ties: 0, points: 0 };
  const b: SeriesRecord = { wins: 0, losses: 0, ties: 0, points: 0 };
  let played = 0;
  for (const matchups of weeks) {
    const m = matchups.find(
      (x) => (x.home_team_id === aId && x.away_team_id === bId) || (x.home_team_id === bId && x.away_team_id === aId),
    );
    if (!m) continue;
    played += 1;
    const aPts = m.home_team_id === aId ? m.home_score : m.away_score;
    const bPts = m.home_team_id === aId ? m.away_score : m.home_score;
    a.points += aPts;
    b.points += bPts;
    if (aPts > bPts) { a.wins += 1; b.losses += 1; }
    else if (bPts > aPts) { b.wins += 1; a.losses += 1; }
    else { a.ties += 1; b.ties += 1; }
  }
  a.points = round1(a.points);
  b.points = round1(b.points);
  return { a, b, played };
}

export function seriesText(r: SeriesRecord): string {
  return r.ties ? `${r.wins}${DASH}${r.losses}${DASH}${r.ties}` : `${r.wins}${DASH}${r.losses}`;
}

/** Better W-L first, then more finale points. Season points keep the
 * order stable before the first finale week is played. */
function seriesOrder(x: Finalist, y: Finalist): number {
  return (
    y.series.wins - y.series.losses - (x.series.wins - x.series.losses) ||
    y.series.points - x.series.points ||
    y.team.points_for - x.team.points_for
  );
}

function buildFinale(week: number, alive: GTeam[], byId: Map<string, GScore>, weeks: GMatchup[][], started: boolean): FinaleState {
  const [t1, t2] = alive;
  const { a, b, played } = finaleSeries(t1.id, t2.id, weeks);
  const mk = (team: GTeam, series: SeriesRecord): Finalist => ({
    team,
    score: started ? byId.get(team.id)?.total_score ?? 0 : null,
    projected: byId.get(team.id)?.projected_score ?? null,
    series,
    leading: false,
  });
  const [f1, f2] = [mk(t1, a), mk(t2, b)].sort(seriesOrder);

  const seriesLevel = f1.series.wins - f1.series.losses === f2.series.wins - f2.series.losses;
  const pointsGap = round1(f1.series.points - f2.series.points);
  let leadLine: string;
  let leadLineShort: string;
  let tiedLabel: string | null = null;
  let tiedTip: string | null = null;

  if (played > 0 && !seriesLevel) {
    f1.leading = true;
    leadLineShort = `${f1.team.name} leads the series ${seriesText(f1.series)}`;
    leadLine = `${leadLineShort} · ${pointsGap >= 0 ? "+" : "-"}${fmt1(Math.abs(pointsGap))} finale pts`;
  } else if (played > 0) {
    tiedLabel = `SERIES TIED ${seriesText(f1.series)}`;
    if (pointsGap > 0) {
      leadLine = `${f1.team.name} ahead on finale points by ${fmt1(pointsGap)} (tie-break)`;
      leadLineShort = `${f1.team.name} ahead on finale pts by ${fmt1(pointsGap)}`;
      tiedTip = `Series tied · tie-break: finale points · ${f1.team.name} +${fmt1(pointsGap)}`;
    } else {
      leadLine = leadLineShort = "Series and finale points level";
      tiedTip = "Series tied · finale points even";
    }
  } else if (started) {
    const gap = round1((f1.score ?? 0) - (f2.score ?? 0));
    const ahead = gap >= 0 ? f1 : f2;
    leadLine = leadLineShort = gap === 0 ? `Tied at ${fmt1(f1.score ?? 0)}` : `${ahead.team.name} leads by ${fmt1(Math.abs(gap))}`;
  } else {
    leadLine = leadLineShort = "First finale week. The series starts when games do.";
  }

  return { week, finalists: [f1, f2], seriesPlayed: played, seriesTied: tiedLabel != null, leadLine, leadLineShort, tiedLabel, tiedTip };
}

export function deriveGuillotine(input: GuillotineInput): GuillotineState {
  const { teams } = input;
  const aliveTeams = teams.filter((t) => t.eliminated_week == null);
  const cutTeams = teams.filter((t) => t.eliminated_week != null);
  const lastCut = cutTeams.reduce((m, t) => Math.max(m, t.eliminated_week ?? 0), 0);

  const games = input.games;
  const counted = games?.filter((g) => !offSchedule(g)) ?? [];
  const anyStarted = games ? games.some(gameStarted) : input.scores.some((s) => s.total_score > 0);
  const allFinal = counted.length > 0 && counted.every((g) => g.completed);

  let week = input.week;
  let scores = input.scores;
  let phase: GuillotinePhase;

  const prev = input.prevScores ?? [];
  const prevHeld =
    !anyStarted &&
    week > 1 &&
    lastCut < week - 1 &&
    prev.length > 0 &&
    aliveTeams.some((t) => prev.some((s) => s.team_id === t.id));

  if (aliveTeams.length <= 2 && teams.length > 2) {
    phase = input.seasonOver && aliveTeams.length === 2 ? "champion" : "finale";
  } else if (allFinal && lastCut < week) {
    phase = "pending";
  } else if (prevHeld) {
    phase = "pending";
    week -= 1;
    scores = prev;
  } else if (anyStarted) {
    phase = "live";
  } else {
    phase = "prekickoff";
  }

  const byId = new Map(scores.map((s) => [s.team_id, s]));
  const out: OutRow[] = [...cutTeams]
    .sort((a, b) => (b.eliminated_week ?? 0) - (a.eliminated_week ?? 0) || compareLive(
      { score: 0, team: a }, { score: 0, team: b }))
    .map((team, i) => ({ team, cutWeek: team.eliminated_week ?? 0, place: aliveTeams.length + i + 1 }));

  const base = {
    week,
    totalTeams: teams.length,
    aliveCount: aliveTeams.length,
    noCutsYet: cutTeams.length === 0,
    out,
  };

  if (phase === "finale" || phase === "champion") {
    return {
      ...base,
      phase,
      cutLine: null,
      alive: [],
      block: null,
      finale: aliveTeams.length === 2
        ? buildFinale(week, aliveTeams, byId, input.finaleWeeks ?? [], phase === "finale" && anyStarted)
        : null,
    };
  }

  const scored = aliveTeams.map((team) => ({
    team,
    score: byId.get(team.id)?.total_score ?? 0,
    projected: byId.get(team.id)?.projected_score ?? null,
  }));

  let alive: AliveRow[];
  let block: GuillotineState["block"] = null;
  if (phase === "prekickoff") {
    scored.sort((a, b) => (b.projected ?? -1) - (a.projected ?? -1) || b.team.points_for - a.team.points_for);
    alive = scored.map((r, i) => ({ ...r, score: null, rank: i + 1, clearBy: null, onBlock: false }));
  } else {
    scored.sort(compareLive);
    const low = scored[scored.length - 1];
    alive = scored.map((r, i) => ({
      ...r,
      rank: i + 1,
      onBlock: r === low,
      clearBy: r === low ? null : round1(r.score - low.score),
    }));
    if (low) {
      const above = scored[scored.length - 2];
      block = {
        team: low.team,
        score: low.score,
        behindBy: above ? round1(above.score - low.score) : null,
        behindName: above?.team.name ?? null,
      };
    }
  }

  const cutLine: CutLineVariant =
    phase === "prekickoff" ? "neutral" : phase === "pending" ? "pending" : base.noCutsYet ? "preview" : "live";

  return { ...base, phase, alive, block, cutLine, finale: null };
}

export const TIE_BREAK_TIP = "Lowest score · tie-break: season points";

export function aliveRowLabel(row: AliveRow, phase: GuillotinePhase): string {
  const pts = row.score == null
    ? row.projected == null ? "not started" : `projected ${fmt1(row.projected)} points`
    : `${fmt1(row.score)} points`;
  const tail = row.onBlock
    ? phase === "pending" ? ", lowest score, cut pending" : ", on the block, lowest score this week"
    : "";
  return `${row.team.name}, rank ${row.rank}, ${pts}${tail}`;
}

export function outRowLabel(row: OutRow): string {
  return `${row.team.name}, eliminated week ${row.cutWeek}, finished ${ordinal(row.place)}`;
}

const wins = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : w === "loss" ? "es" : "s"}`;

/** "series 3 wins 1 loss", never "3 dash 1". */
export function spokenSeries(r: SeriesRecord): string {
  const parts = [wins(r.wins, "win"), wins(r.losses, "loss")];
  if (r.ties) parts.push(wins(r.ties, "tie"));
  return `series ${parts.join(" ")}`;
}

export function finalistLabel(f: Finalist, phase: GuillotinePhase): string {
  const live = f.score == null || phase === "champion" ? "" : `; this week ${fmt1(f.score)} live`;
  return `${f.team.name}, ${spokenSeries(f.series)}, ${fmt1(f.series.points)} finale points${f.leading ? ", leading the series" : ""}${live}`;
}

/** Weeks the finale has run: from the week after the last cut through `lastWeek`. */
export function finaleWeekRange(teams: GTeam[], lastWeek: number): number[] {
  const lastCut = teams.reduce((m, t) => Math.max(m, t.eliminated_week ?? 0), 0);
  const out: number[] = [];
  for (let w = lastCut + 1; w <= lastWeek; w++) out.push(w);
  return out;
}

