/**
 * Where src/proxy.ts sends /api/* requests.
 *
 * The prod backend is only a default on real Vercel deploys. A local
 * `next build && next start` runs with NODE_ENV=production too, and it
 * used to fall back to the prod backend silently, so a local screenshot
 * or test run could read (or write) live data. Now anything that isn't a
 * Vercel deploy goes to localhost unless API_PROXY_TARGET says otherwise.
 *
 * Order:
 *   1. API_PROXY_TARGET, when set, always wins.
 *   2. Vercel production or preview (VERCEL_ENV) uses the prod backend.
 *      Previews have always proxied to prod; this keeps them working
 *      whether or not the Preview environment sets API_PROXY_TARGET.
 *   3. The request came in on a host only Vercel serves for this project
 *      (fantasyfootballcrew.com or a fantasyfootballcrew-*.vercel.app
 *      deploy URL). This covers a deploy with Vercel's system env vars
 *      turned off, so prod can't drop to localhost.
 *   4. Everything else: http://localhost:8001.
 */
export const PROD_BACKEND = "https://fantasyfootballcrew-production.up.railway.app";
export const LOCAL_BACKEND = "http://localhost:8001";

const VERCEL_HOST = /^(?:www\.)?fantasyfootballcrew\.com$|^fantasyfootballcrew-[a-z0-9-]+\.vercel\.app$/i;

export type ProxyTargetSource = "explicit" | "vercel" | "vercel-host" | "local";

export function resolveProxyTarget(
  env: { API_PROXY_TARGET?: string; VERCEL_ENV?: string },
  host?: string | null,
): { target: string; source: ProxyTargetSource } {
  const explicit = env.API_PROXY_TARGET?.trim();
  if (explicit) return { target: explicit, source: "explicit" };
  if (env.VERCEL_ENV === "production" || env.VERCEL_ENV === "preview") return { target: PROD_BACKEND, source: "vercel" };
  const bare = host?.split(":")[0] ?? "";
  if (VERCEL_HOST.test(bare)) return { target: PROD_BACKEND, source: "vercel-host" };
  return { target: LOCAL_BACKEND, source: "local" };
}
