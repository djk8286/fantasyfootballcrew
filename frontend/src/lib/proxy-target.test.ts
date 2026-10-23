import { describe, expect, it } from "vitest";
import { LOCAL_BACKEND, PROD_BACKEND, resolveProxyTarget } from "./proxy-target";

describe("resolveProxyTarget", () => {
  it("never sends a local run to prod by default", () => {
    expect(resolveProxyTarget({}, "localhost:3000")).toEqual({ target: LOCAL_BACKEND, source: "local" });
    expect(resolveProxyTarget({}, "127.0.0.1:3311").target).toBe(LOCAL_BACKEND);
    expect(resolveProxyTarget({}, null).target).toBe(LOCAL_BACKEND);
    expect(resolveProxyTarget({ VERCEL_ENV: "development" }, "localhost:3000").target).toBe(LOCAL_BACKEND);
    expect(resolveProxyTarget({ API_PROXY_TARGET: "  " }, "localhost:3000").target).toBe(LOCAL_BACKEND);
  });

  it("uses API_PROXY_TARGET whenever it is set", () => {
    expect(resolveProxyTarget({ API_PROXY_TARGET: "http://127.0.0.1:8011" }, "localhost:3311"))
      .toEqual({ target: "http://127.0.0.1:8011", source: "explicit" });
    expect(resolveProxyTarget({ API_PROXY_TARGET: "https://staging.example", VERCEL_ENV: "production" }, "fantasyfootballcrew.com").target)
      .toBe("https://staging.example");
  });

  it("keeps Vercel production and preview deploys on the prod backend", () => {
    expect(resolveProxyTarget({ VERCEL_ENV: "production" }, "fantasyfootballcrew.com")).toEqual({ target: PROD_BACKEND, source: "vercel" });
    expect(resolveProxyTarget({ VERCEL_ENV: "preview" }, "fantasyfootballcrew-js3u3i3dg-the-crew2.vercel.app").target).toBe(PROD_BACKEND);
  });

  it("still reaches prod on this project's Vercel hosts if VERCEL_ENV is missing", () => {
    for (const host of ["fantasyfootballcrew.com", "www.fantasyfootballcrew.com", "fantasyfootballcrew-g1hhxr9bm-the-crew2.vercel.app"]) {
      expect(resolveProxyTarget({}, host)).toEqual({ target: PROD_BACKEND, source: "vercel-host" });
    }
  });

  it("does not treat look-alike hosts as Vercel", () => {
    for (const host of ["fantasyfootballcrew.com.evil.test", "evilfantasyfootballcrew.com", "fantasyfootballcrew-x.vercel.app.evil.test"]) {
      expect(resolveProxyTarget({}, host).target).toBe(LOCAL_BACKEND);
    }
  });
});
