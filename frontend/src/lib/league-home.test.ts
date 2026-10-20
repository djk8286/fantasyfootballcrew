import { describe, expect, it } from "vitest";
import { barShare, headline, homeMode, leagueChips, recapLine, scoreboardTitle, shortTeamName, winChance, type Recap } from "./league-home";

const recap = (over: Partial<Recap>): Recap => ({
  week: 6, result: "L", score: 57.6, opponent_score: 109.04, opponent_team_id: "b", opponent_name: "Team 11",
  optimal_score: 77.8, bench_points: 20.2, ...over,
});

describe("league home helpers", () => {
  it("builds setting chips and shows open spots", () => {
    expect(leagueChips({ visibility: "open", team_count: 12, max_teams: 12, league_type: "standard", scoring: "PPR", draft_status: "completed" }))
      .toEqual(["Open", "12 teams", "Standard", "PPR", "Draft done"]);
    expect(leagueChips({ visibility: "invite_only", team_count: 3, max_teams: 10, league_type: "two_man", scoring: "Half PPR", draft_status: "not_started" })[1])
      .toBe("3 of 10 teams");
  });

  it("picks the page mode from the draft status", () => {
    expect(homeMode("not_started")).toBe("predraft");
    expect(homeMode("in_progress")).toBe("drafting");
    expect(homeMode("completed")).toBe("season");
  });

  it("leads with the score once there is one, else the projection", () => {
    expect(headline({ team_id: "a", name: "A", score: null, projected: 100.9 })).toBe(100.9);
    expect(headline({ team_id: "a", name: "A", score: 0, projected: 100.9 })).toBe(0);
  });

  it("splits the bar and estimates a win chance", () => {
    expect(barShare(null, null)).toBe(0.5);
    expect(barShare(75, 25)).toBe(0.75);
    expect(winChance(100, 100)).toBe(50);
    expect(winChance(101, 67.7)).toBeGreaterThan(80);
    expect(winChance(null, 90)).toBeNull();
  });

  it("only recaps a loss or a big bench miss", () => {
    expect(recapLine(recap({}))).toBe(
      "You lost 57.6 to 109.0. 20.2 points stayed on your bench. Your best lineup would have scored 77.8.",
    );
    expect(recapLine(recap({ result: "W", score: 120, opponent_score: 90, bench_points: 2 }))).toBeNull();
    expect(recapLine(recap({ result: "L", score: 90, opponent_score: 95, optimal_score: 100, bench_points: 10 }))).toContain("That lineup wins.");
    expect(recapLine(recap({ bench_points: 1, optimal_score: 58.6 }))).toBe("You lost 57.6 to 109.0.");
    expect(recapLine(null)).toBeNull();
  });

  it("drops the league name from default team names only", () => {
    expect(shortTeamName("QA Test League Team 4", "QA Test League")).toBe("Team 4");
    expect(shortTeamName("QA Tester Team", "QA Test League")).toBe("QA Tester Team");
    expect(shortTeamName("QA Test League", "QA Test League")).toBe("QA Test League");
  });
});

describe("scoreboardTitle", () => {
  const side = (score: number | null, projected: number | null) => ({ team_id: "t", name: "T", score, projected });
  it("says scores once games start", () => {
    expect(scoreboardTitle(7, [{ team_a: side(10, 90), team_b: side(null, 80) }])).toBe("Week 7 scores");
  });
  it("says projections before kickoff when projections are shown", () => {
    expect(scoreboardTitle(7, [{ team_a: side(null, 90), team_b: side(null, 80) }])).toBe("Week 7 projections");
  });
  it("says matchups for guests, who get no projections", () => {
    expect(scoreboardTitle(7, [{ team_a: side(null, null), team_b: side(null, null) }])).toBe("Week 7 matchups");
  });
});
