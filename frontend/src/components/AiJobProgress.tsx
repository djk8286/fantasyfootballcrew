import { Loader2 } from "lucide-react";

/** In-page status while a background AI job runs. The only signal used to
 * be a small spinner inside the dimmed Analyze button, which QA read as
 * "no loading state" for the 20-40 s a run takes. */
export default function AiJobProgress({ seconds, label = "Analyzing your lineup" }: { seconds: number; label?: string }) {
  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="ai-job-progress"
      className="mt-6 flex items-start gap-3 rounded-2xl border border-gold-400/30 bg-gold-400/5 p-4 text-sm text-surface-200"
    >
      <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-gold-400" aria-hidden />
      <div>
        <p className="font-medium text-white">
          {label}… <span className="tabular-nums text-surface-400">{seconds}s</span>
        </p>
        <p className="mt-0.5 text-xs text-surface-400">
          This usually takes 20–40 seconds. You can leave this page; the result shows here (and under Recent) when it&apos;s ready.
        </p>
      </div>
    </div>
  );
}
