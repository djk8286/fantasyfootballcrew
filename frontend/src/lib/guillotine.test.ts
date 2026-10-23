import { describe, expect, it } from "vitest";
import {
  aliveRowLabel,
  deriveGuillotine,
  finaleSeries,
  finaleWeekRange,
  finalistLabel,
  ordinal,
  outRowLabel,
  type GGame,
  type GScore,
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

describe("deriveGuillotine live ordering", () => {
  it("puts the lowest live score on the block with the margin behind the next team", () => {
    const s = deriveGuillotine({
      week: 3, teams: midTeams, games: [live],
      scores: [score("a", 82.7), score("b", 128.4), score("c", 96.1)],
    });
    expect(s.alive.map((r) => [r.team.id, r.rank, r.onBlock, r.clearBy])).toEqual([
      ["b", 1, false, 45.7],
      ["c", 2, false, 13.4],
      ["a", 3, true, null],
    ]);
    expect(s.block).toMatchObject({ score: 82.7, behindBy: 13.4, behindName: "C" });
    expect(s.cutLine).toBe("live");
  });

  it("breaks a tie for lowest like the backend: fewer season points, then earliest team", () => {
    const teams = [
      team("old", 500, null, "2026-07-01T00:00:00Z"),
      team("new", 500, null, "2026-07-05T00:00:00Z"),
      team("rich", 900),
    ];
    const s = deriveGuillotine({ week: 1, teams, games: [live], scores: [score("old", 70), score("new", 70), score("rich", 70)] });
    expect(s.alive.map((r) => r.team.id)).toEqual(["rich", "new", "old"]);
    expect(s.block?.team.id).toBe("old");
  });

  it("previews the line in week 1 before anyone is cut", () => {
    const s = deriveGuillotine({ week: 1, teams: [team("a", 0), team("b", 0), team("c", 0)], games: [live], scores: [score("a", 10)] });
    expect(s.noCutsYet).toBe(true);
    expect(s.cutLine).toBe("preview");
    expect(s.out).toEqual([]);
  });
});

describe("deriveGuillotine pre-kickoff", () => {
  it("sorts by projection, leaves nobody on the block and draws the neutral line", () => {
    const s = deriveGuillotine({
      week: 8, teams: midTeams, games: [pre],
      scores: [score("a", 0, 101.7), score("b", 0, 126.3), score("c", 0, 101.7)],
    });
    expect(s.alive.map((r) => r.team.id)).toEqual(["b", "a", "c"]);
    expect(s.alive.every((r) => !r.onBlock && r.score == null)).toBe(true);
    expect(s.block).toBeNull();
    expect(s.cutLine).toBe("neutral");
  });
});

describe("eliminated rows", () => {
  it("lists the latest cut first and places them under the alive teams", () => {
    const s = deriveGuillotine({ week: 3, teams: midTeams, games: [pre], scores: [] });
    expect(s.out.map((r) => [r.team.id, r.cutWeek, r.place])).toEqual([["d", 2, 4], ["e", 1, 5]]);
    expect(outRowLabel(s.out[0])).toBe("D, eliminated week 2, finished 4th");
  });

  it.each([[1, "1st"], [2, "2nd"], [3, "3rd"], [4, "4th"], [11, "11th"], [12, "12th"], [13, "13th"], [22, "22nd"]])(
    "ordinal(%i) = %s", (n, out) => expect(ordinal(n)).toBe(out),
  );
});

describe("finale", () => {
  const finalTeams = [team("cd", 1751.9), team("ww", 1691.5), team("bb", 1010.5, 10), team("tt", 902.6, 9)];
  const wk = (cd: number, ww: number) => [{ home_team_id: "cd", home_score: cd, away_team_id: "ww", away_score: ww }];

  it("starts when two teams are left and stops the cut line", () => {
    const s = deriveGuillotine({ week: 11, teams: finalTeams, games: [final, final], scores: [] });
    expect(s.phase).toBe("finale");
    expect(s.cutLine).toBeNull();
    expect(s.alive).toEqual([]);
    expect(s.out.map((r) => r.place)).toEqual([3, 4]);
  });

  it("counts the head-to-head series and finale points", () => {
    const { a, b, played } = finaleSeries("cd", "ww", [wk(120, 100), wk(90, 110), [], wk(130.1, 101)]);
    expect(played).toBe(3);
    expect(a).toEqual({ wins: 2, losses: 1, ties: 0, points: 340.1 });
    expect(b).toEqual({ wins: 1, losses: 2, ties: 0, points: 311 });
  });

  it("gives LEADING to the series leader even when trailing this week", () => {
    const s = deriveGuillotine({
      week: 15, teams: finalTeams, games: [live],
      scores: [score("cd", 90, 100), score("ww", 118.6, 121)],
      finaleWeeks: [wk(120, 100), wk(110, 90), wk(80, 100), wk(158.2, 151.7)],
    });
    const [left, right] = s.finale!.finalists;
    expect([left.team.id, left.leading, right.leading]).toEqual(["cd", true, false]);
    expect(s.finale!.leadLine).toBe("CD leads the series 3\u20131 · +26.5 finale pts");
    expect(s.finale!.leadLineShort).toBe("CD leads the series 3\u20131");
  });

  it("drops the LEADING tag when the series is level and names the points tie-break", () => {
    const s = deriveGuillotine({
      week: 15, teams: finalTeams, games: [live], scores: [score("cd", 101.2), score("ww", 104.8)],
      finaleWeeks: [wk(120, 100), wk(100, 120), wk(116.1, 100), wk(116.5, 129.1)],
    });
    expect(s.finale!.finalists.some((f) => f.leading)).toBe(false);
    expect(s.finale!.tiedLabel).toBe("SERIES TIED 2\u20132");
    expect(s.finale!.leadLine).toBe("CD ahead on finale points by 3.5 (tie-break)");
    expect(s.finale!.tiedTip).toBe("Series tied · tie-break: finale points · CD +3.5");
  });

  it("orders finalists by series, then finale points, and never by this week's score", () => {
    const s = deriveGuillotine({
      week: 14, teams: finalTeams, games: [live], scores: [score("cd", 150), score("ww", 60)],
      finaleWeeks: [wk(100, 120), wk(100, 99), wk(90, 130)],
    });
    expect(s.finale!.finalists.map((f) => [f.team.id, f.leading])).toEqual([["ww", true], ["cd", false]]);
    const tied = deriveGuillotine({
      week: 13, teams: finalTeams, games: [live], scores: [],
      finaleWeeks: [wk(100, 120), wk(110, 100)],
    });
    expect(tied.finale!.finalists[0].team.id).toBe("ww");
    expect(tied.finale!.tiedTip).toBe("Series tied · tie-break: finale points · WW +10.0");
  });

  it("shows W-L-T only once a finale week has tied", () => {
    const noTie = deriveGuillotine({ week: 13, teams: finalTeams, games: [live], scores: [], finaleWeeks: [wk(120, 100), wk(99, 100)] });
    expect(noTie.finale!.tiedLabel).toBe("SERIES TIED 1\u20131");
    const tie = deriveGuillotine({
      week: 14, teams: finalTeams, games: [live], scores: [],
      finaleWeeks: [wk(120, 100), wk(99, 100), wk(105, 105)],
    });
    expect(tie.finale!.tiedLabel).toBe("SERIES TIED 1\u20131\u20131");
    const lead = deriveGuillotine({
      week: 14, teams: finalTeams, games: [live], scores: [],
      finaleWeeks: [wk(120, 100), wk(120, 100), wk(105, 105)],
    });
    expect(lead.finale!.leadLineShort).toBe("CD leads the series 2\u20130\u20131");
  });

  it("reads a level series and level points without a tie-break winner", () => {
    const s = deriveGuillotine({ week: 13, teams: finalTeams, games: [live], scores: [], finaleWeeks: [wk(120, 100), wk(100, 120)] });
    expect(s.finale!.leadLine).toBe("Series and finale points level");
    expect(s.finale!.tiedTip).toBe("Series tied · finale points even");
  });

  it("speaks the series as wins and losses", () => {
    const s = deriveGuillotine({
      week: 15, teams: finalTeams, games: [live], scores: [score("cd", 118.6), score("ww", 100)],
      finaleWeeks: [wk(120, 100), wk(110, 90), wk(80, 100), wk(158.2, 151.7)],
    });
    expect(finalistLabel(s.finale!.finalists[0], s.phase)).toBe(
      "CD, series 3 wins 1 loss, 468.2 finale points, leading the series; this week 118.6 live",
    );
  });

  it("uses this week's live score in the first finale week without a LEADING tag", () => {
    const s = deriveGuillotine({ week: 11, teams: finalTeams, games: [live], scores: [score("cd", 106), score("ww", 118.6)] });
    expect(s.finale!.finalists.map((f) => f.team.id)).toEqual(["cd", "ww"]);
    expect(s.finale!.finalists.some((f) => f.leading)).toBe(false);
    expect(s.finale!.tiedLabel).toBeNull();
    expect(s.finale!.leadLine).toBe("WW leads by 12.6");
    const tied = deriveGuillotine({ week: 11, teams: finalTeams, games: [live], scores: [score("cd", 112), score("ww", 112)] });
    expect(tied.finale!.leadLine).toBe("Tied at 112.0");
    expect(tied.finale!.finalists.some((f) => f.leading)).toBe(false);
  });
});

describe("champion", () => {
  const teams = [team("cd", 2126.4), team("ww", 2151.7), team("bb", 1010.5, 10), team("tt", 902.6, 9)];
  const wk = (cd: number, ww: number) => [{ home_team_id: "ww", home_score: ww, away_team_id: "cd", away_score: cd }];
  const weeks = [wk(130, 120), wk(120, 130), wk(125, 110), wk(140, 100), wk(90, 110), wk(120, 119.9), wk(117.7, 112)];

  it("crowns the series winner once the season is over, runner-up 2nd, then cuts by most recent", () => {
    const s = deriveGuillotine({ week: 17, teams, games: [final], scores: [], finaleWeeks: weeks, seasonOver: true });
    expect(s.phase).toBe("champion");
    expect(s.cutLine).toBeNull();
    const [champ, runnerUp] = s.finale!.finalists;
    expect([champ.team.id, champ.series.wins, champ.series.losses]).toEqual(["cd", 5, 2]);
    expect(runnerUp.team.id).toBe("ww");
    expect(s.out.map((r) => [r.team.id, r.place])).toEqual([["bb", 3], ["tt", 4]]);
    expect(champ.score).toBeNull();
  });

  it("stays in the finale until the season rolls over", () => {
    const s = deriveGuillotine({ week: 17, teams, games: [final], scores: [], finaleWeeks: weeks });
    expect(s.phase).toBe("finale");
  });

  it("counts finale weeks from the week after the last cut", () => {
    expect(finaleWeekRange(teams, 17)).toEqual([11, 12, 13, 14, 15, 16, 17]);
    expect(finaleWeekRange(teams, 10)).toEqual([]);
  });
});

describe("row labels", () => {
  it("reads the block row with its reason", () => {
    const s = deriveGuillotine({ week: 6, teams: midTeams, games: [live], scores: [score("a", 82.7), score("b", 90), score("c", 99)] });
    expect(aliveRowLabel(s.alive[2], s.phase)).toBe("A, rank 3, 82.7 points, on the block, lowest score this week");
  });
});
