export type LeagueTabId = "home" | "lineup" | "team" | "standings" | "schedule" | "playoffs" | "trades" | "waivers";

export interface LeagueTab {
  id: LeagueTabId;
  label: string;
  href: string;
  /** Shown in the mobile bottom bar; the rest go under More. */
  primary: boolean;
}

export interface LeagueNavTeam {
  id: string;
  owner_id?: string | null;
  co_owner_id?: string | null;
}

/** The viewer's team in this league: an owned or co-owned team first, then a legacy local claim. */
export function findMyTeamId(
  teams: readonly LeagueNavTeam[],
  userId: string | null,
  claimedTeamIds: readonly string[] = [],
): string | null {
  if (!userId) return null;
  const owned = teams.find((t) => t.owner_id === userId || t.co_owner_id === userId);
  if (owned) return owned.id;
  return teams.find((t) => claimedTeamIds.includes(t.id))?.id ?? null;
}

/** Tabs for one league. Lineup and Team only exist when the viewer has a team. */
export function leagueTabs(leagueId: string, myTeamId: string | null): LeagueTab[] {
  const base = `/leagues/${leagueId}`;
  const tabs: (LeagueTab | null)[] = [
    { id: "home", label: "Home", href: base, primary: true },
    myTeamId ? { id: "lineup", label: "Lineup", href: `${base}/teams/${myTeamId}/lineup`, primary: true } : null,
    myTeamId ? { id: "team", label: "My team", href: `${base}/teams/${myTeamId}`, primary: true } : null,
    { id: "standings", label: "Standings", href: `${base}/standings`, primary: true },
    { id: "schedule", label: "Schedule", href: `${base}/schedule`, primary: !myTeamId },
    { id: "playoffs", label: "Playoffs", href: `${base}/playoffs`, primary: false },
    { id: "trades", label: "Trades", href: `${base}/trades`, primary: !myTeamId },
    { id: "waivers", label: "Waivers", href: `${base}/waivers`, primary: false },
  ];
  return tabs.filter((t): t is LeagueTab => t !== null);
}

/** The tab whose page is showing. Another team's page belongs to no tab. */
export function activeTabId(pathname: string, tabs: readonly LeagueTab[]): LeagueTabId | null {
  const path = pathname.replace(/\/+$/, "");
  const exact = tabs.find((t) => t.href === path);
  if (exact) return exact.id;
  return tabs.find((t) => t.id !== "home" && t.id !== "team" && path.startsWith(`${t.href}/`))?.id ?? null;
}
