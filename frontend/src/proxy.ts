import { NextResponse, type NextRequest } from "next/server";
import { isProdBackend, onVercel, resolveProxyTarget, type ProxyEnv } from "@/lib/proxy-target";

/**
 * First-party API proxy: the browser calls same-origin /api/* on
 * fantasyfootballcrew.com and this forwards it to the Railway backend, so
 * the HttpOnly auth cookies the backend sets are first-party cookies on
 * this site (no SameSite=None / third-party-cookie / Safari ITP issues).
 *
 * Server-only env (never NEXT_PUBLIC_):
 *   API_PROXY_TARGET  backend origin. Unset, it's prod Railway on Vercel deploys
 *                     and localhost:8001 everywhere else, including a local
 *                     production build (see src/lib/proxy-target.ts).
 *   API_PROXY_SECRET  shared with backend PROXY_SHARED_SECRET; authenticates
 *                     X-FFC-Client-IP so the backend rate limiter keys on the
 *                     real visitor instead of Vercel's shared egress IP. Sent
 *                     only to the prod backend origin, and only on Vercel.
 *                     If it is set but VERCEL !== "1", /api fails closed with
 *                     a 503 rather than quietly dropping the visitor IP.
 */
let warnedLocal = false;
let warnedSecretOffVercel = false;

function visitorIp(request: NextRequest, env: ProxyEnv): string | null {
  // Only Vercel's edge sets these from the TCP peer (client-sent values are
  // overwritten). Anywhere else a caller can type any IP into them, and
  // Next's proxy has no socket address to use instead, so send none.
  if (!onVercel(env)) return null;
  const real = request.headers.get("x-real-ip")?.trim();
  if (real) return real;
  const xff = request.headers.get("x-forwarded-for");
  return xff ? xff.split(",")[0].trim() || null : null;
}

export function proxy(request: NextRequest) {
  const env: ProxyEnv = {
    API_PROXY_TARGET: process.env.API_PROXY_TARGET,
    VERCEL: process.env.VERCEL,
    VERCEL_ENV: process.env.VERCEL_ENV,
  };
  const secret = process.env.API_PROXY_SECRET?.trim();
  if (secret && !onVercel(env)) {
    // The secret only lives in Vercel's env scopes. Seeing it without
    // VERCEL=1 means the system env vars aren't exposed, so the visitor IP
    // can't be trusted or forwarded and the backend would rate-limit every
    // visitor as one address. Refuse instead of degrading silently.
    if (!warnedSecretOffVercel) {
      warnedSecretOffVercel = true;
      console.error(
        '[proxy] API_PROXY_SECRET is set but VERCEL !== "1". Refusing to proxy /api (503). ' +
          'Turn on "Automatically expose System Environment Variables" for the Vercel project, ' +
          "or unset API_PROXY_SECRET for local runs.",
      );
    }
    return NextResponse.json({ detail: "Service unavailable" }, { status: 503 });
  }
  const { target, source } = resolveProxyTarget(env);
  if (source === "local" && process.env.NODE_ENV === "production" && !warnedLocal) {
    warnedLocal = true;
    console.warn(`[proxy] API_PROXY_TARGET is not set and this is not a Vercel deploy; sending /api to ${target}`);
  }
  const dest = new URL(request.nextUrl.pathname + request.nextUrl.search, target);

  const headers = new Headers(request.headers);
  // Never let a caller supply these itself.
  headers.delete("x-ffc-proxy-secret");
  headers.delete("x-ffc-client-ip");
  // Railway routes on Host; the destination URL determines it.
  headers.delete("host");
  const ip = visitorIp(request, env);
  if (secret && ip && isProdBackend(target)) {
    headers.set("x-ffc-proxy-secret", secret);
    headers.set("x-ffc-client-ip", ip);
  }
  return NextResponse.rewrite(dest, { request: { headers } });
}

export const config = { matcher: "/api/:path*" };
