"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { loadStatusReport, updatedLabel, type StatusReport as StatusReportModel } from "@/lib/status-page";
import StatusReport from "./StatusReport";

const POLL_MS = 60_000;
const LABEL_TICK_MS = 15_000;

export default function StatusBoard() {
  const [report, setReport] = useState<StatusReportModel | null>(null);
  const [checkedAt, setCheckedAt] = useState<number | null>(null);
  const [now, setNow] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const gen = useRef(0);

  const load = useCallback(async () => {
    const mine = ++gen.current;
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const locale = typeof navigator !== "undefined" ? navigator.language : undefined;
    const result = await loadStatusReport({ locale, timeZone: zone });
    if (mine !== gen.current) return;
    setCheckedAt(result.checkedAt);
    setNow(result.checkedAt);
    setReport(result.report);
  }, []);

  useEffect(() => {
    let id: ReturnType<typeof setInterval> | null = null;
    const poll = () => { void load(); };
    const start = () => {
      if (id != null) return;
      poll();
      id = setInterval(poll, POLL_MS);
    };
    const stop = () => {
      if (id != null) clearInterval(id);
      id = null;
    };
    const onVisibility = () => (document.hidden ? stop() : start());
    if (!document.hidden) start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      gen.current += 1;
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [load]);

  useEffect(() => {
    if (checkedAt == null) return;
    const id = setInterval(() => setNow(Date.now()), LABEL_TICK_MS);
    return () => clearInterval(id);
  }, [checkedAt]);

  const refresh = () => {
    setRefreshing(true);
    void load().finally(() => setRefreshing(false));
  };

  return (
    <div>
      <section className="relative overflow-hidden border-b border-surface-700">
        <div className="absolute inset-0 bg-gradient-to-b from-surface-850 via-surface-900 to-surface-900" />
        <div className="relative max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-12 sm:py-16">
          <h1 className="text-3xl md:text-4xl font-bold text-white mb-3">System status</h1>
          <p className="text-surface-400 text-sm sm:text-base max-w-xl leading-relaxed">
            Whether the site is up, and when Sleeper and ESPN data last synced.
          </p>
        </div>
      </section>

      <section className="py-10 sm:py-14 bg-surface-850">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 space-y-6">
          {report ? (
            <StatusReport
              report={report}
              checkedLabel={checkedAt != null && now != null ? updatedLabel(checkedAt, now) : null}
              onRefresh={refresh}
              refreshing={refreshing}
            />
          ) : (
            <p className="text-surface-400 text-sm" role="status">
              Checking the API and the NFL sync.
            </p>
          )}
        </div>
      </section>
    </div>
  );
}
