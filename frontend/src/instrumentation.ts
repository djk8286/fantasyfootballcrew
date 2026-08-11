// Server + edge error monitoring. Next.js's own file convention (stable
// since 15.0) -- register() runs once per server instance startup,
// onRequestError() captures errors from Server Components, Route
// Handlers, Server Actions, and proxying.
//
// Sentry.init() with no dsn is a documented no-op. See
// src/instrumentation-client.ts for the client-side half of this.
import * as Sentry from "@sentry/nextjs";

export async function register() {
  const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;
  if (process.env.NEXT_RUNTIME === "nodejs") {
    Sentry.init({ dsn, environment: process.env.NODE_ENV, tracesSampleRate: 0.1 });
  } else if (process.env.NEXT_RUNTIME === "edge") {
    Sentry.init({ dsn, environment: process.env.NODE_ENV, tracesSampleRate: 0.1 });
  }
}

export const onRequestError = Sentry.captureRequestError;
