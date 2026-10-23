import { describe, expect, it } from "vitest";
import { LOCAL_BACKEND, PROD_BACKEND, isProdBackend, onVercel, resolveProxyTarget } from "./proxy-target";

describe("resolveProxyTarget", () => {
  it("never sends a non-Vercel run to prod by default", () => {
    expect(resolveProxyTarget({})).toEqual({ target: LOCAL_BACKEND, source: "local" });
    expect(resolveProxyTarget({ API_PROXY_TARGET: "  " }).target).toBe(LOCAL_BACKEND);
    // `vercel env pull` writes VERCEL=1 with VERCEL_ENV=development.
    expect(resolveProxyTarget({ VERCEL: "1", VERCEL_ENV: "development" }).target).toBe(LOCAL_BACKEND);
    // A copied VERCEL_ENV without VERCEL=1 is not a Vercel deploy.
    expect(resolveProxyTarget({ VERCEL_ENV: "production" }).target).toBe(LOCAL_BACKEND);
    expect(resolveProxyTarget({ VERCEL_ENV: "preview" }).target).toBe(LOCAL_BACKEND);
    expect(resolveProxyTarget({ VERCEL: "true", VERCEL_ENV: "production" }).target).toBe(LOCAL_BACKEND);
  });

  it("uses API_PROXY_TARGET whenever it is set", () => {
    expect(resolveProxyTarget({ API_PROXY_TARGET: "http://127.0.0.1:8011" }))
      .toEqual({ target: "http://127.0.0.1:8011", source: "explicit" });
    expect(resolveProxyTarget({ API_PROXY_TARGET: "https://staging.example", VERCEL: "1", VERCEL_ENV: "production" }).target)
      .toBe("https://staging.example");
  });

  it("keeps Vercel production and preview deploys on the prod backend", () => {
    expect(resolveProxyTarget({ VERCEL: "1", VERCEL_ENV: "production" })).toEqual({ target: PROD_BACKEND, source: "vercel" });
    expect(resolveProxyTarget({ VERCEL: "1", VERCEL_ENV: "preview" })).toEqual({ target: PROD_BACKEND, source: "vercel" });
  });

  it("only counts VERCEL=1 as Vercel", () => {
    expect(onVercel({ VERCEL: "1" })).toBe(true);
    for (const v of [undefined, "", "0", "true"]) expect(onVercel({ VERCEL: v })).toBe(false);
  });

  it("isProdBackend matches the prod origin only", () => {
    expect(isProdBackend(PROD_BACKEND)).toBe(true);
    expect(isProdBackend(`${PROD_BACKEND}/`)).toBe(true);
    expect(isProdBackend(`${PROD_BACKEND}/api`)).toBe(true);
    for (const t of [
      LOCAL_BACKEND,
      "https://someone-tunnel.trycloudflare.com",
      "https://fantasyfootballcrew-production.up.railway.app.evil.example",
      "http://fantasyfootballcrew-production.up.railway.app",
      "https://fantasyfootballcrew-production.up.railway.app:8443",
      "not a url",
      "",
    ]) expect(isProdBackend(t)).toBe(false);
  });
});
