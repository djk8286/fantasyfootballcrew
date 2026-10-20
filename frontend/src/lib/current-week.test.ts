import { beforeEach, describe, expect, it, vi } from "vitest";
import { getCurrentNflState, initialWeek, parseWeekParam, resetCurrentNflStateCache, withWeekParam } from "./current-week";

describe("parseWeekParam", () => {
  it("accepts 1-18 and rejects everything else", () => {
    expect(parseWeekParam("7")).toBe(7);
    expect(parseWeekParam("18")).toBe(18);
    for (const bad of [null, undefined, "", "0", "19", "7.5", "-1", "abc", "07x"]) expect(parseWeekParam(bad)).toBeNull();
  });
});

describe("initialWeek", () => {
  const state = { season: 2026, week: 7 };
  it("keeps the week from the URL across a reload", () => {
    expect(initialWeek({ param: "6", state, draftComplete: true })).toBe(6);
    expect(initialWeek({ param: "9", state, draftComplete: false })).toBe(9);
  });
  it("defaults to the live NFL week once drafted, week 1 before", () => {
    expect(initialWeek({ param: null, state, draftComplete: true })).toBe(7);
    expect(initialWeek({ param: null, state, draftComplete: false })).toBe(1);
    expect(initialWeek({ param: "junk", state: null, draftComplete: true })).toBe(1);
    expect(initialWeek({ param: null, state: { season: 2026, week: 22 }, draftComplete: true })).toBe(18);
  });
});

describe("withWeekParam", () => {
  it("sets week and keeps other params", () => {
    expect(withWeekParam("", 7)).toBe("?week=7");
    expect(withWeekParam("?week=6&tab=x", 7)).toBe("?week=7&tab=x");
  });
});

describe("getCurrentNflState", () => {
  beforeEach(() => resetCurrentNflStateCache());
  it("shares one request between callers", async () => {
    const fetcher = vi.fn().mockResolvedValue({ season: 2026, week: 7 });
    const [a, b] = await Promise.all([getCurrentNflState(fetcher, 0), getCurrentNflState(fetcher, 10)]);
    expect(a).toEqual({ season: 2026, week: 7 });
    expect(b).toBe(a);
    expect(fetcher).toHaveBeenCalledTimes(1);
    await getCurrentNflState(fetcher, 61_000);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it("resolves null on failure and doesn't cache it", async () => {
    const fetcher = vi.fn().mockRejectedValueOnce(new Error("x")).mockResolvedValue({ season: 2026, week: 7 });
    expect(await getCurrentNflState(fetcher, 0)).toBeNull();
    expect(await getCurrentNflState(fetcher, 1)).toEqual({ season: 2026, week: 7 });
  });
});
