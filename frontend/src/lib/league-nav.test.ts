import { describe, expect, it } from "vitest";
import { activeTabId, findMyTeamId, leagueTabs } from "./league-nav";

const teams = [
  { id: "t1", owner_id: "cpu" },
  { id: "t2", owner_id: "u-other", co_owner_id: "u-me" },
  { id: "t3", owner_id: "u-me" },
];

describe("findMyTeamId", () => {
  it("prefers a team the account owns or co-owns", () => {
    expect(findMyTeamId(teams, "u-me")).toBe("t2");
    expect(findMyTeamId(teams, "u-other")).toBe("t2");
  });

  it("falls back to a legacy local claim, but only when logged in", () => {
    expect(findMyTeamId(teams, "u-new", ["t1"])).toBe("t1");
    expect(findMyTeamId(teams, null, ["t1"])).toBeNull();
    expect(findMyTeamId(teams, "u-new")).toBeNull();
  });
});

describe("leagueTabs", () => {
  it("gives a manager Lineup and My team links to their own team", () => {
    const tabs = leagueTabs("L", "t3");
    expect(tabs.map((t) => t.id)).toEqual(["home", "lineup", "team", "standings", "schedule", "playoffs", "trades", "waivers"]);
    expect(tabs.find((t) => t.id === "lineup")?.href).toBe("/leagues/L/teams/t3/lineup");
    expect(tabs.filter((t) => t.primary).map((t) => t.id)).toEqual(["home", "lineup", "team", "standings"]);
  });

  it("gives a visitor without a team no Lineup or My team, and promotes Schedule and Trades", () => {
    const tabs = leagueTabs("L", null);
    expect(tabs.map((t) => t.id)).not.toContain("lineup");
    expect(tabs.map((t) => t.id)).not.toContain("team");
    expect(tabs.filter((t) => t.primary).map((t) => t.id)).toEqual(["home", "standings", "schedule", "trades"]);
  });
});

describe("activeTabId", () => {
  const tabs = leagueTabs("L", "t3");

  it("matches each tab's own page", () => {
    expect(activeTabId("/leagues/L", tabs)).toBe("home");
    expect(activeTabId("/leagues/L/", tabs)).toBe("home");
    expect(activeTabId("/leagues/L/teams/t3", tabs)).toBe("team");
    expect(activeTabId("/leagues/L/teams/t3/lineup", tabs)).toBe("lineup");
    expect(activeTabId("/leagues/L/standings", tabs)).toBe("standings");
  });

  it("highlights nothing on another team's page or a settings page", () => {
    expect(activeTabId("/leagues/L/teams/t1", tabs)).toBeNull();
    expect(activeTabId("/leagues/L/teams/t1/lineup", tabs)).toBeNull();
    expect(activeTabId("/leagues/L/scoring", tabs)).toBeNull();
  });
});
