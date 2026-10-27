import { describe, expect, it, vi } from "vitest";
import {
  API_HEALTH_PATH,
  SYNC_STATUS_PATH,
  loadStatusReport,
  probe,
  statusFromProbes,
  updatedLabel,
  type Probe,
  type StatusReport,
} from "./status-page";

const NOW = Date.parse("2026-10-27T01:00:00.000Z");
const M = 60_000;

const ok = (body: unknown): Probe => ({ state: "ok", status: 200, body });
const http = (status: number, body: unknown = null): Probe => ({ state: "http", status, body });
const down: Probe = { state: "unreachable" };
const healthy = ok({ status: "healthy", app: "Fantasy Football Crew" });

function at(ms: number): string {
  return new Date(ms).toISOString();
}

function source(successAt: number | null, attemptOk: boolean | null = true) {
  return {
    last_success_at: successAt == null ? null : at(successAt),
    last_attempt_at: successAt == null ? null : at(successAt),
    last_attempt_ok: attemptOk,
  };
}

function syncBody(options?: {
  season_type?: string | null;
  sleeper?: ReturnType<typeof source>;
  espn?: ReturnType<typeof source>;
  generated_at?: string;
}) {
  return {
    generated_at: options?.generated_at ?? at(NOW),
    season_type: options?.season_type === undefined ? "regular" : options.season_type,
    sources: {
      sleeper: options?.sleeper ?? source(NOW - 30_000),
      espn: options?.espn ?? source(NOW - 45_000),
    },
  };
}

function report(health: Probe, sync: Probe): StatusReport {
  return statusFromProbes({ health, sync, now: NOW, locale: "en-US", timeZone: "UTC" });
}

function row(result: StatusReport, id: string) {
  const found = result.components.find((c) => c.id === id);
  if (!found) throw new Error(`missing ${id}`);
  return found;
}

describe("statusFromProbes", () => {
  it("is operational when the API is healthy and both syncs are fresh", () => {
    const result = report(healthy, ok(syncBody()));
    expect(result.level).toBe("operational");
    expect(result.headline).toBe("All systems operational");
    expect(result.summary).toBe("The API is responding, and Sleeper and ESPN data is current.");
    expect(row(result, "api")).toMatchObject({ level: "operational", label: "Operational", detail: "Responding" });
    expect(row(result, "sleeper").detail).toBe("Last sync 30s ago");
    expect(row(result, "espn")).toMatchObject({ level: "operational", detail: "Last sync 45s ago" });
  });

  it("goes degraded at 10 minutes, matching the freshness chip", () => {
    const fresh = report(healthy, ok(syncBody({ sleeper: source(NOW - 10 * M + 1) })));
    expect(row(fresh, "sleeper").level).toBe("operational");
    const stale = report(healthy, ok(syncBody({ sleeper: source(NOW - 10 * M) })));
    expect(row(stale, "sleeper")).toMatchObject({ level: "degraded", detail: "Last sync 10m ago" });
    expect(stale.level).toBe("degraded");
    expect(stale.headline).toBe("Some systems need attention");
    expect(stale.summary).toBe("The API is responding, but NFL data may be behind.");
  });

  it("treats a failed latest attempt as degraded even when the last success is recent", () => {
    const result = report(healthy, ok(syncBody({
      espn: { ...source(NOW - 4 * M), last_attempt_ok: false, last_attempt_at: at(NOW - 30_000) },
    })));
    expect(row(result, "espn")).toMatchObject({
      level: "degraded",
      detail: "Latest attempt failed. Last success 4m ago.",
    });
    expect(result.level).toBe("degraded");
  });

  it("says when a source has never succeeded", () => {
    const failed = report(healthy, ok(syncBody({ sleeper: source(null, false) })));
    expect(row(failed, "sleeper").detail).toBe("Latest attempt failed. No successful sync yet.");
    const none = report(healthy, ok(syncBody({ sleeper: source(null, null) })));
    expect(row(none, "sleeper")).toMatchObject({ level: "degraded", detail: "No sync recorded yet" });
  });

  it("pauses NFL sync outside the regular season without calling an old timestamp stale", () => {
    for (const season_type of ["pre", "post", "off"]) {
      const result = report(healthy, ok(syncBody({
        season_type,
        sleeper: source(NOW - 20_000),
        espn: source(NOW - 120 * 24 * 60 * M),
      })));
      expect(result.level).toBe("operational");
      expect(result.summary).toBe("The API is responding. NFL stat sync is paused outside the regular season.");
      expect(row(result, "sleeper").detail).toBe("Paused outside the regular season. Last check 20s ago.");
      expect(row(result, "espn")).toMatchObject({ level: "operational", detail: "Paused outside the regular season" });
    }
  });

  it("still flags a failed check while sync is paused", () => {
    const result = report(healthy, ok(syncBody({ season_type: "off", sleeper: source(NOW - 20_000, false) })));
    expect(row(result, "sleeper")).toMatchObject({
      level: "degraded",
      detail: "Paused outside the regular season. The last check failed.",
    });
    expect(result.summary).toContain("the last check failed");
  });

  it("shows ages when the season type is missing", () => {
    const result = report(healthy, ok(syncBody({ season_type: null })));
    expect(row(result, "sleeper").detail).toBe("Last sync 30s ago");
    expect(result.summary).not.toContain("paused");
  });

  it("is an outage when neither check answers", () => {
    const result = report(down, down);
    expect(result.level).toBe("outage");
    expect(result.headline).toBe("The platform is down");
    expect(row(result, "api")).toMatchObject({ level: "outage", detail: "Not responding" });
    expect(row(result, "sleeper")).toMatchObject({ level: "unknown", detail: "Couldn't check while the API is down" });
    expect(row(result, "espn").level).toBe("unknown");
  });

  it("is an outage when both endpoints return 5xx", () => {
    const result = report(http(503), http(503, { detail: "db timeout at secret-host.internal" }));
    expect(result.level).toBe("outage");
    expect(row(result, "sleeper").detail).toBe("Couldn't check while the API is down");
    expect(JSON.stringify(result)).not.toContain("secret-host");
  });

  it("keeps the API operational when health is clean and sync status is down", () => {
    const result = report(healthy, http(503));
    expect(row(result, "api")).toMatchObject({ level: "operational", detail: "Responding" });
    expect(row(result, "sleeper")).toMatchObject({ level: "degraded", detail: "Sync status is unavailable right now" });
    expect(result.level).toBe("degraded");
    expect(result.summary).toBe("The API is responding, but NFL sync status is unavailable.");
  });

  it("treats a sync-status payload as API up when the health alias is not deployed yet", () => {
    const result = report(http(404), ok(syncBody()));
    expect(row(result, "api").level).toBe("operational");
    expect(result.level).toBe("operational");
  });

  it("degrades when health fails but the sync endpoint still answers", () => {
    const missing = report(down, ok(syncBody()));
    expect(row(missing, "api")).toMatchObject({ level: "degraded", detail: "Responding, but the health check was not clean" });
    expect(missing.summary).toBe("The API answered, but the health check was not clean.");
    const errored = report(http(500), ok(syncBody({ sleeper: source(NOW - 30 * M) })));
    expect(errored.level).toBe("degraded");
    expect(errored.summary).toBe("The health check was not clean, and NFL data may be behind.");
  });

  it("does not treat a 200 with the wrong shape as healthy or as sync data", () => {
    const result = report(ok({ status: "starting" }), ok({ generated_at: at(NOW) }));
    expect(row(result, "api").level).toBe("degraded");
    expect(row(result, "espn").detail).toBe("Sync status is unavailable right now");
  });
});

describe("probe and loadStatusReport", () => {
  it("classifies a JSON success, an HTTP error, and a network failure", async () => {
    const fetchImpl = vi.fn(async (url: string) => {
      if (url.endsWith("ok")) return new Response(JSON.stringify({ status: "healthy" }), { status: 200 });
      if (url.endsWith("bad")) return new Response("nope", { status: 503 });
      throw new TypeError("Failed to fetch");
    }) as unknown as typeof fetch;
    expect(await probe("/ok", fetchImpl)).toEqual({ state: "ok", status: 200, body: { status: "healthy" } });
    expect(await probe("/bad", fetchImpl)).toEqual({ state: "http", status: 503, body: null });
    expect(await probe("/down", fetchImpl)).toEqual({ state: "unreachable" });
    expect(fetchImpl).toHaveBeenCalledWith("/ok", { credentials: "omit", cache: "no-store" });
  });

  it("reads health and sync-status through the /api proxy paths", async () => {
    const seen: string[] = [];
    const fetchImpl = vi.fn(async (url: string) => {
      seen.push(url);
      if (url === API_HEALTH_PATH) {
        return new Response(JSON.stringify({ status: "healthy", app: "Fantasy Football Crew" }), { status: 200 });
      }
      return new Response(JSON.stringify(syncBody()), { status: 200 });
    }) as unknown as typeof fetch;
    const result = await loadStatusReport({ fetchImpl, now: NOW, locale: "en-US", timeZone: "UTC" });
    expect(seen).toEqual([API_HEALTH_PATH, SYNC_STATUS_PATH]);
    expect(result.checkedAt).toBe(NOW);
    expect(result.report.level).toBe("operational");
  });
});

describe("updatedLabel", () => {
  it("reads as a relative time", () => {
    expect(updatedLabel(NOW, NOW, "en-US", "UTC")).toBe("Updated just now");
    expect(updatedLabel(NOW - 12_000, NOW, "en-US", "UTC")).toBe("Updated 12s ago");
  });
});
