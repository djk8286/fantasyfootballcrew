"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { nflApi } from "@/lib/api-client";
import { chipState, type ChipKind, type SyncSource, type SyncStatus } from "@/lib/freshness";
import { FfcIcon } from "./icons";

const SYNCING_AFTER_MS = 400;
const POLL_MS = 60_000;

const KIND_CLASS: Record<ChipKind, string> = {
  fresh: "bg-ffc-live/10 border-ffc-live/35",
  syncing: "bg-ffc-live/10 border-ffc-live/35",
  stale: "bg-ffc-warn/10 border-ffc-warn/45",
  failed: "bg-ffc-error/12 border-ffc-error/55",
};
const ACTION_CLASS: Record<ChipKind, string> = {
  fresh: "text-ffc-live",
  syncing: "text-ffc-live",
  stale: "text-ffc-warn",
  failed: "text-ffc-error",
};

/**
 * Data-freshness chip. Reads the backend's last-sync timestamps, ticks the
 * age locally, and runs `onRefresh` from its Refresh/Retry button.
 */
export default function FreshnessChip({
  sources,
  onRefresh,
  live = false,
  className = "",
}: {
  sources: SyncSource[];
  /** Reloads the page's data. Rejecting marks the chip failed. */
  onRefresh?: () => Promise<unknown>;
  /** Games are in progress: the fresh dot pulses. */
  live?: boolean;
  className?: string;
}) {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [skewMs, setSkewMs] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const [syncing, setSyncing] = useState(false);
  const [clientFailed, setClientFailed] = useState(false);
  const inFlight = useRef(false);

  const loadStatus = useCallback(async () => {
    const s = await nflApi.getSyncStatus();
    setStatus(s);
    setSkewMs(new Date(s.generated_at).getTime() - Date.now());
    setNow(Date.now());
    return s;
  }, []);

  useEffect(() => {
    loadStatus().catch(() => setClientFailed(true));
    const id = setInterval(() => loadStatus().catch(() => setClientFailed(true)), POLL_MS);
    return () => clearInterval(id);
  }, [loadStatus]);

  const state = chipState({ now, status, sources, syncing, clientFailed, skewMs });

  useEffect(() => {
    if (!state) return;
    const id = setTimeout(() => setNow(Date.now()), state.tickMs);
    return () => clearTimeout(id);
  }, [now, state]);

  // Announce state changes only, never the ticking age.
  const [announced, setAnnounced] = useState<{ kind: ChipKind | null; label: string }>({ kind: null, label: "" });
  useEffect(() => {
    if (state && state.kind !== announced.kind) setAnnounced({ kind: state.kind, label: state.ariaLabel });
  }, [state, announced.kind]);

  const refresh = async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    const timer = setTimeout(() => setSyncing(true), SYNCING_AFTER_MS);
    try {
      await Promise.all([onRefresh?.(), loadStatus()]);
      setClientFailed(false);
    } catch {
      setClientFailed(true);
    } finally {
      clearTimeout(timer);
      setSyncing(false);
      inFlight.current = false;
    }
  };

  if (!state) return null;

  const icon =
    state.kind === "fresh" ? (
      <span className="relative inline-flex h-4 w-4 items-center justify-center" aria-hidden="true">
        {live && <span className="ffc-halo-pulse absolute inset-1 rounded-full bg-ffc-live" />}
        <span className="relative h-2 w-2 rounded-full bg-ffc-live" />
      </span>
    ) : state.kind === "syncing" ? (
      <FfcIcon name="refresh" size={14} className="ffc-spin text-ffc-live" />
    ) : state.kind === "stale" ? (
      <FfcIcon name="clock" size={14} className="text-ffc-warn" />
    ) : (
      <FfcIcon name="alert" size={14} className="text-ffc-error" />
    );

  return (
    <div
      className={`ffc-chip inline-flex h-8 max-w-full items-center rounded-full border pl-3 pr-3 font-ffc-ui text-[13px] leading-[18px] ${KIND_CLASS[state.kind]} ${className}`}
      data-kind={state.kind}
    >
      <span
        role="status"
        aria-live="polite"
        aria-busy={state.kind === "syncing" || undefined}
        aria-label={announced.kind === state.kind ? announced.label : state.ariaLabel}
        className="inline-flex min-w-0 items-center gap-2"
      >
        {icon}
        <span aria-hidden="true" className="min-w-0 truncate">
          <span className="font-medium text-ffc-text">{state.text}</span>
          {state.suffix && <span className="ffc-chip-suffix text-ffc-text-muted"> · {state.suffix}</span>}
        </span>
      </span>
      {state.action && (
        <>
          <span className="mx-2.5 h-4 w-px shrink-0 bg-current opacity-30" aria-hidden="true" />
          <button
            type="button"
            onClick={refresh}
            aria-label={state.action.ariaLabel}
            className={`relative inline-flex shrink-0 items-center gap-1.5 font-semibold ${ACTION_CLASS[state.kind]} rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ffc-focus after:absolute after:left-1/2 after:top-1/2 after:h-11 after:w-11 after:min-w-full after:-translate-x-1/2 after:-translate-y-1/2 after:content-['']`}
          >
            <FfcIcon name="refresh" size={14} />
            {state.action.label}
          </button>
        </>
      )}
    </div>
  );
}

