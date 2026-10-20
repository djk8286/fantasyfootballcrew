import { describe, expect, it } from "vitest";
import { groupRoster, ordinal, preDraftNote, recordText, scheduleRows, type ScheduleWeek } from "./team-page";

describe("groupRoster", () => {
  it("groups by position in roster order with starters first", () => {
    const rows = [
      { id: "k", position: "K", slot: "K" },
      { id: "wr-bn", position: "WR", slot: "BN" },
      { id: "qb", position: "QB", slot: "QB" },
      { id: "wr", position: "WR", slot: "FLEX" },
      { id: "x", position: "P", slot: "BN" },
    ];
    expect(groupRoster(rows).map((g) => [g.position, g.players.map((p) => p.id)])).toEqual([
      ["QB", ["qb"]],
      ["WR", ["wr", "wr-bn"]],
      ["K", ["k"]],
      ["P", ["x"]],
    ]);
  });
});

const side = (id: string, score: number | null) => ({ id, name: id.toUpperCase(), score });

describe("scheduleRows", () => {
  const weeks: ScheduleWeek[] = [
    { week: 6, status: "final", matchups: [{ team_a: side("me", 90), team_b: side("b", 100) }] },
    { week: 7, status: "live", matchups: [{ team_a: side("c", 40), team_b: side("me", 55) }] },
    { week: 8, status: "upcoming", matchups: [{ team_a: side("me", null), team_b: side("d", null) }] },
    { week: 9, status: "upcoming", matchups: [{ team_a: side("e", null), team_b: side("me", null) }] },
    { week: 10, status: "upcoming", matchups: [{ team_a: side("x", null), team_b: side("y", null) }] },
  ];

  it("reads my side, gives final weeks a result, and marks the first upcoming game next", () => {
    const rows = scheduleRows(weeks, "me");
    expect(rows.map((r) => [r.week, r.opponent?.id ?? null, r.result, r.status, r.next])).toEqual([
      [6, "b", "L", "final", false],
      [7, "c", null, "live", false],
      [8, "d", null, "upcoming", true],
      [9, "e", null, "upcoming", false],
      [10, null, null, "upcoming", false],
    ]);
    expect(rows[1].me).toBe(55);
  });

  it("calls a tie a tie", () => {
    const tie: ScheduleWeek[] = [{ week: 6, status: "final", matchups: [{ team_a: side("me", 80), team_b: side("b", 80) }] }];
    expect(scheduleRows(tie, "me")[0].result).toBe("T");
  });
});

describe("header text", () => {
  it("ordinal", () => {
    expect([1, 2, 3, 4, 11, 12, 13, 21, 22].map(ordinal)).toEqual(["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd"]);
  });
  it("recordText hides zero ties", () => {
    expect(recordText({ wins: 3, losses: 2, ties: 0 })).toBe("3-2");
    expect(recordText({ wins: 3, losses: 2, ties: 1 })).toBe("3-2-1");
  });
  it("preDraftNote", () => {
    expect(preDraftNote(1)).toBeNull();
    expect(preDraftNote(2)).toBe("Week 1 came before the draft.");
    expect(preDraftNote(6)).toBe("Weeks 1 to 5 came before the draft.");
  });
});

describe("groupRoster without lineup data", () => {
  it("keeps roster order when slots are hidden from guests", () => {
    const rows = [
      { id: "a", position: "WR", slot: null },
      { id: "b", position: "QB", slot: null },
      { id: "c", position: "WR", slot: null },
    ];
    expect(groupRoster(rows).map((g) => [g.position, g.players.map((p) => p.id)])).toEqual([
      ["QB", ["b"]],
      ["WR", ["a", "c"]],
    ]);
  });
});
