import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs";

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