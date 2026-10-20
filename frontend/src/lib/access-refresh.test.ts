import { describe, expect, it } from "vitest";
import { accessLikelyExpired } from "./api-client";

describe("proactive access refresh (QA 2026-10-19 BUG J)", () => {
  const now = 1_000_000_000;
  it("doesn't refresh a freshly issued access cookie", () => {
    expect(accessLikelyExpired(String(now - 60_000), now)).toBe(false);
  });
  it("refreshes before sending once the cookie is ~15 min old", () => {
    expect(accessLikelyExpired(String(now - 14 * 60_000 - 1), now)).toBe(true);
    expect(accessLikelyExpired(String(now - 60 * 60_000), now)).toBe(true);
  });
  it("falls back to the 401 retry when the issue time is unknown", () => {
    expect(accessLikelyExpired(null, now)).toBe(false);
    expect(accessLikelyExpired("garbage", now)).toBe(true);
  });
});
