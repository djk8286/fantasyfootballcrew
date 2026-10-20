import { describe, expect, it } from "vitest";
import { historySummaryLabel, leagueLabel, switcherLabels } from "./league-label";

const leagues = [
  { id: "aaaaaa1", name: "QA Test League", created_at: "2026-10-17T06:50:00Z" },
  { id: "bbbbbb2", name: "QA Test League", created_at: "2026-10-19T20:00:00Z" },
  { id: "cccccc3", name: "Solo League", created_at: "2026-10-01T00:00:00Z" },
];

describe("historySummaryLabel", () => {
  it("disambiguates same-named leagues in Recent entries", () => {
    const a = historySummaryLabel({ summary: "QA Tester Team — QA Test League", league_id: "aaaaaa1" }, leagues);
    const b = historySummaryLabel({ summary: "QA Tester Team — QA Test League", league_id: "bbbbbb2" }, leagues);
    expect(a).not.toBe(b);
    expect(a.startsWith("QA Tester Team — QA Test League (created")).toBe(true);
  });
  it("leaves unique names and league-less entries alone", () => {
    expect(historySummaryLabel({ summary: "My Team — Solo League", league_id: "cccccc3" }, leagues)).toBe("My Team — Solo League");
    expect(historySummaryLabel({ summary: "Bet: over 47.5", league_id: null }, leagues)).toBe("Bet: over 47.5");
  });
});

describe("switcherLabels", () => {
  it("disambiguates the current league and the others the same way as the dashboard", () => {
    const [a, b, c] = leagues;
    const out = switcherLabels(a, leagues);
    expect(out.current).toBe(leagueLabel(a, leagues));
    expect(out.current).not.toBe(a.name);
    expect(out.others.map((o) => o.id)).toEqual([b.id, c.id]);
    expect(out.others[0].label).toBe(leagueLabel(b, leagues));
    expect(out.others[0].label).not.toBe(out.current);
    expect(out.others[1].label).toBe("Solo League");
  });
  it("counts the current league even when it isn't in the user's list", () => {
    const [a, b] = leagues;
    const out = switcherLabels(a, [b]);
    expect(out.current).not.toBe(a.name);
    expect(out.others[0].label).not.toBe(b.name);
  });
});
