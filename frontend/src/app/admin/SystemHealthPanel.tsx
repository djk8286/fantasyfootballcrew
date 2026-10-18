"use client";

import { Activity, AlertTriangle, CheckCircle2, Clock, Database, RefreshCw, Timer } from "lucide-react";

export interface SystemHealthJob {
  name: string;
  label: string;
  status: "ok" | "stale" | "failed" | "never_run";
  stale_after_seconds: number | null;
  last_run_at: string | null;
  last_duration_ms: number | null;
  last_success_at: string | null;
  last_failure_at: string | null;
  last_error: string | null;
  runs_24h: number;
  failures_24h: number;
}

interface Freshness {
  updated_at: string | null;
  age_seconds: number | null;
}

export interface SystemHealth {
  generated_at: string;
  jobs: SystemHealthJob[];
  freshness: { espn_games: Freshness; sleeper_players: Freshness; sleeper_stats: Freshness };
  draft_timer: {
    status: SystemHealthJob["status"];
    last_tick_at: string | null;
    in_progress_drafts: number;
    timed_drafts: number;
    overdue_drafts: { draft_id: string; league_id: string; seconds_overdue: number }[];
  };
}

// How many jobs need attention -- drives the tab badge on the page.
export function countUnhealthy(health: SystemHealth | null): number {
  if (!health) return 0;
  return health.jobs.filter((j) => j.status === "failed" || j.status === "stale").length
    + (health.draft_timer.overdue_drafts.length > 0 ? 1 : 0);
}

const STATUS_STYLE: Record<SystemHealthJob["status"], { label: string; className: string }> = {
  ok: { label: "OK", className: "text-green-400 bg-green-400/10 border-green-400/30" },
  stale: { label: "Stale", className: "text-amber-400 bg-amber-400/10 border-amber-400/30" },
  failed: { label: "Failed", className: "text-red-400 bg-red-400/10 border-red-400/30" },
  never_run: { label: "Not run yet", className: "text-surface-400 bg-surface-700/40 border-surface-600" },
};

function StatusPill({ status }: { status: SystemHealthJob["status"] }) {
  const s = STATUS_STYLE[status];
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded border text-[10px] font-bold uppercase tracking-wider ${s.className}`}>
      {s.label}
    </span>
  );
}

function fmtAgo(iso: string | null, nowMs: number): string {
  if (!iso) return "never";
  const s = Math.max(0, Math.round((nowMs - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

function FreshnessTile({ label, value, warnAfterSeconds, nowMs }: { label: string; value: Freshness; warnAfterSeconds: number; nowMs: number }) {
  const stale = value.age_seconds == null || value.age_seconds > warnAfterSeconds;
  return (
    <div className={`bg-surface-800/60 border rounded-xl p-4 ${stale ? "border-amber-400/40" : "border-surface-700"}`}>
      <p className="text-surface-400 text-xs flex items-center gap-1.5">
        <Database className="w-3.5 h-3.5" /> {label}
      </p>
      <p className={`text-lg font-bold mt-1 ${stale ? "text-amber-400" : "text-white"}`}>{fmtAgo(value.updated_at, nowMs)}</p>
      {value.updated_at && <p className="text-surface-500 text-[11px] mt-0.5">{new Date(value.updated_at).toLocaleString()}</p>}
    </div>
  );
}

export default function SystemHealthPanel({
  health, error, onRefresh, refreshing,
}: {
  health: SystemHealth | null;
  error: string | null;
  onRefresh: () => void;
  refreshing: boolean;
}) {
  if (error) {
    return (
      <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm" role="alert">
        Couldn&apos;t load system health: {error}
      </div>
    );
  }
  if (!health) {
    return <p className="text-surface-500 text-sm">Loading system health...</p>;
  }

  // Ages are computed against the server's own clock at generation time,
  // so a skewed browser clock can't make everything look stale.
  const nowMs = new Date(health.generated_at).getTime();
  const unhealthy = countUnhealthy(health);
  const dt = health.draft_timer;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className={`flex items-center gap-2 text-sm font-semibold ${unhealthy ? "text-amber-400" : "text-green-400"}`}>
          {unhealthy ? <AlertTriangle className="w-4 h-4" /> : <CheckCircle2 className="w-4 h-4" />}
          {unhealthy ? `${unhealthy} item${unhealthy === 1 ? "" : "s"} need attention` : "All background jobs healthy"}
        </div>
        <button
          onClick={onRefresh}
          disabled={refreshing}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold text-surface-300 hover:text-white bg-surface-800 border border-surface-700 disabled:opacity-50 transition-colors"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? "animate-spin" : ""}`} /> Refresh
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <FreshnessTile label="Sleeper stats" value={health.freshness.sleeper_stats} warnAfterSeconds={15 * 60} nowMs={nowMs} />
        <FreshnessTile label="Sleeper players" value={health.freshness.sleeper_players} warnAfterSeconds={3 * 3600} nowMs={nowMs} />
        <FreshnessTile label="ESPN games" value={health.freshness.espn_games} warnAfterSeconds={24 * 3600} nowMs={nowMs} />
      </div>

      <div className={`bg-surface-800/60 border rounded-2xl p-4 ${dt.status === "failed" || dt.status === "stale" || dt.overdue_drafts.length ? "border-red-500/40" : "border-surface-700"}`}>
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <h3 className="text-white font-bold text-sm flex items-center gap-2">
            <Timer className="w-4 h-4 text-gold-400" /> Draft Timer Watchdog
          </h3>
          <StatusPill status={dt.status} />
        </div>
        <p className="text-surface-400 text-xs mt-2">
          Last tick {fmtAgo(dt.last_tick_at, nowMs)} · {dt.in_progress_drafts} draft{dt.in_progress_drafts === 1 ? "" : "s"} in progress ({dt.timed_drafts} timed)
        </p>
        {dt.overdue_drafts.length > 0 && (
          <ul className="mt-2 space-y-1">
            {dt.overdue_drafts.map((d) => (
              <li key={d.draft_id} className="text-red-400 text-xs flex items-center gap-1.5">
                <AlertTriangle className="w-3 h-3" /> Draft {d.draft_id.slice(0, 8)} pick is {Math.round(d.seconds_overdue / 60)}m past its deadline
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="bg-surface-800/60 border border-surface-700 rounded-2xl overflow-hidden overflow-x-auto">
        <table className="w-full text-sm min-w-[760px]">
          <thead>
            <tr className="border-b border-surface-700 text-left text-surface-400 text-xs uppercase tracking-wider">
              <th className="px-4 py-3 font-medium">Job</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">Last Success</th>
              <th className="px-4 py-3 font-medium">Last Failure</th>
              <th className="px-4 py-3 font-medium text-right">Runs / Fails (24h)</th>
              <th className="px-4 py-3 font-medium text-right">Last Duration</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-700/60">
            {health.jobs.map((j) => (
              <tr key={j.name} className={j.status === "failed" ? "bg-red-500/5" : j.status === "stale" ? "bg-amber-400/5" : ""}>
                <td className="px-4 py-3">
                  <span className="text-white font-medium flex items-center gap-1.5">
                    <Activity className="w-3.5 h-3.5 text-surface-500" /> {j.label}
                  </span>
                  <span className="block text-surface-500 text-[11px] font-mono">{j.name}</span>
                  {j.last_error && (
                    <span className="block text-red-400/90 text-[11px] mt-1 break-all" title={j.last_error}>
                      {j.last_error.length > 160 ? `${j.last_error.slice(0, 160)}…` : j.last_error}
                    </span>
                  )}
                </td>
                <td className="px-4 py-3"><StatusPill status={j.status} /></td>
                <td className="px-4 py-3 text-surface-300 text-xs">
                  <span className="inline-flex items-center gap-1"><Clock className="w-3 h-3 text-surface-500" />{fmtAgo(j.last_success_at, nowMs)}</span>
                </td>
                <td className={`px-4 py-3 text-xs ${j.last_failure_at ? "text-red-400" : "text-surface-500"}`}>{fmtAgo(j.last_failure_at, nowMs)}</td>
                <td className="px-4 py-3 text-right text-xs">
                  <span className="text-surface-300">{j.runs_24h}</span>
                  <span className="text-surface-600"> / </span>
                  <span className={j.failures_24h ? "text-red-400 font-semibold" : "text-surface-500"}>{j.failures_24h}</span>
                </td>
                <td className="px-4 py-3 text-right text-surface-400 text-xs">
                  {j.last_duration_ms == null ? "—" : j.last_duration_ms < 1000 ? `${j.last_duration_ms}ms` : `${(j.last_duration_ms / 1000).toFixed(1)}s`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
