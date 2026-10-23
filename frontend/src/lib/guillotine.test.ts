import { describe, expect, it } from "vitest";
import {
  aliveRowLabel,
  deriveGuillotine,
  finalistLabel,
  type GGame,
  type GScore,
  type GSummary,
  type GTeam,
} from "./guillotine";

const team = (id: string, season: number, cut: number | null = null, created = "2026-08-01T00:00:00Z"): GTeam => ({
  id, name: id.toUpperCase(), eliminated_week: cut, created_at: created, points_for: season,
});
const score = (team_id: string, total_score: number, projected_score: number | null = null): GScore =>
  ({ team_id, total_score, projected_score });
const pre: GGame = { status_state: "pre", completed: false };
const live: GGame = { status_state: "in", completed: false };
const final: GGame = { status_state: "post", completed: true };
const postponed: GGame = { status_state: "post", completed: false };

type Row = [id: string, wins: number, losses: number, ties: number, points: number];
/** A backend summary: finalists leader first, as guillotine_placement.py sends them. */
const summary = (rows: Row[], weeks: number[], champion: string | null = null, places: Record<string, number | null> = {}): GSummary => ({
  phase: champion ? "final" : "finale",
  champion_team_id: champion,
  runner_up_team_id: champion ? rows.find((r) => r[0] !== champion)![0] : null,
  finalists: rows.map(([team_id, wins, losses, ties, points]) => ({ team_id, wins, losses, ties, points })),
  finale_weeks: weeks,
  places,
});

const midTeams = [team("a", 900), team("b", 850), team("c", 800), team("d", 700, 2), team("e", 400, 1)];

describe("deriveGuillotine phase", () => {
  it.each([
    ["no game started", [pre, pre], "prekickoff"],
    ["a game is live", [final, live, pre], "live"],
    ["every game final", [final, final], "pending"],
    ["final except a postponed game", [final, postponed], "pending"],
  ] as const)("%s → %s", (_, games, phase) => {
    const s = deriveGuillotine({ week: 3, teams: midTeams, scores: [score("a", 90), score("b", 80), score("c", 70)], games: [...games] });
    expect(s.phase).toBe(phase);
  });

  it("is not pending once this week's cut is on record", () => {
    const teams = [...midTeams.slice(0, 2), team("c", 800, 3), ...midTeams.slice(3)];
    const s = deriveGuillotine({ week: 3, teams: [...teams, team("f", 600)], scores: [], games: [final] });
    expect(s.phase).toBe("live");
  });

  it("holds the previous week as pending when the rollover skipped its cut", () => {
    const s = deriveGuillotine({
      week: 3, teams: [team("a", 900), team("b", 850), team("c", 800), team("e", 400, 1)],
      scores: [], games: [pre], prevScores: [score("a", 100), score("b", 95), score("c", 60)],
    });
    expect(s.phase).toBe("pending");
    expect(s.week).toBe(2);
    expect(s.block?.team.id).toBe("c");
  });

  it("falls back to scores when games could not be loaded", () => {
    expect(deriveGuillotine({ week: 3, teams: midTeams, scores: [score("a", 0)], games: null }).phase).toBe("prekickoff");
    expect(deriveGuillotine({ week: 3, teams: midTeams, scores: [score("a", 4.2)], games: null }).phase).toBe("live");
  });
});

describe("deriveGuillotine finale", () => {
  const finalTeams = [team("cd", 1751.9), team("ww", 1691.5), team("bb", 1010.5, 10), team("tt", 902.6, 9)];
  const none = summary([["cd", 0, 0, 0, 0], ["ww", 0, 0, 0, 0]], []);

  it("starts when two teams are left and stops the cut line", () => {
    const s = deriveGuillotine({ week: 11, teams: finalTeams, games: [final, final], scores: [], summary: none });
    expect(s.phase).toBe("finale");
    expect(s.cutLine).toBeNull();
    expect(s.alive).toEqual([]);
    expect(s.out.map((r) => r.place)).toEqual([3, 4]);
  });

  it("refuses to draw a finale without the backend summary", () => {
    expect(() => deriveGuillotine({ week: 11, teams: finalTeams, games: [live], scores: [] })).toThrow();
    const wrong = summary([["cd", 1, 0, 0, 100], ["bb", 0, 1, 0, 90]], [11]);
    expect(() => deriveGuillotine({ week: 12, teams: finalTeams, games: [live], scores: [], summary: wrong })).toThrow();
  });

  it("gives LEADING to the series leader even when trailing this week", () => {
    const s = deriveGuillotine({
      week: 15, teams: finalTeams, games: [live],
      scores: [score("cd", 90, 100), score("ww", 118.6, 121)],
      summary: summary([["cd", 3, 1, 0, 468.2], ["ww", 1, 3, 0, 441.7]], [11, 12, 13, 14]),
    });
    const [left, right] = s.finale!.finalists;
    expect([left.team.id, left.leading, right.leading]).toEqual(["cd", true, false]);
    expect(s.finale!.leadLine).toBe("CD leads the series 3\u20131 · +26.5 finale pts");
    expect(s.finale!.leadLineShort).toBe("CD leads the series 3\u20131");
    expect(s.finale!.weeks).toEqual([11, 12, 13, 14]);
  });

  it("keeps the backend order even when this week's score says otherwise", () => {
    const s = deriveGuillotine({
      week: 14, teams: finalTeams, games: [live], scores: [score("cd", 150), score("ww", 60)],
      summary: summary([["ww", 2, 1, 0, 349], ["cd", 1, 2, 0, 290]], [11, 12, 13]),
    });
    expect(s.finale!.finalists.map((f) => [f.team.id, f.leading])).toEqual([["ww", true], ["cd", false]]);
  });

  it("drops the LEADING tag when the series is level and names the points tie-break", () => {
    const s = deriveGuillotine({
      week: 15, teams: finalTeams, games: [live], scores: [score("cd", 101.2), score("ww", 104.8)],
      summary: summary([["cd", 2, 2, 0, 452.6], ["ww", 2, 2, 0, 449.1]], [11, 12, 13, 14]),
    });
    expect(s.finale!.finalists.some((f) => f.leading)).toBe(false);
    expect(s.finale!.tiedLabel).toBe("SERIES TIED 2\u20132");
    expect(s.finale!.leadLine).toBe("CD ahead on finale points by 3.5 (tie-break)");
    expect(s.finale!.tiedTip).toBe("Series tied · tie-break: finale points · CD +3.5");
  });

  it("names season points when the series and finale points are level", () => {
    const s = deriveGuillotine({
      week: 13, teams: finalTeams, games: [live], scores: [],
      summary: summary([["cd", 1, 1, 0, 220], ["ww", 1, 1, 0, 220]], [11, 12]),
    });
    expect(s.finale!.leadLine).toBe("Finale points level. CD ahead on season points (tie-break)");
    expect(s.finale!.tiedTip).toBe("Series tied · finale points even · tie-break: season points · CD");
    const even = [team("cd", 1700), team("ww", 1700), team("bb", 1010.5, 10), team("tt", 902.6, 9)];
    const flat = deriveGuillotine({
      week: 13, teams: even, games: [live], scores: [],
      summary: summary([["cd", 1, 1, 0, 220], ["ww", 1, 1, 0, 220]], [11, 12]),
    });
    expect(flat.finale!.leadLine).toBe("Series and finale points level");
  });

  it("shows W-L-T only once a finale week has tied", () => {
    const tie = deriveGuillotine({
      week: 14, teams: finalTeams, games: [live], scores: [],
      summary: summary([["cd", 1, 1, 1, 324], ["ww", 1, 1, 1, 305]], [11, 12, 13]),
    });
    expect(tie.finale!.tiedLabel).toBe("SERIES TIED 1\u20131\u20131");
    const lead = deriveGuillotine({
      week: 14, teams: finalTeams, games: [live], scores: [],
      summary: summary([["cd", 2, 0, 1, 345], ["ww", 0, 2, 1, 305]], [11, 12, 13]),
    });
    expect(lead.finale!.leadLineShort).toBe("CD leads the series 2\u20130\u20131");
  });

  it("speaks the series as wins and losses", () => {
    const s = deriveGuillotine({
      week: 15, teams: finalTeams, games: [live], scores: [score("cd", 118.6), score("ww", 100)],
      summary: summary([["cd", 3, 1, 0, 468.2], ["ww", 1, 3, 0, 441.7]], [11, 12, 13, 14]),
    });
    expect(finalistLabel(s.finale!.finalists[0], s.phase)).toBe(
      "CD, series 3 wins 1 loss, 468.2 finale points, leading the series; this week 118.6 live",
    );
  });

  it("uses this week's live score in the first finale week without a LEADING tag", () => {
    const s = deriveGuillotine({ week: 11, teams: finalTeams, games: [live], scores: [score("cd", 106), score("ww", 118.6)], summary: none });
    expect(s.finale!.finalists.map((f) => f.team.id)).toEqual(["cd", "ww"]);
    expect(s.finale!.finalists.some((f) => f.leading)).toBe(false);
    expect(s.finale!.tiedLabel).toBeNull();
    expect(s.finale!.leadLine).toBe("WW leads by 12.6");
    const tied = deriveGuillotine({ week: 11, teams: finalTeams, games: [live], scores: [score("cd", 112), score("ww", 112)], summary: none });
    expect(tied.finale!.leadLine).toBe("Tied at 112.0");
  });
});

describe("champion", () => {
  const teams = [team("cd", 2126.4), team("ww", 2151.7), team("bb", 1010.5, 10), team("tt", 902.6, 9)];
  const weeks = [11, 12, 13, 14, 15, 16, 17, 18];
  const places = { cd: 1, ww: 2, bb: 3, tt: 4 };

  it("crowns the backend champion, runner-up 2nd, then cuts by most recent", () => {
    const s = deriveGuillotine({
      week: 18, teams, games: [final], scores: [],
      summary: summary([["cd", 5, 3, 0, 973.4], ["ww", 3, 5, 0, 952.1]], weeks, "cd", places),
    });
    expect(s.phase).toBe("champion");
    expect(s.cutLine).toBeNull();
    const [champ, runnerUp] = s.finale!.finalists;
    expect([champ.team.id, champ.series.wins, champ.series.losses]).toEqual(["cd", 5, 3]);
    expect(runnerUp.team.id).toBe("ww");
    expect(s.out.map((r) => [r.team.id, r.place])).toEqual([["bb", 3], ["tt", 4]]);
    expect(champ.score).toBeNull();
  });

  it("crowns the series winner even when the runner-up has more season points", () => {
    const s = deriveGuillotine({
      week: 18, teams, games: [final], scores: [],
      summary: summary([["cd", 5, 3, 0, 900], ["ww", 3, 5, 0, 1000]], weeks, "cd", places),
    });
    expect(s.finale!.finalists[0].team.id).toBe("cd");
  });

  it("stays in the finale until the backend names a champion", () => {
    const s = deriveGuillotine({
      week: 17, teams, games: [final], scores: [],
      summary: summary([["cd", 4, 3, 0, 850], ["ww", 3, 4, 0, 840]], weeks.slice(0, 7)),
    });
    expect(s.phase).toBe("finale");
  });

  it("rejects a summary that lists the champion second", () => {
    expect(() => deriveGuillotine({
      week: 18, teams, games: [final], scores: [],
      summary: summary([["ww", 3, 5, 0, 952.1], ["cd", 5, 3, 0, 973.4]], weeks, "cd", places),
    })).toThrow();
  });
});

describe("row labels", () => {
  it("reads the block row with its reason", () => {
    const s = deriveGuillotine({ week: 6, teams: midTeams, games: [live], scores: [score("a", 82.7), score("b", 90), score("c", 99)] });
    expect(aliveRowLabel(s.alive[2], s.phase)).toBe("A, rank 3, 82.7 points, on the block, lowest score this week");
  });
});
