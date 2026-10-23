import { describe, expect, it } from "vitest";
import type { GSummary } from "@/lib/guillotine";
import { loadGuillotineData, type GuillotineApi } from "./useGuillotineData";

const teams = [
  { id: "a", name: "A", eliminated_week: null, created_at: "2026-08-01T00:00:00Z" },
  { id: "b", name: "B", eliminated_week: null, created_at: "2026-08-01T00:00:00Z" },
  { id: "c", name: "C", eliminated_week: 2, created_at: "2026-08-01T00:00:00Z" },
  { id: "d", name: "D", eliminated_week: 1, created_at: "2026-08-01T00:00:00Z" },
];
const points = new Map([["a", 600], ["b", 500], ["c", 150], ["d", 60]]);

/** b leads the finale 2-1 (weeks 3-5). */
const bLeads: GSummary = {
  phase: "finale",
  champion_team_id: null,
  runner_up_team_id: null,
  finalists: [
    { team_id: "b", wins: 2, losses: 1, ties: 0, points: 320 },
    { team_id: "a", wins: 1, losses: 2, ties: 0, points: 330 },
  ],
  finale_weeks: [3, 4, 5],
  places: { a: null, b: null, c: 3, d: 4 },
};

function fakeApi(opts: { seasonType?: string; week?: number; failWeeks?: number[]; teamList?: typeof teams } = {}) {
  const calls: number[] = [];
  const api: GuillotineApi = {
    getCurrentWeek: async () => ({ season: 2026, week: opts.week ?? 6, season_type: opts.seasonType ?? "regular" }),
    getTeams: async () => opts.teamList ?? teams,
    getWeeklyScores: async (_id, week) => {
      calls.push(week);
      if (opts.failWeeks?.includes(week)) throw new Error(`week ${week} failed`);
      return { team_scores: [{ team_id: "a", total_score: 140, projected_score: null }, { team_id: "b", total_score: 90, projected_score: null }] };
    },
    getNflScores: async () => { throw new Error("optional"); },
  };
  return { api, calls };
}

describe("loadGuillotineData", () => {
  it("draws the backend series: b leads 2-1 even when a is ahead this week", async () => {
    const { api } = fakeApi();
    const d = await loadGuillotineData(api, "L", points, bLeads);
    expect(d.state.phase).toBe("finale");
    expect(d.state.finale!.finalists.map((f) => [f.team.id, f.leading])).toEqual([["b", true], ["a", false]]);
  });

  it("errors instead of crowning anyone when a week fetch fails (b led 2-1)", async () => {
    // The old loader turned a failed week into an empty one, so a 2-1 lead
    // for b could read as a series a won. Now the whole load fails.
    const { api } = fakeApi({ seasonType: "post", failWeeks: [18] });
    await expect(loadGuillotineData(api, "L", points, bLeads)).rejects.toThrow("week 18 failed");
  });

  it("errors on a failed current or previous week before the finale", async () => {
    const four = teams.map((t) => ({ ...t, eliminated_week: t.id === "d" ? 1 : null }));
    const elim: GSummary = { ...bLeads, phase: "elimination", finalists: [], finale_weeks: [], places: { a: null, b: null, c: null, d: 4 } };
    for (const fail of [6, 5]) {
      const { api } = fakeApi({ teamList: four, failWeeks: [fail] });
      await expect(loadGuillotineData(api, "L", points, elim)).rejects.toThrow(`week ${fail} failed`);
    }
    const { api, calls } = fakeApi({ teamList: four });
    const ok = await loadGuillotineData(api, "L", points, elim);
    expect(ok.state.block?.team.id).toBeDefined();
    expect(calls.sort()).toEqual([5, 6]);
  });

  it("errors without the backend summary", async () => {
    const { api } = fakeApi();
    await expect(loadGuillotineData(api, "L", points, null)).rejects.toThrow();
  });

  it("crowns the backend champion with no week fetches", async () => {
    const { api, calls } = fakeApi({ seasonType: "off", failWeeks: [17, 18] });
    const final: GSummary = { ...bLeads, phase: "final", champion_team_id: "b", runner_up_team_id: "a",
      finale_weeks: [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
      places: { b: 1, a: 2, c: 3, d: 4 } };
    const d = await loadGuillotineData(api, "L", points, final);
    expect(d.state.phase).toBe("champion");
    expect(d.state.finale!.finalists[0].team.id).toBe("b");
    expect(d.state.block).toBeNull();
    expect(calls).toEqual([]);
  });

  it("treats the preseason as week 1 with nothing on the block", async () => {
    const four = teams.map((t) => ({ ...t, eliminated_week: null }));
    const elim: GSummary = { ...bLeads, phase: "elimination", finalists: [], finale_weeks: [], places: { a: null, b: null, c: null, d: null } };
    const { api, calls } = fakeApi({ seasonType: "pre", week: 0, teamList: four });
    const api2: GuillotineApi = { ...api, getWeeklyScores: async (id, w, y) => { await api.getWeeklyScores(id, w, y); return { team_scores: [] }; } };
    const d = await loadGuillotineData(api2, "L", points, elim);
    expect(d.state.week).toBe(1);
    expect(d.state.phase).toBe("prekickoff");
    expect(d.state.block).toBeNull();
    expect(calls).toEqual([1]);
  });
});
