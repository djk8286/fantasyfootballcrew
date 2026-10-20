import { describe, expect, it } from "vitest";
import { applyMove, benchIds, issuesFor, lineupLoadProblem, moveWarning, projectedTotal, targetsFor, type LineupPlayer, type Slot } from "./lineup";

const P = (id: string, position: string, extra: Partial<LineupPlayer> = {}): LineupPlayer => ({
  id, name: id.toUpperCase(), position, injuryStatus: null, locked: false, onBye: false, ...extra,
});

const players: Record<string, LineupPlayer> = Object.fromEntries(
  [
    P("qb1", "QB"), P("qb2", "QB"), P("rb1", "RB"), P("rb2", "RB"), P("rb3", "RB"),
    P("wr1", "WR"), P("wr2", "WR", { injuryStatus: "Out" }), P("te1", "TE"),
    P("k1", "K"), P("lockedrb", "RB", { locked: true }), P("byewr", "WR", { onBye: true }),
  ].map((p) => [p.id, p]),
);

const slots: Slot[] = [
  { slot: "QB", player_id: "qb1" },
  { slot: "RB", player_id: "rb1" },
  { slot: "RB", player_id: "lockedrb" },
  { slot: "WR", player_id: "wr1" },
  { slot: "FLEX", player_id: "rb2" },
  { slot: "TE", player_id: null },
];
const bench = benchIds(slots, Object.keys(players));

describe("targetsFor", () => {
  it("a bench QB can only go to the QB slot", () => {
    const t = targetsFor(slots, { kind: "bench", playerId: "qb2" }, players, bench);
    expect([...t.slots]).toEqual([0]);
  });

  it("a bench RB can take an RB or FLEX slot, but not a locked RB's", () => {
    const t = targetsFor(slots, { kind: "bench", playerId: "rb3" }, players, bench);
    expect([...t.slots]).toEqual([1, 4]);
  });

  it("the FLEX starter can swap with an RB slot or a WR slot whose player fits FLEX", () => {
    const t = targetsFor(slots, { kind: "slot", index: 4 }, players, bench);
    expect([...t.slots]).toEqual([1]); // rb2 can't play WR, so no swap with slot 3
    expect([...t.bench].sort()).toEqual(["byewr", "rb3", "te1", "wr2"]);
    expect(t.toBench).toBe(true);
  });

  it("a WR starter swaps with FLEX only when the FLEX player can play WR", () => {
    const t = targetsFor(slots, { kind: "slot", index: 3 }, players, bench);
    expect(t.slots.has(4)).toBe(false);
  });

  it("an empty slot offers eligible bench players and nothing to bench", () => {
    const t = targetsFor(slots, { kind: "slot", index: 5 }, players, bench);
    expect([...t.bench]).toEqual(["te1"]);
    expect(t.toBench).toBe(false);
  });

  it("a locked starter can't be picked", () => {
    const t = targetsFor(slots, { kind: "slot", index: 2 }, players, bench);
    expect(t.slots.size + t.bench.size).toBe(0);
    expect(t.toBench).toBe(false);
  });
});

describe("applyMove", () => {
  it("swaps two starters", () => {
    const next = applyMove(slots, { kind: "slot", index: 1 }, { kind: "slot", index: 4 });
    expect(next[1].player_id).toBe("rb2");
    expect(next[4].player_id).toBe("rb1");
    expect(slots[1].player_id).toBe("rb1"); // input untouched
  });

  it("a bench player takes a slot in either tap order", () => {
    const a = applyMove(slots, { kind: "slot", index: 0 }, { kind: "bench", playerId: "qb2" });
    const b = applyMove(slots, { kind: "bench", playerId: "qb2" }, { kind: "slot", index: 0 });
    expect(a[0].player_id).toBe("qb2");
    expect(b).toEqual(a);
  });

  it("moving a starter to the bench empties his slot", () => {
    expect(applyMove(slots, { kind: "slot", index: 3 }, "bench")[3].player_id).toBeNull();
  });
});

describe("issuesFor", () => {
  it("flags an Out or bye starter the moment he's in a slot, plus empty slots", () => {
    const withOut = applyMove(slots, { kind: "bench", playerId: "wr2" }, { kind: "slot", index: 3 });
    const withBye = applyMove(withOut, { kind: "bench", playerId: "byewr" }, { kind: "slot", index: 4 });
    expect(issuesFor(withBye, players).map((i) => [i.kind, i.slotIndex])).toEqual([["out", 3], ["bye", 4], ["empty", 5]]);
    expect(issuesFor(withBye, players)[0].message).toBe("WR2 is listed Out and may not play.");
  });

  it("Questionable isn't an issue", () => {
    const q = { ...players, wr1: { ...players.wr1, injuryStatus: "Questionable" } };
    expect(issuesFor(slots, q).map((i) => i.kind)).toEqual(["empty"]);
  });
});

describe("moveWarning", () => {
  it("flags starting an Out player at the moment of the swap", () => {
    expect(moveWarning(slots, { kind: "bench", playerId: "wr2" }, { kind: "slot", index: 3 }, players)).toBe(
      "WR2 is listed Out and may not play.",
    );
  });

  it("flags starting a player on bye", () => {
    expect(moveWarning(slots, { kind: "slot", index: 3 }, { kind: "bench", playerId: "byewr" }, players)).toBe(
      "BYEWR is on bye and won't score.",
    );
  });

  it("stays quiet for a healthy swap", () => {
    expect(moveWarning(slots, { kind: "bench", playerId: "rb3" }, { kind: "slot", index: 1 }, players)).toBeNull();
  });

  it("doesn't repeat a warning that was already there", () => {
    const withOut = slots.map((s, i) => (i === 3 ? { ...s, player_id: "wr2" } : s));
    expect(moveWarning(withOut, { kind: "bench", playerId: "qb2" }, { kind: "slot", index: 0 }, players)).toBeNull();
  });
});

describe("projectedTotal", () => {
  const two: Slot[] = [
    { slot: "QB", player_id: "qb1" },
    { slot: "RB", player_id: "rb1" },
    { slot: "WR", player_id: null },
  ];

  it("adds up the starters and counts an unprojected starter as 0", () => {
    expect(projectedTotal(two, { qb1: 21.4, rb1: null, wr1: 30 }, true)).toBe(21.4);
  });

  it("follows a swap", () => {
    const swapped = applyMove(two, { kind: "bench", playerId: "rb2" }, { kind: "slot", index: 1 });
    expect(projectedTotal(swapped, { qb1: 21.4, rb2: 9.15 }, true)).toBe(30.55);
  });

  it("is null when the week has no projections", () => {
    expect(projectedTotal(two, {}, false)).toBeNull();
  });
});

describe("lineupLoadProblem", () => {
  it("asks logged-out visitors to log in", () => {
    expect(lineupLoadProblem(401)).toEqual({ kind: "login" });
  });
  it("explains private leagues", () => {
    expect(lineupLoadProblem(403)).toEqual({ kind: "message", text: "This league is private. Only its members can see lineups." });
  });
  it("falls back to a retry message", () => {
    expect(lineupLoadProblem(null)).toEqual({ kind: "message", text: "Couldn't load this lineup. Try again in a moment." });
    expect(lineupLoadProblem(500).kind).toBe("message");
  });
});
