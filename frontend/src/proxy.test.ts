import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { LOCAL_BACKEND, PROD_BACKEND } from "@/lib/proxy-target";
import { proxy } from "./proxy";

const FWD = "x-middleware-request-";

function run(url: string, headers: Record<string, string>) {
  const res = proxy(new NextRequest(url, { headers }));
  return {
    rewrite: res.headers.get("x-middleware-rewrite"),
    fwd: (name: string) => res.headers.get(FWD + name),
  };
}

const visitor = {
  host: "fantasyfootballcrew.com",
  cookie: "ffc_session=abc; ffc_refresh=def",
  "x-real-ip": "203.0.113.77",
  "x-forwarded-for": "203.0.113.77, 10.0.0.1",
  // A caller trying to set these itself.
  "x-ffc-proxy-secret": "guessed",
  "x-ffc-client-ip": "1.1.1.1",
};

describe("proxy()", () => {
  afterEach(() => vi.unstubAllEnvs());

  function env(vars: Record<string, string>) {
    for (const k of ["API_PROXY_TARGET", "VERCEL", "VERCEL_ENV", "API_PROXY_SECRET"]) vi.stubEnv(k, vars[k] ?? "");
  }

  it("on a Vercel production deploy: rewrites to prod and forwards cookie, secret and the edge's client IP", () => {
    env({ VERCEL: "1", VERCEL_ENV: "production", API_PROXY_SECRET: "real-secret" });
    const r = run("https://fantasyfootballcrew.com/api/v1/leagues?x=1", visitor);
    expect(r.rewrite).toBe(`${PROD_BACKEND}/api/v1/leagues?x=1`);
    expect(r.fwd("cookie")).toBe(visitor.cookie);
    expect(r.fwd("x-ffc-proxy-secret")).toBe("real-secret");
    expect(r.fwd("x-ffc-client-ip")).toBe("203.0.113.77");
    expect(r.fwd("host")).toBeNull();
  });

  it("on a Vercel preview deploy: still prod for now", () => {
    env({ VERCEL: "1", VERCEL_ENV: "preview", API_PROXY_SECRET: "real-secret" });
    const r = run("https://fantasyfootballcrew-abc123-the-crew2.vercel.app/api/v1/me", { ...visitor, host: "fantasyfootballcrew-abc123-the-crew2.vercel.app" });
    expect(r.rewrite).toBe(`${PROD_BACKEND}/api/v1/me`);
    expect(r.fwd("x-ffc-client-ip")).toBe("203.0.113.77");
  });

  it("off Vercel with no secret: a prod Host header doesn't reach prod, and no client IP or secret is sent", () => {
    env({});
    const r = run("http://192.168.1.50:3000/api/v1/auth/login", visitor);
    expect(r.rewrite).toBe(`${LOCAL_BACKEND}/api/v1/auth/login`);
    expect(r.fwd("cookie")).toBe(visitor.cookie);
    // The caller's own values are stripped, and none are added.
    expect(r.fwd("x-ffc-proxy-secret")).toBeNull();
    expect(r.fwd("x-ffc-client-ip")).toBeNull();
  });

  it("off Vercel with a copied VERCEL_ENV=production: still local", () => {
    env({ VERCEL_ENV: "production" });
    const r = run("http://localhost:3000/api/v1/x", { ...visitor, host: "localhost:3000" });
    expect(r.rewrite).toBe(`${LOCAL_BACKEND}/api/v1/x`);
    expect(r.fwd("x-ffc-client-ip")).toBeNull();
  });

  it("API_PROXY_SECRET set but VERCEL !== '1': fails closed with a 503 and logs one error", async () => {
    // Fresh module so the log-once flag starts clear.
    vi.resetModules();
    const { proxy: freshProxy } = await import("./proxy");
    const err = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      const cases: Record<string, string>[] = [
        { API_PROXY_SECRET: "real-secret", VERCEL_ENV: "production" },
        { API_PROXY_SECRET: "real-secret", VERCEL: "true", VERCEL_ENV: "production" },
        { API_PROXY_SECRET: "real-secret", API_PROXY_TARGET: PROD_BACKEND },
        { API_PROXY_SECRET: "real-secret" },
      ];
      for (const c of cases) {
        env(c);
        const res = freshProxy(new NextRequest("https://fantasyfootballcrew.com/api/v1/leagues", { headers: visitor }));
        expect(res.status).toBe(503);
        expect(res.headers.get("x-middleware-rewrite")).toBeNull();
        expect(await res.json()).toEqual({ detail: "Service unavailable" });
      }
      expect(err).toHaveBeenCalledTimes(1);
      expect(String(err.mock.calls[0][0])).toContain("API_PROXY_SECRET is set but VERCEL");
      expect(String(err.mock.calls[0][0])).not.toContain("real-secret");
    } finally {
      err.mockRestore();
    }
  });

  it("on Vercel, an explicit target that isn't the prod backend gets neither the secret nor the client IP", () => {
    env({ VERCEL: "1", VERCEL_ENV: "preview", API_PROXY_SECRET: "real-secret", API_PROXY_TARGET: "https://someone-tunnel.trycloudflare.com" });
    const r = run("https://fantasyfootballcrew-abc123-the-crew2.vercel.app/api/v1/me", { ...visitor, host: "fantasyfootballcrew-abc123-the-crew2.vercel.app" });
    expect(r.rewrite).toBe("https://someone-tunnel.trycloudflare.com/api/v1/me");
    expect(r.fwd("cookie")).toBe(visitor.cookie);
    expect(r.fwd("x-ffc-proxy-secret")).toBeNull();
    expect(r.fwd("x-ffc-client-ip")).toBeNull();
  });

  it("on Vercel, a lookalike host or different scheme/port isn't the prod backend", () => {
    for (const t of [
      "https://fantasyfootballcrew-production.up.railway.app.evil.example",
      "http://fantasyfootballcrew-production.up.railway.app",
      "https://fantasyfootballcrew-production.up.railway.app:8443",
    ]) {
      env({ VERCEL: "1", VERCEL_ENV: "production", API_PROXY_SECRET: "real-secret", API_PROXY_TARGET: t });
      const r = run("https://fantasyfootballcrew.com/api/v1/x", visitor);
      expect(r.fwd("x-ffc-proxy-secret")).toBeNull();
      expect(r.fwd("x-ffc-client-ip")).toBeNull();
    }
  });

  it("on Vercel, an explicit target equal to the prod backend (with a path or trailing slash) still gets them", () => {
    env({ VERCEL: "1", VERCEL_ENV: "production", API_PROXY_SECRET: "real-secret", API_PROXY_TARGET: `${PROD_BACKEND}/` });
    const r = run("https://fantasyfootballcrew.com/api/v1/x", visitor);
    expect(r.rewrite).toBe(`${PROD_BACKEND}/api/v1/x`);
    expect(r.fwd("x-ffc-proxy-secret")).toBe("real-secret");
    expect(r.fwd("x-ffc-client-ip")).toBe("203.0.113.77");
  });

  it("vercel dev (VERCEL=1, development) goes local and sends neither", () => {
    env({ VERCEL: "1", VERCEL_ENV: "development", API_PROXY_SECRET: "real-secret" });
    const r = run("http://localhost:3000/api/v1/x", { ...visitor, host: "localhost:3000" });
    expect(r.rewrite).toBe(`${LOCAL_BACKEND}/api/v1/x`);
    expect(r.fwd("x-ffc-proxy-secret")).toBeNull();
    expect(r.fwd("x-ffc-client-ip")).toBeNull();
  });

  it("an explicit API_PROXY_TARGET wins, local or on Vercel", () => {
    env({ API_PROXY_TARGET: "http://127.0.0.1:8011" });
    expect(run("http://localhost:3311/api/v1/x", { host: "localhost:3311" }).rewrite).toBe("http://127.0.0.1:8011/api/v1/x");
    env({ API_PROXY_TARGET: "https://staging.example", VERCEL: "1", VERCEL_ENV: "preview" });
    expect(run("https://p.vercel.app/api/v1/x", { host: "p.vercel.app" }).rewrite).toBe("https://staging.example/api/v1/x");
  });
});
