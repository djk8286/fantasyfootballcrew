"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import {
  ArrowLeftRight,
  CalendarDays,
  Check,
  ChevronDown,
  ClipboardList,
  Crown,
  Home,
  MoreHorizontal,
  Repeat,
  Settings,
  Shield,
  Trophy,
  type LucideIcon,
} from "lucide-react";
import { getCurrentUserId, isLoggedIn, leaguesApi, nflApi, teamsApi } from "@/lib/api-client";
import { activeTabId, findMyTeamId, leagueTabs, type LeagueTabId } from "@/lib/league-nav";
import { Skeleton } from "@/components/ui/Skeleton";

const ICONS: Record<LeagueTabId, LucideIcon> = {
  home: Home,
  lineup: ClipboardList,
  team: Shield,
  standings: Trophy,
  schedule: CalendarDays,
  playoffs: Crown,
  trades: ArrowLeftRight,
  waivers: Repeat,
};

interface ShellLeague {
  id: string;
  name: string;
  commissioner_id?: string;
  co_commissioner_ids?: string[] | null;
}

interface ShellData {
  league: ShellLeague | null;
  myTeamId: string | null;
  myLeagues: { id: string; name: string }[];
  week: { week: number; season_type: string } | null;
}

function legacyClaims(leagueId: string): string[] {
  try {
    const stored = JSON.parse(localStorage.getItem("ffc_user_teams") || "{}");
    return stored[leagueId] ? [stored[leagueId]] : [];
  } catch {
    return [];
  }
}

async function loadShell(leagueId: string): Promise<ShellData> {
  const userId = getCurrentUserId();
  const [league, teams, myLeagues, week] = await Promise.all([
    leaguesApi.get(leagueId).catch(() => null) as Promise<ShellLeague | null>,
    (teamsApi.getByLeague(leagueId) as Promise<{ id: string; owner_id?: string | null; co_owner_id?: string | null }[]>).catch(() => []),
    isLoggedIn() ? (leaguesApi.list({ mine: true }) as Promise<{ id: string; name: string }[]>).catch(() => []) : Promise.resolve([]),
    nflApi.getCurrentWeek().catch(() => null),
  ]);
  return {
    league,
    myTeamId: findMyTeamId(teams, userId, userId ? legacyClaims(leagueId) : []),
    myLeagues,
    week,
  };
}

function weekLabel(week: ShellData["week"]): string | null {
  if (!week) return null;
  if (week.season_type === "post") return `Playoffs wk ${week.week}`;
  if (week.season_type === "pre") return "Preseason";
  return `Week ${week.week}`;
}

/** League top bar, tab nav and mobile tab bar, shared by every /leagues/[id] page. */
export default function LeagueShell({ leagueId, children }: { leagueId: string; children: ReactNode }) {
  const pathname = usePathname();
  const [data, setData] = useState<ShellData | null>(null);
  const [menu, setMenu] = useState<{ kind: "leagues" | "more"; path: string } | null>(null);

  useEffect(() => {
    let live = true;
    loadShell(leagueId).then((d) => {
      if (live) setData(d);
    });
    return () => {
      live = false;
    };
  }, [leagueId]);

  // A menu belongs to the page it was opened on, so navigating closes it.
  const openMenu = menu && menu.path === pathname ? menu.kind : null;
  const toggle = (kind: "leagues" | "more") => setMenu(openMenu === kind ? null : { kind, path: pathname });

  useEffect(() => {
    document.body.classList.add("has-league-tabbar");
    return () => document.body.classList.remove("has-league-tabbar");
  }, []);

  useEffect(() => {
    if (!openMenu) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setMenu(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openMenu]);

  const tabs = leagueTabs(leagueId, data?.myTeamId ?? null);
  const active = activeTabId(pathname, tabs);
  const userId = getCurrentUserId();
  const isManager =
    !!userId && !!data?.league && (data.league.commissioner_id === userId || (data.league.co_commissioner_ids || []).includes(userId));
  const otherLeagues = (data?.myLeagues ?? []).filter((l) => l.id !== leagueId);
  const secondary = tabs.filter((t) => !t.primary);
  const moreActive = secondary.some((t) => t.id === active);
  const week = weekLabel(data?.week ?? null);

  return (
    <>
      <div className="border-b border-ink-700 bg-ink-950">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="flex h-12 items-center gap-3">
            <div className="relative min-w-0">
              {data?.league ? (
                otherLeagues.length > 0 ? (
                  <button
                    type="button"
                    onClick={() => toggle("leagues")}
                    aria-expanded={openMenu === "leagues"}
                    aria-haspopup="menu"
                    className="flex min-w-0 items-center gap-1.5 rounded-control px-1 py-1 text-sm font-semibold text-ink-100 hover:bg-ink-800"
                  >
                    <span className="truncate">{data.league.name}</span>
                    <ChevronDown className="h-4 w-4 shrink-0 text-ink-400" aria-hidden />
                  </button>
                ) : (
                  <Link href={`/leagues/${leagueId}`} className="block truncate px-1 text-sm font-semibold text-ink-100">
                    {data.league.name}
                  </Link>
                )
              ) : (
                <Skeleton className="h-4 w-40" />
              )}
              {openMenu === "leagues" && data?.league && (
                <div role="menu" className="absolute left-0 top-full z-50 mt-1 w-64 rounded-card border border-ink-700 bg-ink-900 p-1 shadow-xl">
                  <div className="flex items-center gap-2 rounded-control px-3 py-2 text-sm text-ink-100">
                    <Check className="h-4 w-4 text-ink-400" aria-hidden />
                    <span className="truncate">{data.league.name}</span>
                  </div>
                  {otherLeagues.map((l) => (
                    <Link
                      key={l.id}
                      role="menuitem"
                      href={`/leagues/${l.id}`}
                      className="block truncate rounded-control py-2 pl-9 pr-3 text-sm text-ink-300 hover:bg-ink-800 hover:text-ink-100"
                    >
                      {l.name}
                    </Link>
                  ))}
                </div>
              )}
            </div>
            {week && (
              <span className="num shrink-0 rounded-chip bg-ink-800 px-2 py-0.5 text-xs text-ink-300">{week}</span>
            )}
            {isManager && (
              <Link
                href={`/leagues/${leagueId}/commissioner`}
                className="ml-auto flex shrink-0 items-center gap-1.5 rounded-control px-2 py-1 text-xs font-medium text-ink-300 hover:bg-ink-800 hover:text-ink-100"
              >
                <Settings className="h-4 w-4" aria-hidden />
                <span className="hidden sm:inline">Commissioner</span>
              </Link>
            )}
          </div>
          <nav aria-label="League" className="-mb-px hidden gap-1 md:flex">
            {tabs.map((t) => (
              <Link
                key={t.id}
                href={t.href}
                aria-current={t.id === active ? "page" : undefined}
                className={`border-b-2 px-3 pb-2.5 pt-1 text-sm font-medium transition-colors ${
                  t.id === active ? "border-ink-100 text-ink-100" : "border-transparent text-ink-400 hover:text-ink-100"
                }`}
              >
                {t.label}
              </Link>
            ))}
          </nav>
        </div>
      </div>

      {children}

      <nav
        aria-label="League"
        className="fixed inset-x-0 bottom-0 z-50 border-t border-ink-700 bg-ink-950/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden"
      >
        {openMenu === "more" && (
          <div role="menu" className="absolute inset-x-2 bottom-full mb-2 rounded-card border border-ink-700 bg-ink-900 p-1 shadow-xl">
            {secondary.map((t) => {
              const Icon = ICONS[t.id];
              return (
                <Link
                  key={t.id}
                  role="menuitem"
                  href={t.href}
                  aria-current={t.id === active ? "page" : undefined}
                  className={`flex items-center gap-3 rounded-control px-3 py-3 text-sm ${
                    t.id === active ? "bg-ink-800 text-ink-100" : "text-ink-300"
                  }`}
                >
                  <Icon className="h-4 w-4" aria-hidden />
                  {t.label}
                </Link>
              );
            })}
          </div>
        )}
        <div className="flex h-16">
          {tabs
            .filter((t) => t.primary)
            .map((t) => {
              const Icon = ICONS[t.id];
              const on = t.id === active;
              return (
                <Link
                  key={t.id}
                  href={t.href}
                  aria-current={on ? "page" : undefined}
                  className={`flex flex-1 flex-col items-center justify-center gap-1 text-label font-medium tracking-normal ${on ? "text-ink-100" : "text-ink-400"}`}
                >
                  <Icon className="h-5 w-5" aria-hidden />
                  {t.label}
                </Link>
              );
            })}
          <button
            type="button"
            onClick={() => toggle("more")}
            aria-expanded={openMenu === "more"}
            aria-haspopup="menu"
            className={`flex flex-1 flex-col items-center justify-center gap-1 text-label font-medium tracking-normal ${
              openMenu === "more" || moreActive ? "text-ink-100" : "text-ink-400"
            }`}
          >
            <MoreHorizontal className="h-5 w-5" aria-hidden />
            More
          </button>
        </div>
      </nav>
    </>
  );
}
