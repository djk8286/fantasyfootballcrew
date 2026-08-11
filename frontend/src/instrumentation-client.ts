// Client-side error monitoring. Next.js's own file convention (stable
// since 15.3) -- runs after the HTML loads, before React hydrates.
//
// Sentry.init() with no dsn is a documented no-op: nothing gets sent,
// nothing breaks. Same deferred-but-ready shape as the backend's
// app/core/sentry.py -- ships now, activates the moment
// NEXT_PUBLIC_SENTRY_DSN is set, no other code changes needed.
import * as Sentry from "@sentry/nextjs";

Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  environment: process.env.NODE_ENV,
  tracesSampleRate: 0.1,
  sendDefaultPii: false,
});

export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
