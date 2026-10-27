// Public /status view model. Composes the existing liveness payload
// (GET /api/v1/health, the same body as Railway's GET /health) with
// GET /api/v1/nfl/sync-status. Stale means the same 10 minutes the
// in-app freshness chip uses. Outside the regular season the scheduler
// skips the stat pull, so a recent job row is a check, not new stats.

import { STALE_AFTER_MS, relativeAge, type SourceStatus, type SyncSource, type SyncStatus } from "./freshness";

export const API_HEALTH_PATH = "/api/v1/health";
export const SYNC_STATUS_PATH = "/api/v1/nfl/sync-status";

export type StatusLevel = "operational" | "degraded" | "outage";
export type ComponentLevel = StatusLevel | "unknown";

export type Probe =
  | { state: "ok"; status: number; body: unknown }
  | { state: "http"; status: number; body: unknown }
  | { state: "unreachable" };

export interface StatusComponent {
  id: "api" | SyncSource;
  name: string;
  level: ComponentLevel;
  label: string;
  detail: string;
}

export interface StatusReport {
  level: StatusLevel;
  headline: string;
  summary: string;
  components: StatusComponent[];
}

const LABEL: Record<ComponentLevel, string> = {
  operational: "Operational",
  degraded: "Degraded",
  outage: "Outage",
  unknown: "Unknown",
};

const PAUSED = new Set(["pre", "post", "off"]);

export async function probe(url: string, fetchImpl: typeof fetch = fetch): Promise<Probe> {
  try {
    const res = await fetchImpl(url, { credentials: "omit", cache: "no-store" });
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      body = null;
    }
    if (res.ok) return { state: "ok", status: res.status, body };
    return { state: "http", status: res.status, body };
  } catch {
    return { state: "unreachable" };
  }
}

export async function loadStatusReport(options?: {
  fetchImpl?: typeof fetch;
  now?: number;
  locale?: string;
  timeZone?: string;
}): Promise<{ report: StatusReport; checkedAt: number }> {
  const fetchImpl = options?.fetchImpl ?? fetch;
  const [health, sync] = await Promise.all([
    probe(API_HEALTH_PATH, fetchImpl),
    probe(SYNC_STATUS_PATH, fetchImpl),
  ]);
  const checkedAt = options?.now ?? Date.now();
  return {
    checkedAt,
    report: statusFromProbes({
      health,
      sync,
      now: checkedAt,
      locale: options?.locale,
      timeZone: options?.timeZone,
    }),
  };
}

export function statusFromProbes(input: {
  health: Probe;
  sync: Probe;
  now?: number;
  locale?: string;
  timeZone?: string;
}): StatusReport {
  const syncStatus = input.sync.state === "ok" ? asSyncStatus(input.sync.body) : null;
  const serverNow = syncStatus ? Date.parse(syncStatus.generated_at) : NaN;
  const now = Number.isFinite(serverNow) ? serverNow : (input.now ?? Date.now());
  const api = apiComponent(input.health, syncStatus != null);
  const paused = syncStatus != null && typeof syncStatus.season_type === "string" && PAUSED.has(syncStatus.season_type);

  const sleeper = syncComponent("sleeper", "Sleeper stats", syncStatus, paused, api.level, now, input.locale, input.timeZone);
  const espn = syncComponent("espn", "ESPN scores", syncStatus, paused, api.level, now, input.locale, input.timeZone);
  const components = [api, sleeper, espn];
  const syncDegraded = sleeper.level === "degraded" || espn.level === "degraded";
  const syncUnavailable = syncStatus == null && api.level !== "outage";

  let level: StatusLevel = "operational";
  if (api.level === "outage") level = "outage";
  else if (api.level === "degraded" || syncDegraded) level = "degraded";

  return {
    level,
    headline: headline(level),
    summary: summary(api.level, paused, syncDegraded, syncUnavailable),
    components,
  };
}

export function updatedLabel(checkedAt: number, now: number, locale?: string, timeZone?: string): string {
  return `Updated ${agePhrase(new Date(checkedAt), new Date(now), locale, timeZone)}`;
}

function headline(level: StatusLevel): string {
  if (level === "outage") return "The platform is down";
  if (level === "degraded") return "Some systems need attention";
  return "All systems operational";
}

function summary(api: ComponentLevel, paused: boolean, syncDegraded: boolean, syncUnavailable: boolean): string {
  if (api === "outage") {
    return "The API is not responding. Leagues and scores will not load until it is back.";
  }
  if (api === "degraded" && syncUnavailable) {
    return "The health check was not clean, and NFL sync status is unavailable.";
  }
  if (api === "degraded" && syncDegraded) {
    return "The health check was not clean, and NFL data may be behind.";
  }
  if (api === "degraded") {
    return "The API answered, but the health check was not clean.";
  }
  if (syncUnavailable) return "The API is responding, but NFL sync status is unavailable.";
  if (paused && syncDegraded) {
    return "The API is responding. NFL stat sync is paused outside the regular season, and the last check failed.";
  }
  if (paused) {
    return "The API is responding. NFL stat sync is paused outside the regular season.";
  }
  if (syncDegraded) return "The API is responding, but NFL data may be behind.";
  return "The API is responding, and Sleeper and ESPN data is current.";
}

function apiComponent(health: Probe, syncOk: boolean): StatusComponent {
  if (health.state === "ok" && healthStatus(health.body) === "healthy") {
    return component("api", "API", "operational", "Responding");
  }
  // Frontend can ship before the /api/v1/health alias. A real sync-status
  // payload still means this API process answered.
  if (health.state === "http" && health.status === 404 && syncOk) {
    return component("api", "API", "operational", "Responding");
  }
  const health5xx = health.state === "http" && health.status >= 500;
  const healthDown = health.state === "unreachable" || health5xx;
  if (healthDown && !syncOk) {
    return component("api", "API", "outage", "Not responding");
  }
  return component("api", "API", "degraded", "Responding, but the health check was not clean");
}

function syncComponent(
  id: SyncSource,
  name: string,
  status: SyncStatus | null,
  paused: boolean,
  apiLevel: ComponentLevel,
  now: number,
  locale?: string,
  timeZone?: string,
): StatusComponent {
  if (!status) {
    if (apiLevel === "outage") {
      return component(id, name, "unknown", "Couldn't check while the API is down");
    }
    return component(id, name, "degraded", "Sync status is unavailable right now");
  }
  const source = readSource(status.sources?.[id]);
  if (paused) return component(id, name, ...pausedSource(source, now, locale, timeZone));
  return component(id, name, ...liveSource(source, now, locale, timeZone));
}

function pausedSource(
  source: SourceStatus | null,
  now: number,
  locale?: string,
  timeZone?: string,
): [ComponentLevel, string] {
  if (source?.last_attempt_ok === false) {
    return ["degraded", "Paused outside the regular season. The last check failed."];
  }
  const successAt = timeOf(source?.last_success_at);
  if (successAt != null && now - successAt < STALE_AFTER_MS) {
    return ["operational", `Paused outside the regular season. Last check ${agePhrase(new Date(successAt), new Date(now), locale, timeZone)}.`];
  }
  return ["operational", "Paused outside the regular season"];
}

function liveSource(
  source: SourceStatus | null,
  now: number,
  locale?: string,
  timeZone?: string,
): [ComponentLevel, string] {
  const successAt = timeOf(source?.last_success_at);
  const failed = source?.last_attempt_ok === false;
  const ageText = successAt == null ? null : agePhrase(new Date(successAt), new Date(now), locale, timeZone);
  const fresh = successAt != null && now - successAt < STALE_AFTER_MS;
  if (failed && ageText) return ["degraded", `Latest attempt failed. Last success ${ageText}.`];
  if (failed) return ["degraded", "Latest attempt failed. No successful sync yet."];
  if (ageText && fresh) return ["operational", `Last sync ${ageText}`];
  if (ageText) return ["degraded", `Last sync ${ageText}`];
  return ["degraded", "No sync recorded yet"];
}

function component(id: StatusComponent["id"], name: string, level: ComponentLevel, detail: string): StatusComponent {
  return { id, name, level, label: LABEL[level], detail };
}

function healthStatus(body: unknown): string | null {
  if (!body || typeof body !== "object") return null;
  const status = (body as { status?: unknown }).status;
  return typeof status === "string" ? status : null;
}

function asSyncStatus(body: unknown): SyncStatus | null {
  if (!body || typeof body !== "object") return null;
  const record = body as Partial<SyncStatus>;
  if (!record.sources || typeof record.sources !== "object" || typeof record.generated_at !== "string") return null;
  return record as SyncStatus;
}

function readSource(value: SourceStatus | undefined): SourceStatus | null {
  if (!value || typeof value !== "object") return null;
  return {
    last_success_at: typeof value.last_success_at === "string" ? value.last_success_at : null,
    last_attempt_at: typeof value.last_attempt_at === "string" ? value.last_attempt_at : null,
    last_attempt_ok: typeof value.last_attempt_ok === "boolean" ? value.last_attempt_ok : null,
  };
}

function timeOf(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const ms = Date.parse(iso);
  return Number.isFinite(ms) ? ms : null;
}

function agePhrase(at: Date, now: Date, locale?: string, timeZone?: string): string {
  const rel = relativeAge(at, now, locale, timeZone);
  if (rel === "just now" || rel.startsWith("at ") || /^[A-Z]/.test(rel)) return rel;
  return `${rel} ago`;
}
