import { describe, expect, it } from "vitest";
import { tradeOptionLabel, defaultComparePair, pendingTradeView, pickFromTeam, tradeAccepted } from "./trade-label";

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

describe("pendingTradeView", () => {
  const name = (id: string) => ({ a: "Crew Destroyers", b: "Waiver Wolves", c: "Bye Week Bandits" })[id];
  const offer = { team_id: "a", status: "pending", details: { target_team_id: "b" } };

  it("lets the receiving team answer an unanswered offer", () => {
    expect(pendingTradeView(offer, ["b"], name)).toEqual({ note: "Your answer is needed.", canRespond: true, canCancel: false });
  });
  it("tells the proposer who it is waiting on", () => {
    expect(pendingTradeView(offer, ["a"], name)).toEqual({
      note: "Waiting on Waiver Wolves to accept or decline.", canRespond: false, canCancel: true,
    });
  });
  it("hands an accepted offer to the commissioner", () => {
    const accepted = { ...offer, details: { target_team_id: "b", recipient_response: "accepted" as const } };
    expect(pendingTradeView(accepted, ["b"], name)).toEqual({
      note: "Waiver Wolves accepted. Awaiting commissioner approval.", canRespond: false, canCancel: false,
    });
    expect(tradeAccepted(accepted.details)).toBe(true);
    expect(tradeAccepted(offer.details)).toBe(false);
  });
  it("keeps the CPU's own reason line and only adds the next step", () => {
    const cpu = { team_id: "a", status: "pending", details: { target_team_id: "c", cpu_response: "accepted" as const } };
    expect(pendingTradeView(cpu, ["a"], name).note).toBe("Awaiting commissioner approval.");
  });
  it("has nothing to say once a trade is closed", () => {
    expect(pendingTradeView({ ...offer, status: "denied" }, ["b"], name)).toEqual({ note: null, canRespond: false, canCancel: false });
  });
});

describe("pickFromTeam", () => {
  const mine = [{ id: "squad-a" }, { id: "squad-b" }];
  it("uses the picked team", () => {
    expect(pickFromTeam(mine, "squad-b")?.id).toBe("squad-b");
  });
  it("falls back to the first team when nothing or a stale team is picked", () => {
    expect(pickFromTeam(mine, "")?.id).toBe("squad-a");
    expect(pickFromTeam(mine, "gone")?.id).toBe("squad-a");
  });
  it("is empty when you manage no team", () => {
    expect(pickFromTeam([], "squad-a")).toBeUndefined();
  });
});
