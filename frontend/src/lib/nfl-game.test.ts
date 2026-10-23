import { describe, expect, it } from "vitest";
import { nflScoreLine } from "./nfl-game";

describe("nflScoreLine", () => {
  it("shows no score before kickoff, even when the feed says 0-0", () => {
    expect(nflScoreLine({ status_state: "pre", completed: false, home_score: 0, away_score: 0 })).toBeNull();
    expect(nflScoreLine({ status_state: "pre", completed: false, home_score: null, away_score: null })).toBeNull();
  });

  it("shows away - home once the game is live or final", () => {
    expect(nflScoreLine({ status_state: "in", completed: false, home_score: 10, away_score: 6 })).toBe("6 - 10");
    expect(nflScoreLine({ status_state: "in", completed: false, home_score: 0, away_score: 0 })).toBe("0 - 0");
    expect(nflScoreLine({ status_state: "post", completed: true, home_score: 27, away_score: 30 })).toBe("30 - 27");
  });

  it("treats a game with no known state as not started unless it's final", () => {
    expect(nflScoreLine({ completed: false, home_score: 0, away_score: 0 })).toBeNull();
    expect(nflScoreLine({ completed: true, home_score: 3, away_score: 0 })).toBe("0 - 3");
  });
});
