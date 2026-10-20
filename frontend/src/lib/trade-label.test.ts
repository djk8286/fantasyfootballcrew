import { describe, expect, it } from "vitest";
import { tradeOptionLabel, defaultComparePair } from "./trade-label";

const teams: Record<string, string> = { a: "QA Tester Team", b: "CPU Team 3" };
const players: Record<string, string> = { p1: "Tyler Loop", p2: "Matt Gay", p3: "Bijan Robinson", p4: "RJ Harvey", p5: "Josh Allen" };

describe("tradeOptionLabel", () => {
  it("names teams and players so trades are distinguishable", () => {
    const t = { id: "1", team_id: "a", status: "pending", details: { target_team_id: "b", offered_player_ids: ["p1"], requested_player_ids: ["p2"] } };
    expect(tradeOptionLabel(t, (id) => teams[id], (id) => players[id])).toBe("Pending: QA Tester Team gives Tyler Loop to CPU Team 3 for Matt Gay");
  });
  it("summarises big packages and tolerates unknown ids", () => {
    const t = { id: "2", team_id: "a", status: "denied", details: { target_team_id: "zz", offered_player_ids: ["p1", "p3", "p4"], requested_player_ids: ["nope"] } };
    expect(tradeOptionLabel(t, (id) => teams[id], (id) => players[id])).toBe(
      "Denied: QA Tester Team gives Tyler Loop + Bijan Robinson +1 more to Unknown team for Unknown player"
    );
  });
});

describe("defaultComparePair", () => {
  const ts = [{ id: "t4", owner_id: null }, { id: "t1", owner_id: "me" }, { id: "t2", owner_id: "u2" }];
  it("starts with my team and never picks the same team twice", () => {
    expect(defaultComparePair(ts, "me")).toEqual(["t1", "t4"]);
    expect(defaultComparePair(ts, null)).toEqual(["t4", "t1"]);
    expect(defaultComparePair([{ id: "solo" }], "me")).toEqual(["solo", ""]);
  });
});
