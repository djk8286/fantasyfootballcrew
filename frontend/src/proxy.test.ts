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

  it("off Vercel: a prod Host header doesn't reach prod, and no client IP or secret is sent", () => {
    env({ API_PROXY_SECRET: "local-copy-of-secret" });
    const r = run("http://192.168.1.50:3000/api/v1/auth/login", visitor);
    expect(r.rewrite).toBe(`${LOCAL_BACKEND}/api/v1/auth/login`);
    expect(r.fwd("cookie")).toBe(visitor.cookie);
    // The caller's own values are stripped, and none are added.
    expect(r.fwd("x-ffc-proxy-secret")).toBeNull();
    expect(r.fwd("x-ffc-client-ip")).toBeNull();
  });

  it("off Vercel with a copied VERCEL_ENV=production: still local", () => {
    env({ VERCEL_ENV: "production", API_PROXY_SECRET: "s" });
    const r = run("http://localhost:3000/api/v1/x", { ...visitor, host: "localhost:3000" });
    expect(r.rewrite).toBe(`${LOCAL_BACKEND}/api/v1/x`);
    expect(r.fwd("x-ffc-client-ip")).toBeNull();
  });

  it("an explicit API_PROXY_TARGET wins, local or on Vercel", () => {
    env({ API_PROXY_TARGET: "http://127.0.0.1:8011" });
    expect(run("http://localhost:3311/api/v1/x", { host: "localhost:3311" }).rewrite).toBe("http://127.0.0.1:8011/api/v1/x");
    env({ API_PROXY_TARGET: "https://staging.example", VERCEL: "1", VERCEL_ENV: "preview" });
    expect(run("https://p.vercel.app/api/v1/x", { host: "p.vercel.app" }).rewrite).toBe("https://staging.example/api/v1/x");
  });
});
