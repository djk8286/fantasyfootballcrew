import { AlertTriangle, CheckCircle2, HelpCircle, RefreshCw, XCircle } from "lucide-react";
import type { ComponentLevel, StatusReport as StatusReportModel } from "@/lib/status-page";

const TONE: Record<ComponentLevel, { banner: string; text: string; pill: string }> = {
  operational: {
    banner: "border-green-400/30 bg-green-400/10",
    text: "text-green-400",
    pill: "text-green-400 bg-green-400/10 border-green-400/30",
  },
  degraded: {
    banner: "border-amber-400/40 bg-amber-400/10",
    text: "text-amber-400",
    pill: "text-amber-400 bg-amber-400/10 border-amber-400/30",
  },
  outage: {
    banner: "border-red-500/40 bg-red-500/10",
    text: "text-red-400",
    pill: "text-red-400 bg-red-500/10 border-red-500/30",
  },
  unknown: {
    banner: "border-surface-600 bg-surface-800/60",
    text: "text-surface-300",
    pill: "text-surface-300 bg-surface-700/40 border-surface-600",
  },
};

function LevelIcon({ level }: { level: ComponentLevel }) {
  const className = `w-5 h-5 mt-0.5 shrink-0 ${TONE[level].text}`;
  if (level === "operational") return <CheckCircle2 className={className} aria-hidden="true" />;
  if (level === "degraded") return <AlertTriangle className={className} aria-hidden="true" />;
  if (level === "outage") return <XCircle className={className} aria-hidden="true" />;
  return <HelpCircle className={className} aria-hidden="true" />;
}

export default function StatusReport({
  report,
  checkedLabel,
  onRefresh,
  refreshing,
}: {
  report: StatusReportModel;
  checkedLabel: string | null;
  onRefresh: () => void;
  refreshing: boolean;
}) {
  const tone = TONE[report.level];
  return (
    <>
      <div
        className={`rounded-2xl border p-4 sm:p-5 ${tone.banner}`}
        data-level={report.level}
        role="status"
        aria-live="polite"
      >
        <div className="flex items-start gap-3">
          <LevelIcon level={report.level} />
          <div className="min-w-0">
            <h2 className={`text-lg sm:text-xl font-bold ${tone.text}`}>{report.headline}</h2>
            <p className="text-surface-300 text-sm mt-1 leading-relaxed">{report.summary}</p>
          </div>
        </div>
      </div>

      <ul className="space-y-3" aria-label="Components">
        {report.components.map((component) => {
          const pill = TONE[component.level].pill;
          return (
            <li
              key={component.id}
              data-component={component.id}
              data-level={component.level}
              className="bg-surface-800/60 border border-surface-700 rounded-2xl p-4 sm:p-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="min-w-0">
                <h3 className="text-white font-semibold text-sm">{component.name}</h3>
                <p className="text-surface-400 text-sm mt-1 leading-relaxed">{component.detail}</p>
              </div>
              <span className={`inline-flex self-start sm:self-center shrink-0 items-center px-2.5 py-1 rounded-md border text-xs font-bold uppercase tracking-wider ${pill}`}>
                {component.label}
              </span>
            </li>
          );
        })}
      </ul>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-surface-500 text-xs sm:text-sm">
          {checkedLabel ?? "Not checked yet"}
          <span className="text-surface-600"> · Refreshes about once a minute.</span>
        </p>
        <button
          type="button"
          onClick={onRefresh}
          disabled={refreshing}
          aria-busy={refreshing || undefined}
          className="inline-flex items-center justify-center gap-2 min-h-11 px-4 rounded-lg text-sm font-semibold text-surface-200 hover:text-white bg-surface-800 border border-surface-700 disabled:opacity-50 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold-400"
        >
          <RefreshCw className={`w-4 h-4 ${refreshing ? "animate-spin" : ""}`} aria-hidden="true" />
          Refresh
        </button>
      </div>
    </>
  );
}
