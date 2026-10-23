import Link from "next/link";
import { AlertTriangle, RefreshCw, Trophy } from "lucide-react";

/**
 * The standings page when its first load fails. The page header stays
 * (the league nav comes from LeagueShell above it) and the error sits in
 * the content area, so the visitor keeps their bearings and can retry.
 */
export default function StandingsUnavailable({
  leagueId,
  leagueName,
  message,
  onRetry,
}: {
  leagueId: string;
  leagueName?: string | null;
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="min-h-screen bg-surface-900">
      <section className="relative overflow-hidden border-b border-surface-700">
        <div className="absolute inset-0 bg-gradient-to-b from-surface-850 via-surface-900 to-surface-900" />
        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 md:py-10">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gold-400/10 border border-gold-400/20 flex items-center justify-center">
              <Trophy className="w-5 h-5 text-gold-400" aria-hidden="true" />
            </div>
            <div>
              <h1 className="text-2xl md:text-3xl font-bold text-white tracking-tight">Standings</h1>
              {leagueName && <p className="text-surface-400 text-sm">{leagueName}</p>}
            </div>
          </div>
        </div>
      </section>

      <section className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-6">
        <div role="alert" className="flex flex-col gap-3 rounded-2xl border border-red-500/30 bg-red-500/10 p-4 sm:flex-row sm:items-center">
          <AlertTriangle className="h-5 w-5 shrink-0 text-red-400" aria-hidden="true" />
          <div className="flex-1">
            <p className="text-sm font-semibold text-white">Couldn&apos;t load standings</p>
            <p className="text-sm text-surface-300">{message}</p>
          </div>
          <div className="flex items-center gap-3">
            {onRetry && (
              <button
                type="button"
                onClick={onRetry}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-surface-600 px-3 py-2 text-sm text-surface-200 hover:border-surface-500 hover:text-white"
              >
                <RefreshCw className="h-4 w-4" aria-hidden="true" />
                Try again
              </button>
            )}
            <Link href={`/leagues/${leagueId}`} className="text-sm font-medium text-gold-400 hover:text-gold-300">
              Back to league
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}
