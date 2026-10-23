/**
 * Where src/proxy.ts sends /api/* requests, and whether it may trust the
 * platform's client-IP header.
 *
 * The prod backend is only a default on real Vercel deploys. A local
 * `next build && next start` runs with NODE_ENV=production too, and it
 * used to fall back to the prod backend silently, so a local screenshot
 * or test run could read (or write) live data. Now anything that isn't a
 * Vercel deploy goes to localhost unless API_PROXY_TARGET says otherwise.
 *
 * Order:
 *   1. API_PROXY_TARGET, when set, always wins.
 *   2. A Vercel production or preview deploy (VERCEL === "1" and
 *      VERCEL_ENV is "production" or "preview") uses the prod backend.
 *      Previews have always proxied to prod; that stays until there is a
 *      staging backend. Both variables are Vercel system env vars, so the
 *      project must keep "Automatically expose System Environment
 *      Variables" on, or set API_PROXY_TARGET.
 *   3. Everything else: http://localhost:8001.
 *
 * Nothing here reads the request's Host header. Anyone can send any Host,
 * so it can't decide where traffic goes.
 */
export const PROD_BACKEND = "https://fantasyfootballcrew-production.up.railway.app";
export const LOCAL_BACKEND = "http://localhost:8001";

export interface ProxyEnv {
  API_PROXY_TARGET?: string;
  VERCEL?: string;
  VERCEL_ENV?: string;
}

export type ProxyTargetSource = "explicit" | "vercel" | "local";

/** Running on Vercel's own infrastructure. */
export function onVercel(env: ProxyEnv): boolean {
  return env.VERCEL === "1";
}

export function resolveProxyTarget(env: ProxyEnv): { target: string; source: ProxyTargetSource } {
  const explicit = env.API_PROXY_TARGET?.trim();
  if (explicit) return { target: explicit, source: "explicit" };
  if (onVercel(env) && (env.VERCEL_ENV === "production" || env.VERCEL_ENV === "preview")) {
    return { target: PROD_BACKEND, source: "vercel" };
  }
  return { target: LOCAL_BACKEND, source: "local" };
}
