import { NextResponse, type NextRequest } from "next/server";
import { resolveProxyTarget } from "@/lib/proxy-target";

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
 *                     real visitor instead of Vercel's shared egress IP.
 */
let warnedLocal = false;

function visitorIp(request: NextRequest): string | null {
  // On Vercel these are set by Vercel's edge from the TCP peer (client-sent
  // values are overwritten), so they're trustworthy here -- unlike at Railway.
  const real = request.headers.get("x-real-ip")?.trim();
  if (real) return real;
  const xff = request.headers.get("x-forwarded-for");
  return xff ? xff.split(",")[0].trim() || null : null;
}

export function proxy(request: NextRequest) {
  const { target, source } = resolveProxyTarget(
    { API_PROXY_TARGET: process.env.API_PROXY_TARGET, VERCEL_ENV: process.env.VERCEL_ENV },
    request.headers.get("host"),
  );
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
  const secret = process.env.API_PROXY_SECRET;
  const ip = visitorIp(request);
  if (secret && ip) {
    headers.set("x-ffc-proxy-secret", secret);
    headers.set("x-ffc-client-ip", ip);
  }
  return NextResponse.rewrite(dest, { request: { headers } });
}

export const config = { matcher: "/api/:path*" };
