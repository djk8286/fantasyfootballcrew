import { describe, expect, it } from "vitest";
import { chipState, type SyncStatus } from "./freshness";
import { applyStandingsLoad, EMPTY_SNAPSHOT, fetchStandings, type StandingsSnapshot } from "./standingsSnapshot";

const NOW = Date.parse("2026-10-22T02:42:00Z");
const M = 60_000;

describe("fetchStandings", () => {
  const ok = { getTeams: async () => [{ id: 1 }], getStandings: async () => ({ standings: [{ team_id: 1 }], guillotine: null }) };

  it("returns teams, rows, the summary and when the load started", async () => {
    const r = await fetchStandings(ok, "7", () => 123);
    expect(r).toEqual({ teams: [{ id: 1 }], entries: [{ team_id: 1 }], guillotine: null, at: 123 });
  });

  it.each([
    ["teams fail", { ...ok, getTeams: async () => { throw new Error("502"); } }],
    ["standings fail", { ...ok, getStandings: async () => { throw new Error("502"); } }],
    ["standings body is null", { ...ok, getStandings: async () => null }],
    ["standings has no rows array", { ...ok, getStandings: async () => ({ standings: "nope" }) }],
    ["teams is not a list", { ...ok, getTeams: async () => ({}) }],
  ])("rejects when %s instead of returning an empty table", async (_label, api) => {
    await expect(fetchStandings(api, "7")).rejects.toThrow();
  });
});

describe("applyStandingsLoad", () => {
  const prev: StandingsSnapshot<string> = { rows: ["a", "b"], guillotine: null, at: NOW - 14 * M, refreshFailed: false };

  it("keeps the old rows and load time when the reload fails", () => {
    expect(applyStandingsLoad(prev, null)).toEqual({ ...prev, refreshFailed: true });
  });

  it("replaces everything and clears the failure on success", () => {
    const failed = { ...prev, refreshFailed: true };
    expect(applyStandingsLoad(failed, { rows: ["c"], guillotine: null, at: NOW })).toEqual({
      rows: ["c"], guillotine: null, at: NOW, refreshFailed: false,
    });
  });

  it("shows new rows but keeps the old time when the rest of the reload fails", () => {
    expect(applyStandingsLoad(prev, { rows: ["c"], guillotine: null, at: NOW }, true)).toEqual({
      rows: ["c"], guillotine: null, at: prev.at, refreshFailed: true,
    });
  });

  it("a failed first reload stays empty with no load time", () => {
    expect(applyStandingsLoad(EMPTY_SNAPSHOT, null)).toEqual({ rows: [], guillotine: null, at: undefined, refreshFailed: true });
  });

  it("never lets the chip read just now after a failed reload", () => {
    // A sync landed seconds ago, but the reload that would show it failed.
    const status: SyncStatus = {
      generated_at: new Date(NOW).toISOString(),
      sources: { sleeper: { last_success_at: new Date(NOW - 5_000).toISOString(), last_attempt_at: null, last_attempt_ok: true } },
    };
    const snap = applyStandingsLoad(prev, null);
    const c = chipState({
      now: NOW, locale: "en-US", timeZone: "America/Los_Angeles", sources: ["sleeper"], status,
      dataAt: snap.at, clientFailed: snap.refreshFailed,
    })!;
    expect(c.kind).toBe("failed");
    expect(c.text).toBe("Sync failed");
    expect(c.suffix).toBe("showing 7:28 PM data");
    expect(JSON.stringify(c)).not.toMatch(/just now/);
  });
});
