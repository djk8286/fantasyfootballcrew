// Guillotine standings state, derived from data the API already returns.
// The live cut line mirrors backend guillotine_service.process_league_guillotine:
// the lowest weekly score is cut, ties go to fewer season points, then the
// earliest-created team. Cuts stop at 2 alive teams. The finale series,
// champion and final places come from the backend summary
// (guillotine_placement.py) and are drawn as sent.

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
  /** Champion first once decided, otherwise the series leader first. */
  finalists: [Finalist, Finalist];
  seriesPlayed: number;
  /** Counted finale weeks, oldest first, from the backend. */
  weeks: number[];
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
  /** The backend's placement (GET /standings "guillotine"). It owns the
   * finale series, the champion and final places. Required once the
   * finale is set. */
  summary?: GSummary | null;
}

export interface GSummaryFinalist {
  team_id: string;
  wins: number;
  losses: number;
  ties: number;
  points: number;
}

/** backend guillotine_placement.py */
export interface GSummary {
  phase: "elimination" | "finale" | "final";
  champion_team_id: string | null;
  runner_up_team_id: string | null;
  /** Leader first: series W-L, then finale points, then season points. */
  finalists: GSummaryFinalist[];
  /** Counted finale weeks, oldest first. */
  finale_weeks: number[];
  places: Record<string, number | null>;
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

export function seriesText(r: SeriesRecord): string {
  return r.ties ? `${r.wins}${DASH}${r.losses}${DASH}${r.ties}` : `${r.wins}${DASH}${r.losses}`;
}

function buildFinale(week: number, alive: GTeam[], byId: Map<string, GScore>, summary: GSummary, started: boolean): FinaleState {
  const teamById = new Map(alive.map((t) => [t.id, t]));
  const rows = summary.finalists;
  if (rows.length !== 2 || !rows.every((r) => teamById.has(r.team_id))) {
    throw new Error("finale summary does not match the alive teams");
  }
  const played = summary.finale_weeks.length;
  // The backend sends the leader first, so the order is used as is.
  const [f1, f2] = rows.map((r): Finalist => ({
    team: teamById.get(r.team_id)!,
    score: started ? byId.get(r.team_id)?.total_score ?? 0 : null,
    projected: byId.get(r.team_id)?.projected_score ?? null,
    series: { wins: r.wins, losses: r.losses, ties: r.ties, points: round1(r.points) },
    leading: false,
  }));
  if (summary.champion_team_id && summary.champion_team_id !== f1.team.id) {
    throw new Error("finale summary lists the champion second");
  }

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
    } else if (f1.team.points_for !== f2.team.points_for) {
      leadLine = `Finale points level. ${f1.team.name} ahead on season points (tie-break)`;
      leadLineShort = `${f1.team.name} ahead on season pts`;
      tiedTip = `Series tied · finale points even · tie-break: season points · ${f1.team.name}`;
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

  return { week, finalists: [f1, f2], seriesPlayed: played, weeks: summary.finale_weeks, seriesTied: tiedLabel != null, leadLine, leadLineShort, tiedLabel, tiedTip };
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

  const summary = input.summary ?? null;
  if (aliveTeams.length <= 2 && teams.length > 2) {
    phase = summary?.champion_team_id ? "champion" : "finale";
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
    .map((team, i) => ({
      team,
      cutWeek: team.eliminated_week ?? 0,
      place: summary?.places[team.id] ?? aliveTeams.length + i + 1,
    }));

  const base = {
    week,
    totalTeams: teams.length,
    aliveCount: aliveTeams.length,
    noCutsYet: cutTeams.length === 0,
    out,
  };

  if (phase === "finale" || phase === "champion") {
    if (aliveTeams.length === 2 && !summary) throw new Error("finale needs the backend summary");
    return {
      ...base,
      phase,
      cutLine: null,
      alive: [],
      block: null,
      finale: aliveTeams.length === 2 && summary
        ? buildFinale(week, aliveTeams, byId, summary, phase === "finale" && anyStarted)
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
