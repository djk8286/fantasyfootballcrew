// Data-freshness chip state. Pure, so the ticker and the copy are testable.

export type SyncSource = "sleeper" | "espn";
export type ChipKind = "fresh" | "syncing" | "stale" | "failed";

export interface SourceStatus {
  last_success_at: string | null;
  last_attempt_at: string | null;
  last_attempt_ok: boolean | null;
}

export interface SyncStatus {
  generated_at: string;
  /** Sleeper's season_type: "pre" | "regular" | "post" | "off", or null
   * when the backend couldn't read it. Syncs only pull stats in the
   * regular season. */
  season_type?: string | null;
  sources: Partial<Record<SyncSource, SourceStatus>>;
}

export const STALE_AFTER_MS = 10 * 60 * 1000;
const SOURCE_NAME: Record<SyncSource, string> = { sleeper: "Sleeper", espn: "ESPN" };

export interface ChipInput {
  now: number;
  status: SyncStatus | null;
  sources: SyncSource[];
  /** A refresh the user asked for is in flight. */
  syncing?: boolean;
  /** The user's last refresh failed in the browser. */
  clientFailed?: boolean;
  /** When the page last loaded its data (ms). The page can't be newer
   * than that, so the age is taken from the older of this and the sync. */
  dataAt?: number;
  /** Clock skew between server and browser, in ms (server minus client). */
  skewMs?: number;
  locale?: string;
  timeZone?: string;
}

export interface ChipState {
  kind: ChipKind;
  /** Visible text, e.g. "Synced 12s ago". */
  text: string;
  /** Muted suffix after " · ": the source, or "showing 7:42 PM data". */
  suffix: string;
  ariaLabel: string;
  action: { label: string; ariaLabel: string } | null;
  /** Milliseconds until the visible text next changes. */
  tickMs: number;
}

function clock(d: Date, locale?: string, timeZone?: string): string {
  return d.toLocaleTimeString(locale ?? "en-US", { hour: "numeric", minute: "2-digit", timeZone });
}

function sameDay(a: Date, b: Date, timeZone?: string): boolean {
  const f = (d: Date) => d.toLocaleDateString("en-CA", { timeZone });
  return f(a) === f(b);
}

/** "just now", "12s", "3m", "2h", "at 1:05 PM", "Sun 7:42 PM". */
export function relativeAge(at: Date, now: Date, locale?: string, timeZone?: string): string {
  const s = Math.max(0, Math.floor((now.getTime() - at.getTime()) / 1000));
  if (s < 5) return "just now";
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 6 * 3600) return `${Math.floor(s / 3600)}h`;
  if (sameDay(at, now, timeZone)) return `at ${clock(at, locale, timeZone)}`;
  const day = at.toLocaleDateString(locale ?? "en-US", { weekday: "short", timeZone });
  return `${day} ${clock(at, locale, timeZone)}`;
}

/** The same age in words, for screen readers. */
export function spokenAge(at: Date, now: Date, locale?: string, timeZone?: string): string {
  const s = Math.max(0, Math.floor((now.getTime() - at.getTime()) / 1000));
  const unit = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"} ago`;
  if (s < 5) return "just now";
  if (s < 60) return unit(s, "second");
  if (s < 3600) return unit(Math.floor(s / 60), "minute");
  if (s < 6 * 3600) return unit(Math.floor(s / 3600), "hour");
  const rel = relativeAge(at, now, locale, timeZone);
  return rel.startsWith("at ") ? rel : `on ${rel}`;
}

function withAgo(rel: string): string {
  return rel === "just now" || rel.startsWith("at ") || /^[A-Z]/.test(rel) ? rel : `${rel} ago`;
}

export function chipState(input: ChipInput): ChipState | null {
  const { status, sources } = input;
  const now = new Date(input.now + (input.skewMs ?? 0));
  const entries = sources.map((s) => ({ source: s, st: status?.sources[s] }));
  const known = entries.filter((e) => e.st?.last_success_at);
  const sourceLabel = sources.map((s) => SOURCE_NAME[s]).join(" + ");

  // Outside the regular season the syncs skip their work but still log
  // a success, so a "Synced 2m ago" chip would be wrong. Hide it.
  if (status?.season_type && status.season_type !== "regular") return null;

  // The oldest source decides the age: the page is only as fresh as its slowest feed.
  let oldest = known.reduce<Date | null>((m, e) => {
    const d = new Date(e.st!.last_success_at!);
    return m == null || d < m ? d : m;
  }, null);
  // A sync after the page loaded isn't on screen yet. The data shown is
  // at least as old as the load. dataAt is browser time, so shift it by
  // the skew to compare with server times.
  if (oldest && input.dataAt != null) {
    const loaded = new Date(input.dataAt + (input.skewMs ?? 0));
    if (loaded < oldest) oldest = loaded;
  }

  const failedSources = entries.filter((e) => e.st?.last_attempt_ok === false).map((e) => e.source);
  const failed = input.clientFailed || failedSources.length > 0;

  if (input.syncing) {
    return {
      kind: "syncing",
      text: "Syncing…",
      suffix: sourceLabel,
      ariaLabel: `Syncing data from ${sourceLabel}`,
      action: null,
      tickMs: 1000,
    };
  }
  if (!oldest && !failed) return null;

  const age = oldest ? now.getTime() - oldest.getTime() : Infinity;
  const tickMs = age < 60_000 ? 1000 : 30_000;

  if (failed) {
    const who =
      failedSources.length === 1 && sources.length > 1 ? `${SOURCE_NAME[failedSources[0]]} sync failed` : "Sync failed";
    const at = oldest ? clock(oldest, input.locale, input.timeZone) : null;
    const when = oldest && !sameDay(oldest, now, input.timeZone)
      ? relativeAge(oldest, now, input.locale, input.timeZone)
      : at;
    const retrySource = failedSources.length === 1 ? SOURCE_NAME[failedSources[0]] : sourceLabel;
    return {
      kind: "failed",
      text: who,
      suffix: when ? `showing ${when} data` : "",
      ariaLabel: when ? `${who}. Showing data from ${when}` : `${who}. No data synced yet`,
      action: { label: "Refresh", ariaLabel: `Refresh data from ${retrySource}` },
      tickMs,
    };
  }

  const rel = relativeAge(oldest!, now, input.locale, input.timeZone);
  const spoken = spokenAge(oldest!, now, input.locale, input.timeZone);
  if (age >= STALE_AFTER_MS) {
    return {
      kind: "stale",
      text: `Last synced ${withAgo(rel)}`,
      suffix: sourceLabel,
      ariaLabel: `Data from ${sourceLabel} may be out of date, last synced ${spoken}`,
      action: { label: "Refresh", ariaLabel: `Refresh data from ${sourceLabel}` },
      tickMs,
    };
  }
  return {
    kind: "fresh",
    text: rel === "just now" ? "Synced just now" : `Synced ${rel} ago`,
    suffix: sourceLabel,
    ariaLabel: `Live data from ${sourceLabel}, synced ${spoken}`,
    action: null,
    tickMs,
  };
}
