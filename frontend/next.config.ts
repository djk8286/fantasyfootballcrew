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

// Google AdSense (see src/components/AdSlot.tsx) -- gated on the same
// env var that gates whether AdSlot renders anything at all, so this
// widened CSP is completely inert (byte-for-byte the same policy as
// before AdSlot existed) unless/until NEXT_PUBLIC_ADSENSE_CLIENT_ID is
// actually set. AdSense needs script-src for its loader, frame-src for
// the sandboxed iframe each ad creative actually renders inside,
// connect-src for its own ad-request calls, and img-src for fallback
// image ads -- all scoped to Google's ad-serving domains specifically,
// not a blanket googlesyndication wildcard grant to the rest of the CSP.
const ADS_ENABLED = !!process.env.NEXT_PUBLIC_ADSENSE_CLIENT_ID;
const ADSENSE_SCRIPT_SRC = " https://pagead2.googlesyndication.com https://www.googletagservices.com";
const ADSENSE_FRAME_SRC = " https://googleads.g.doubleclick.net https://tpc.googlesyndication.com https://www.google.com";
const ADSENSE_CONNECT_SRC = " https://pagead2.googlesyndication.com https://googleads.g.doubleclick.net";
const ADSENSE_IMG_SRC = " https://pagead2.googlesyndication.com https://googleads.g.doubleclick.net";

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
  `script-src 'self' 'unsafe-inline'${ADS_ENABLED ? ADSENSE_SCRIPT_SRC : ""}`,
  // Tailwind/Next's runtime style injection needs inline styles -- this
  // is the standard, common exception for style-src, unlike script-src.
  "style-src 'self' 'unsafe-inline'",
  // sleepercdn.com: PlayerAvatar.tsx loads Sleeper headshots via a raw
  // <img> (see backend's sleeper_avatar_url()), not next/image, so it's
  // a real cross-origin image load, not just the remotePatterns config.
  `img-src 'self' data: https://sleepercdn.com${ADS_ENABLED ? ADSENSE_IMG_SRC : ""}`,
  "font-src 'self' data:",
  // supabase.co: the Supabase client exists (src/lib/supabase.ts) but
  // isn't actually wired to any auth flow yet -- included now so turning
  // it on later doesn't also require remembering to update this policy.
  `connect-src 'self' ${API_ORIGIN} https://*.supabase.co https://*.sentry.io${ADS_ENABLED ? ADSENSE_CONNECT_SRC : ""}`,
  // No frame-src before AdSense -- this app has never embedded anything
  // in an iframe, so it fell back to default-src 'self' (fine, since
  // nothing needed otherwise). AdSense's actual ad creative renders
  // inside a sandboxed cross-origin iframe, which needs an explicit
  // allowance here.
  `frame-src 'self'${ADS_ENABLED ? ADSENSE_FRAME_SRC : ""}`,
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