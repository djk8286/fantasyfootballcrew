"use client";

import { useEffect } from "react";
import Link from "next/link";
import { AlertTriangle, RotateCcw } from "lucide-react";

// Route-segment error boundary -- catches a render/runtime error anywhere
// in this page and everything below it, without taking Header/Footer (the
// root layout) down with it. Before this file existed, an unhandled error
// anywhere fell through to Next.js's built-in default error UI --
// functional, but generic and unbranded rather than matching the rest of
// the app. Reported to Sentry automatically via instrumentation-client.ts's
// onRequestError hook -- no explicit capture call needed here.
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="min-h-[60vh] flex items-center justify-center px-4">
      <div className="max-w-md w-full text-center">
        <div className="w-14 h-14 mx-auto mb-4 rounded-2xl bg-red-500/10 border border-red-500/30 flex items-center justify-center">
          <AlertTriangle className="w-7 h-7 text-red-400" />
        </div>
        <h1 className="text-xl font-bold text-white mb-2">Something went wrong</h1>
        <p className="text-surface-400 text-sm mb-6">
          This page hit an unexpected error. It&apos;s been logged -- try again,
          or head back to the dashboard.
        </p>
        <div className="flex items-center justify-center gap-3">
          <button
            onClick={reset}
            className="inline-flex items-center gap-1.5 bg-gold-400 hover:bg-gold-300 text-surface-900 px-5 py-2.5 rounded-xl font-semibold text-sm transition-all"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            Try Again
          </button>
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-1.5 border border-surface-600 hover:border-gold-400/50 text-surface-300 hover:text-gold-400 px-5 py-2.5 rounded-xl font-semibold text-sm transition-all"
          >
            Dashboard
          </Link>
        </div>
      </div>
    </div>
  );
}
