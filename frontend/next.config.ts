import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs";

// The backend origin every page fetches from (src/lib/api-client.ts calls
// it directly with an absolute URL -- the rewrite below is dev-only,
// nothing in the app actually issues a relative /api/* fetch that would
// hit it). Derived from the same env var the app itself uses rather than
// hand-duplicating the Railway URL, so this can't silently drift out of
// sync with the real backend if that ever changes; falls back to the
// current production URL only so a misconfigured build doesn't ship with
// zero connect-src for its own API and break outright.
const API_ORIGIN =
  process.env.NEXT_PUBLIC_API_URL || "https://fantasyfootballcrew-production.up.railway.app";

const CSP = [
  "default-src 'self'",
  // 'unsafe-inline' here isn't a shortcut -- verified empirically (see
  // the commit this landed in) that this Next.js version's own hydration
  // bootstrap uses inline <script> tags directly (not exclusively
  // external /_next/static chunks the way a nonce/hash-based policy
  // assumes), so a bare 'self' broke every single page. A real
  // nonce-based policy is the "correct" fix but needs per-request
  // middleware this Next version's exact API surface hasn't been
  // verified for (see frontend/AGENTS.md's breaking-changes warning) --
  // not worth the live-site-breaking risk to chase right now, especially
  // since the app has no dangerouslySetInnerHTML anywhere (verified via
  // grep), so React's own escaping already covers the main thing a
  // strict script-src would otherwise buy.
  "script-src 'self' 'unsafe-inline'",
  // Tailwind/Next's runtime style injection needs inline styles -- this
  // is the standard, common exception for style-src, unlike script-src.
  "style-src 'self' 'unsafe-inline'",
  // sleepercdn.com: PlayerAvatar.tsx loads Sleeper headshots via a raw
  // <img> (see backend's sleeper_avatar_url()), not next/image, so it's
  // a real cross-origin image load, not just the remotePatterns config.
  `img-src 'self' data: https://sleepercdn.com`,
  "font-src 'self' data:",
  // supabase.co: the Supabase client exists (src/lib/supabase.ts) but
  // isn't actually wired to any auth flow yet -- included now so turning
  // it on later doesn't also require remembering to update this policy.
  `connect-src 'self' ${API_ORIGIN} https://*.supabase.co https://*.sentry.io`,
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

const nextConfig: NextConfig = {
  trailingSlash: false,
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "**.sleeper.com",
      },
    ],
  },
  // Proxy API requests to the backend during dev & production
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8001/api/:path*",
      },
    ];
  },
  // Production only -- `next dev`'s Fast Refresh relies on inline
  // eval'd scripts and a websocket connection a strict CSP would block,
  // and there's no real security boundary to defend on localhost anyway.
  async headers() {
    if (process.env.NODE_ENV !== "production") return [];
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: CSP },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "geolocation=(), microphone=(), camera=()" },
          { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" },
        ],
      },
    ];
  },
  output: "standalone",
};

// org/project/authToken are all unset -- that's fine, it just means source
// maps don't get uploaded (stack traces in Sentry will show minified code
// instead of the original source). Error capture itself is unaffected;
// see src/instrumentation-client.ts and src/instrumentation.ts. Uploading
// source maps later just needs SENTRY_ORG/SENTRY_PROJECT/SENTRY_AUTH_TOKEN
// added as env vars, no code changes.
export default withSentryConfig(nextConfig, {
  silent: true,
  telemetry: false,
});