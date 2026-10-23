import { describe, expect, it } from "vitest";
import { chipState, relativeAge, type SyncStatus } from "./freshness";

const NOW = Date.parse("2026-10-22T02:42:00Z"); // Wed 7:42 PM PT
const tz = "America/Los_Angeles";
const ago = (ms: number) => new Date(NOW - ms).toISOString();
const S = 1000, M = 60 * S, H = 60 * M;

const status = (sleeper: Partial<SyncStatus["sources"]["sleeper"]>, espn?: Partial<SyncStatus["sources"]["espn"]>): SyncStatus => ({
  generated_at: new Date(NOW).toISOString(),
  sources: {
    sleeper: { last_success_at: null, last_attempt_at: null, last_attempt_ok: null, ...sleeper },
    ...(espn ? { espn: { last_success_at: null, last_attempt_at: null, last_attempt_ok: null, ...espn } } : {}),
  },
});

describe("relativeAge", () => {
  it.each([
    [0, "just now"],
    [4 * S, "just now"],
    [12 * S, "12s"],
    [59 * S, "59s"],
    [14 * M + 59 * S, "14m"],
    [5 * H + 59 * M, "5h"],
    [7 * H, "at 12:42 PM"],
    [20 * H, "Tue 11:42 PM"],
  ])("%i ms → %s", (ms, out) => {
    expect(relativeAge(new Date(NOW - ms), new Date(NOW), "en-US", tz)).toBe(out);
  });
});

describe("chipState", () => {
  const base = { now: NOW, locale: "en-US", timeZone: tz };

  it("is fresh under 10 minutes and ticks every second under a minute", () => {
    const c = chipState({ ...base, sources: ["sleeper"], status: status({ last_success_at: ago(12 * S), last_attempt_ok: true }) })!;
    expect(c).toMatchObject({
      kind: "fresh", text: "Synced 12s ago", suffix: "Sleeper", action: null, tickMs: 1000,
      ariaLabel: "Live data from Sleeper, synced 12 seconds ago",
    });
  });

  it("goes stale at 10 minutes with a Refresh action", () => {
    const c = chipState({ ...base, sources: ["sleeper"], status: status({ last_success_at: ago(14 * M), last_attempt_ok: true }) })!;
    expect(c.kind).toBe("stale");
    expect(c.text).toBe("Last synced 14m ago");
    expect(c.ariaLabel).toBe("Data from Sleeper may be out of date, last synced 14 minutes ago");
    expect(c.action).toEqual({ label: "Refresh", ariaLabel: "Refresh data from Sleeper" });
    expect(c.tickMs).toBe(30000);
    expect(chipState({ ...base, sources: ["sleeper"], status: status({ last_success_at: ago(10 * M - 1) }) })!.kind).toBe("fresh");
  });

  it.each([
    [7 * H, "Last synced at 12:42 PM"],
    [2 * H, "Last synced 2h ago"],
  ])("stale copy at %i ms", (ms, text) => {
    expect(chipState({ ...base, sources: ["sleeper"], status: status({ last_success_at: ago(ms) }) })!.text).toBe(text);
  });

  it("fails with the clock time of the data on screen and a Refresh", () => {
    const c = chipState({ ...base, sources: ["sleeper"], status: status({ last_success_at: ago(3 * M), last_attempt_ok: false }) })!;
    expect(c).toMatchObject({
      kind: "failed", text: "Sync failed", suffix: "showing 7:39 PM data",
      ariaLabel: "Sync failed. Showing data from 7:39 PM",
      action: { label: "Refresh", ariaLabel: "Refresh data from Sleeper" },
    });
  });

  it("names the one source that failed in a mixed view", () => {
    const c = chipState({
      ...base, sources: ["sleeper", "espn"],
      status: status({ last_success_at: ago(5 * S), last_attempt_ok: true }, { last_success_at: ago(3 * M), last_attempt_ok: false }),
    })!;
    expect(c.text).toBe("ESPN sync failed");
    expect(c.action?.ariaLabel).toBe("Refresh data from ESPN");
  });

  it("ages a mixed view by its oldest source", () => {
    const c = chipState({
      ...base, sources: ["sleeper", "espn"],
      status: status({ last_success_at: ago(5 * S) }, { last_success_at: ago(4 * M) }),
    })!;
    expect([c.text, c.suffix]).toEqual(["Synced 4m ago", "Sleeper + ESPN"]);
  });

  it("shows syncing over everything while a refresh is in flight", () => {
    const c = chipState({ ...base, sources: ["espn"], syncing: true, status: status({}, { last_success_at: ago(20 * M) }) })!;
    expect(c).toMatchObject({ kind: "syncing", text: "Syncing…", ariaLabel: "Syncing data from ESPN" });
  });

  it("fails when the browser's own refresh fails", () => {
    const c = chipState({ ...base, sources: ["sleeper"], clientFailed: true, status: status({ last_success_at: ago(1 * M) }) })!;
    expect(c.kind).toBe("failed");
  });

  it("renders nothing before the first sync", () => {
    expect(chipState({ ...base, sources: ["sleeper"], status: status({}) })).toBeNull();
    expect(chipState({ ...base, sources: ["sleeper"], status: null })).toBeNull();
  });

  it("ages by the page load when a newer sync hasn't been loaded", () => {
    const st = status({ last_success_at: ago(1 * M), last_attempt_ok: true });
    const loaded = chipState({ ...base, sources: ["sleeper"], status: st, dataAt: NOW - 14 * M })!;
    expect([loaded.kind, loaded.text]).toEqual(["stale", "Last synced 14m ago"]);
    const afterLoad = chipState({ ...base, sources: ["sleeper"], status: st, dataAt: NOW - 5 * S })!;
    expect(afterLoad.text).toBe("Synced 1m ago");
    // dataAt is browser time; a server clock 2m ahead shifts it to match.
    const skewed = chipState({ ...base, now: NOW - 2 * M, skewMs: 2 * M, sources: ["sleeper"], status: st, dataAt: NOW - 2 * M - 30 * S })!;
    expect(skewed.text).toBe("Synced 1m ago");
  });

  it("hides outside the regular season", () => {
    const st = { ...status({ last_success_at: ago(1 * M), last_attempt_ok: false }) };
    for (const season_type of ["pre", "post", "off"]) {
      expect(chipState({ ...base, sources: ["sleeper"], status: { ...st, season_type } })).toBeNull();
    }
    expect(chipState({ ...base, sources: ["sleeper"], status: { ...st, season_type: "regular" } })!.kind).toBe("failed");
    expect(chipState({ ...base, sources: ["sleeper"], status: { ...st, season_type: null } })!.kind).toBe("failed");
  });
});
