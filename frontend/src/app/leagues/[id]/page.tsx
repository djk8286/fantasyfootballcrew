"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Bot, Clock, ListChecks, Lock, Mail, Send, Shield, Swords, UserPlus, Users } from "lucide-react";
import Avatar from "@/components/Avatar";
import AdSlot from "@/components/AdSlot";
import ManagementWindowIndicator from "@/components/ManagementWindowIndicator";
import { ActivityFeed, type ActivityItem } from "@/components/ActivityFeed";
import { PlayerNewsCard } from "@/components/PlayerNewsCard";
import { SalaryCapBadge, BestBallBadge } from "@/components/LeagueBadges";
import type { AdminLeague, AdminTeam } from "@/components/commissioner/types";
import { Badge } from "@/components/ui/Badge";
import { Button, buttonClasses } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { Num } from "@/components/ui/Num";
import { Skeleton, SkeletonRows } from "@/components/ui/Skeleton";
import {
  draftsApi,
  friendlyErrorMessage,
  isLoggedIn,
  joinRequestsApi,
  leaguesApi,
  nflApi,
  teamsApi,
  tradesApi,
  waiversApi,
} from "@/lib/api-client";
import { errorStatus, loadProblem } from "@/lib/access-problem";
import { initialWeek } from "@/lib/current-week";
import { barShare, headline, homeMode, leagueChips, recapLine, recordLine, scoreboardTitle, shortTeamName, winChance, type HomeSide, type Recap } from "@/lib/league-home";

// ─── Data ─────────────────────────────────────────────────────

interface LeagueData extends AdminLeague {
  viewer_join_status: string | null;
}

interface Home {
  league: {
    name: string;
    league_type: string;
    visibility: string;
    draft_status: string;
    team_count: number;
    max_teams: number;
    scoring: string;
    best_ball: boolean;
    is_commissioner: boolean;
    is_member: boolean;
  };
  week: number;
  year: number;
  week_status: "upcoming" | "live" | "final" | "unknown";
  my_team: { id: string; name: string; has_lineup_set: boolean } | null;
  my_matchup: { me: HomeSide; opponent: HomeSide } | null;
  top_issue: { kind: string; message: string } | null;
  issue_count: number;
  last_week: Recap | null;
  scoreboard: { team_a: HomeSide; team_b: HomeSide; mine: boolean }[];
  standings: { rank: number; team_id: string; name: string; wins: number; losses: number; ties: number; points_for: number; streak: string | null; mine: boolean }[];
  activity: ActivityItem[];
}

const CURRENT_YEAR = new Date().getFullYear();

async function fetchLeagueHome(id: string) {
  const [state, league, teams] = await Promise.all([
    nflApi.getCurrentWeek().catch(() => null),
    leaguesApi.get(id).catch(() => null) as Promise<LeagueData | null>,
    teamsApi.getByLeague(id).catch(() => []) as Promise<AdminTeam[]>,
  ]);
  if (!league) return null;
  const year = state?.season ?? CURRENT_YEAR;
  const week = initialWeek({ param: null, state, draftComplete: league.draft_status === "completed" });
  let homeStatus: number | null = null;
  const [home, cap, recap, draft] = await Promise.all([
    leaguesApi.getHome(id, week, year).catch((err: unknown) => {
      homeStatus = errorStatus(err);
      return null;
    }) as Promise<Home | null>,
    leaguesApi.getSalaryCapSettings(id).catch(() => null) as Promise<{ enabled?: boolean } | null>,
    leaguesApi.getTeamRecap(id).catch(() => null) as Promise<{ content: string; week: number } | null>,
    league.draft_status === "not_started"
      ? Promise.resolve(null)
      : (fetch(`/api/v1/drafts/find?league_id=${id}`).then((r) => (r.ok ? r.json() : null)).catch(() => null) as Promise<{ id?: string } | null>),
  ]);
  return { league, teams: Array.isArray(teams) ? teams : [], home, homeProblem: home ? null : loadProblem(homeStatus, "league"), capEnabled: !!cap?.enabled, aiRecap: recap, draftId: draft?.id ?? null };
}

type PageData = NonNullable<Awaited<ReturnType<typeof fetchLeagueHome>>>;

// ─── Pieces ───────────────────────────────────────────────────

function Header({ data, isManager }: { data: PageData; isManager: boolean }) {
  const { league, home } = data;
  const chips = home ? leagueChips(home.league) : [];
  return (
    <div className="flex flex-wrap items-start gap-4">
      <div className="min-w-0 flex-1 basis-64">
        <h1 className="text-2xl font-semibold tracking-tight text-ink-100 lg:text-3xl">{league.name}</h1>
        {league.description && <p className="mt-1 max-w-2xl text-sm text-ink-400">{league.description}</p>}
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          {chips.map((c) => (
            <Badge key={c}>{c}</Badge>
          ))}
          {data.capEnabled && <SalaryCapBadge />}
          {home?.league.best_ball && <BestBallBadge />}
          {home?.league.best_ball && <ManagementWindowIndicator leagueId={league.id} />}
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        {league.draft_status === "completed" && data.draftId && (
          <Link href={`/draft/${data.draftId}`} className={`${buttonClasses("ghost", "md")} max-sm:hidden`}>
            Draft results
          </Link>
        )}
        {isManager && (
          <>
            <Link href={`/leagues/${league.id}/commissioner?tab=invites`} className={buttonClasses("secondary", "md")}>
              <UserPlus className="h-4 w-4" aria-hidden /> Invite
            </Link>
            <Link href={`/leagues/${league.id}/commissioner`} className={buttonClasses("secondary", "md")}>
              <Shield className="h-4 w-4" aria-hidden /> Commissioner
            </Link>
          </>
        )}
      </div>
    </div>
  );
}

function SideBlock({ side, align, leagueId, mine, leagueName }: { side: HomeSide; align: "left" | "right"; leagueId: string; mine: boolean; leagueName: string }) {
  const value = headline(side);
  return (
    <div className={`min-w-0 ${align === "right" ? "text-right" : ""}`}>
      <Link href={`/leagues/${leagueId}/teams/${side.team_id}`} title={side.name} className="block truncate text-sm font-semibold text-ink-100 hover:text-gold">
        {shortTeamName(side.name, leagueName)}
      </Link>
      <Num value={value} size="score" className={`mt-1 block ${mine ? "text-ink-100" : "text-ink-300"}`} />
      {side.score != null && side.projected != null && <span className="num text-xs text-ink-400">Proj {side.projected.toFixed(1)}</span>}
    </div>
  );
}

function MatchupCard({ home, leagueId, leagueName }: { home: Home; leagueId: string; leagueName: string }) {
  const m = home.my_matchup!;
  const live = home.week_status === "live";
  const final = home.week_status === "final";
  const started = m.me.score != null;
  const share = barShare(headline(m.me), headline(m.opponent));
  const chance = !started ? winChance(m.me.projected, m.opponent.projected) : null;
  const canSetLineup = !home.league.best_ball && !final && home.my_team;
  return (
    <Card>
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-label font-semibold uppercase text-ink-400">Your matchup · Week {home.week}</h2>
        {live ? <Badge tone="live">Live</Badge> : final ? <Badge>Final</Badge> : <span className="text-xs text-ink-400">Not started</span>}
      </div>
      <div className="grid grid-cols-[1fr_auto_1fr] items-end gap-3">
        <SideBlock side={m.me} align="left" leagueId={leagueId} leagueName={leagueName} mine />
        <span className="pb-2 text-xs text-ink-400">vs</span>
        <SideBlock side={m.opponent} align="right" leagueId={leagueId} leagueName={leagueName} mine={false} />
      </div>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-ink-700" aria-hidden>
        <div className="h-full rounded-full bg-gold" style={{ width: `${Math.round(share * 100)}%` }} />
      </div>
      <div className="mt-1.5 flex justify-between gap-3 text-xs text-ink-400">
        <span>{started ? (final ? "Final score" : "Live score") : chance != null ? `Projected · ${chance}% to win` : "No projections yet"}</span>
        <span>Projections from Sleeper</span>
      </div>
      {canSetLineup && (
        <div className="mt-4 flex flex-col gap-2 sm:flex-row">
          <Link href={`/leagues/${leagueId}/teams/${home.my_team!.id}/lineup`} className={buttonClasses("primary", "md")}>
            <ListChecks className="h-4 w-4" aria-hidden /> Set lineup
            {home.top_issue && (
              <span className="ml-1 rounded-chip bg-ink-950/25 px-1.5 py-0.5 text-xs font-medium">
                {home.top_issue.message}
                {home.issue_count > 1 && ` +${home.issue_count - 1}`}
              </span>
            )}
          </Link>
          <Link href={`/leagues/${leagueId}/teams/${m.opponent.team_id}`} className={buttonClasses("secondary", "md")}>
            Scout {shortTeamName(m.opponent.name, leagueName)}
          </Link>
        </div>
      )}
    </Card>
  );
}

function RecapCard({ recap }: { recap: Recap }) {
  const text = recapLine(recap);
  if (!text) return null;
  return (
    <Card className="border-warn/40 bg-warn/[0.06]">
      <p className="flex items-start gap-3 text-sm text-ink-200">
        <span className="shrink-0">
          <Badge tone="warn">Wk {recap.week}</Badge>
        </span>
        <span>{text}</span>
      </p>
    </Card>
  );
}

function Scoreboard({ home, leagueId, leagueName }: { home: Home; leagueId: string; leagueName: string }) {
  if (home.scoreboard.length === 0) return null;
  const tileSide = (s: HomeSide, lead: boolean) => (
    <Link href={`/leagues/${leagueId}/teams/${s.team_id}`} className="flex items-center justify-between gap-3 py-0.5 hover:text-gold">
      <span title={s.name} className={`truncate text-sm ${lead ? "font-semibold text-ink-100" : "text-ink-300"}`}>{shortTeamName(s.name, leagueName)}</span>
      <Num value={headline(s)} className={`text-sm ${lead ? "text-ink-100" : "text-ink-400"}`} />
    </Link>
  );
  return (
    <Card>
      <CardHeader title={scoreboardTitle(home.week, home.scoreboard)} />
      <div className="-mx-4 flex snap-x gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:grid sm:grid-cols-2 sm:overflow-visible sm:px-0 xl:grid-cols-3">
        {home.scoreboard.map((g) => {
          const a = headline(g.team_a) ?? 0;
          const b = headline(g.team_b) ?? 0;
          return (
            <div
              key={g.team_a.team_id}
              className={`min-w-[11rem] shrink-0 snap-start rounded-control border px-3 py-2 sm:min-w-0 ${g.mine ? "border-gold/60 bg-gold/[0.06]" : "border-ink-700 bg-ink-950/40"}`}
            >
              {tileSide(g.team_a, a > b)}
              {tileSide(g.team_b, b > a)}
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function StandingsCard({ home, leagueId, leagueName }: { home: Home; leagueId: string; leagueName: string }) {
  return (
    <Card className="px-0 lg:px-0">
      <div className="px-4 lg:px-5">
        <CardHeader
          title="Standings"
          action={
            <Link href={`/leagues/${leagueId}/standings`} className="text-xs font-medium text-gold hover:text-gold-hi">
              Full table
            </Link>
          }
        />
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-label uppercase text-ink-400">
            <th className="w-10 pb-2 pl-4 text-left font-semibold lg:pl-5">#</th>
            <th className="pb-2 text-left font-semibold">Team</th>
            <th className="w-12 pb-2 text-right font-semibold">W-L</th>
            <th className="w-16 pb-2 text-right font-semibold">PF</th>
            <th className="w-16 pb-2 pl-3 pr-4 text-right font-semibold lg:pr-5">Strk</th>
          </tr>
        </thead>
        <tbody>
          {home.standings.map((r) => (
            <tr key={r.team_id} className={`border-t border-ink-700 ${r.mine ? "bg-gold/[0.07]" : ""}`}>
              <td className="num py-2 pl-4 text-ink-400 lg:pl-5">{r.rank}</td>
              <td className="max-w-0 py-2 pr-2">
                <Link href={`/leagues/${leagueId}/teams/${r.team_id}`} title={r.name} className={`block truncate hover:text-gold ${r.mine ? "font-semibold text-gold" : "text-ink-100"}`}>
                  {shortTeamName(r.name, leagueName)}
                </Link>
              </td>
              <td className="num py-2 text-right text-ink-100">{recordLine(r)}</td>
              <td className="py-2 text-right">
                <Num value={r.points_for} className="text-sm text-ink-300" />
              </td>
              <td className={`num py-2 pr-4 text-right lg:pr-5 ${r.streak?.startsWith("W") ? "text-win" : r.streak?.startsWith("L") ? "text-loss" : "text-ink-400"}`}>
                {r.streak ?? "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function DraftCard({ data, isManager, onError }: { data: PageData; isManager: boolean; onError: (m: string) => void }) {
  const { league, teams } = data;
  const router = useRouter();
  const [starting, setStarting] = useState(false);
  const full = teams.length >= league.max_teams;
  if (league.draft_status === "in_progress") {
    return (
      <Card you>
        <div className="flex flex-wrap items-center gap-3">
          <Swords className="h-5 w-5 text-gold" aria-hidden />
          <p className="flex-1 text-sm font-semibold text-ink-100">The draft is on.</p>
          <Link href={`/draft/${data.draftId ?? league.id}`} className={buttonClasses("primary", "md")}>
            Enter draft room
          </Link>
        </div>
      </Card>
    );
  }
  async function start() {
    setStarting(true);
    try {
      const d = (await draftsApi.create(league.id, 15)) as { id: string };
      router.push(`/draft/${d.id}`);
    } catch (err) {
      onError(friendlyErrorMessage(err, "Couldn't start the draft."));
      setStarting(false);
    }
  }
  return (
    <Card>
      <CardHeader title="Draft" />
      <p className="text-sm text-ink-200">
        {full ? `All ${league.max_teams} teams are in.` : `${teams.length} of ${league.max_teams} teams are in.`}{" "}
        {isManager ? (full ? "Start the draft when everyone is ready." : "Fill the open spots with CPU teams or invite people.") : "The commissioner starts the draft."}
      </p>
      <div className="mt-3 flex -space-x-2">
        {teams.slice(0, 12).map((t) => (
          <Avatar key={t.id} url={t.avatar_url} size={28} rounded="rounded-full" className="border-2 border-ink-900" title={t.name} />
        ))}
      </div>
      {isManager && (
        <div className="mt-4">
          <Button variant="primary" onClick={start} disabled={starting}>
            {starting ? "Starting" : "Start draft"}
          </Button>
        </div>
      )}
    </Card>
  );
}

/** For people who aren't in the league yet: claim an open team or ask in. */
function JoinCard({ data, onChanged, onError }: { data: PageData; onChanged: () => void; onError: (m: string) => void }) {
  const { league, teams } = data;
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const status = league.viewer_join_status;
  const open = teams.filter((t) => t.is_cpu || !t.owner_id || t.owner_id === "cpu" || t.owner_id === "placeholder");

  if (!isLoggedIn()) {
    return (
      <Card>
        <p className="text-sm text-ink-300">
          <Link href="/login" className="font-medium text-gold hover:text-gold-hi">
            Log in
          </Link>{" "}
          to join this league.
        </p>
      </Card>
    );
  }
  async function claim(teamId: string) {
    setBusy(teamId);
    try {
      await teamsApi.claim(teamId);
      onChanged();
    } catch (err) {
      onError(friendlyErrorMessage(err, "Couldn't claim that team."));
    } finally {
      setBusy(null);
    }
  }
  async function request() {
    setBusy("request");
    try {
      await joinRequestsApi.create(league.id, note || undefined);
      setNote("");
      onChanged();
    } catch (err) {
      onError(friendlyErrorMessage(err, "Couldn't send the request."));
    } finally {
      setBusy(null);
    }
  }
  if (status === "eligible") {
    return (
      <Card>
        <CardHeader title="Join this league" />
        {open.length === 0 ? (
          <p className="text-sm text-ink-400">Every team has a manager.</p>
        ) : (
          <ul className="divide-y divide-ink-700">
            {open.map((t) => (
              <li key={t.id} className="flex items-center gap-3 py-2">
                <Avatar url={t.avatar_url} size={28} />
                <span className="flex-1 truncate text-sm text-ink-100">{t.name}</span>
                <Button size="sm" variant="primary" disabled={busy === t.id} onClick={() => claim(t.id)}>
                  {busy === t.id ? "Claiming" : "Claim"}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    );
  }
  if (status === "requested") {
    return (
      <Card>
        <p className="flex items-center gap-2 text-sm text-ink-300">
          <Clock className="h-4 w-4 text-warn" aria-hidden /> Your request to join is waiting on the commissioner.
        </p>
      </Card>
    );
  }
  if (status === "invited") {
    return (
      <Card>
        <p className="flex items-center gap-2 text-sm text-ink-300">
          <Mail className="h-4 w-4 text-gold" aria-hidden /> You have an invite. Use the link in your email to join.
        </p>
      </Card>
    );
  }
  if (status === "blocked") {
    return (
      <Card>
        {league.visibility === "invite_only" ? (
          <>
            <p className="flex items-center gap-2 text-sm text-ink-300">
              <Lock className="h-4 w-4 text-ink-400" aria-hidden /> This league is invite only. Ask the commissioner in.
            </p>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={2}
              placeholder="Add a note (optional)"
              className="mt-3 w-full rounded-control border border-ink-700 bg-ink-950 px-3 py-2 text-sm text-ink-100 placeholder:text-ink-400"
            />
            <Button className="mt-2" variant="primary" onClick={request} disabled={busy === "request"}>
              <Send className="h-4 w-4" aria-hidden /> {busy === "request" ? "Sending" : "Ask to join"}
            </Button>
          </>
        ) : (
          <p className="flex items-center gap-2 text-sm text-ink-300">
            <Lock className="h-4 w-4 text-ink-400" aria-hidden /> This league is private.
          </p>
        )}
      </Card>
    );
  }
  return null;
}

function PageSkeleton() {
  return (
    <div className="mx-auto max-w-6xl space-y-4 px-4 py-6 sm:px-6 lg:px-8">
      <Skeleton className="h-8 w-64" />
      <Skeleton className="h-5 w-80" />
      <div className="gap-4 lg:grid lg:grid-cols-[minmax(0,1fr)_22rem]">
        <Card>
          <SkeletonRows rows={4} />
        </Card>
        <Card>
          <SkeletonRows rows={6} />
        </Card>
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────

export default function LeagueHomePage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<PageData | null | undefined>(undefined);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    fetchLeagueHome(id).then((d) => live && setData(d));
    return () => {
      live = false;
    };
  }, [id]);

  // Live weeks refresh scores every minute. Before the draft, refresh
  // every 8s so claims by other people show up.
  const status = data?.home?.week_status;
  const mode = data ? homeMode(data.league.draft_status) : null;
  useEffect(() => {
    if (status !== "live" && mode !== "predraft") return;
    const t = setInterval(() => fetchLeagueHome(id).then((d) => d && setData(d)), mode === "predraft" ? 8000 : 60000);
    return () => clearInterval(t);
  }, [id, status, mode]);

  async function reload() {
    const d = await fetchLeagueHome(id);
    if (d) setData(d);
  }

  if (data === undefined) return <PageSkeleton />;
  if (data === null) {
    return (
      <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6 lg:px-8">
        <Card>
          <p className="text-sm font-semibold text-ink-100">League not found.</p>
          <Link href="/dashboard" className="mt-2 inline-block text-sm text-gold hover:text-gold-hi">
            Back to your leagues
          </Link>
        </Card>
      </div>
    );
  }

  const { home } = data;
  const isManager = !!home?.league.is_commissioner;
  const isMember = !!home?.league.is_member;

  async function cancelMove(item: ActivityItem) {
    if (!item.cancel) return;
    setBusyId(item.id);
    try {
      if (item.cancel.type === "trade") await tradesApi.cancel(id, item.cancel.id);
      else await waiversApi.cancelClaim(id, item.cancel.id);
      await reload();
    } catch (err) {
      setError(friendlyErrorMessage(err, "Couldn't cancel that. Try again."));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="mx-auto max-w-6xl space-y-4 px-4 py-6 sm:px-6 lg:px-8">
      <Header data={data} isManager={isManager} />

      {error && (
        <div role="alert" className="flex items-start gap-3 rounded-card border border-loss/40 bg-loss/10 px-4 py-3 text-sm text-loss">
          <span className="flex-1">{error}</span>
          <button type="button" onClick={() => setError("")} className="text-loss/70 hover:text-loss" aria-label="Dismiss">
            ×
          </button>
        </div>
      )}

      {!home ? (
        <Card>
          {data.homeProblem?.kind === "login" ? (
            <p className="text-sm text-ink-300">
              <Link href={`/login?next=${encodeURIComponent(`/leagues/${id}`)}`} className="font-semibold text-gold">
                Log in
              </Link>{" "}
              {data.homeProblem.text}
            </p>
          ) : (
            <p className="text-sm text-ink-400">{data.homeProblem?.text ?? "Couldn't load this week. Try again in a moment."}</p>
          )}
        </Card>
      ) : (
        <div className="gap-4 space-y-4 lg:grid lg:grid-cols-[minmax(0,1fr)_22rem] lg:space-y-0">
          <div className="min-w-0 space-y-4">
            {!isMember && !isManager && <JoinCard data={data} onChanged={reload} onError={setError} />}
            {mode !== "season" && <DraftCard data={data} isManager={isManager} onError={setError} />}
            {mode === "season" && home.my_matchup && <MatchupCard home={home} leagueId={id} leagueName={data.league.name} />}
            {mode === "season" && home.last_week && <RecapCard recap={home.last_week} />}
            {mode === "season" && <Scoreboard home={home} leagueId={id} leagueName={data.league.name} />}
            <Card>
              <CardHeader title="League activity" />
              <ActivityFeed items={home.activity} onCancel={cancelMove} busyId={busyId} empty="Nothing has happened yet." />
            </Card>
            {data.aiRecap?.content && (
              <Card>
                <CardHeader
                  title={`Week ${data.aiRecap.week} recaps`}
                  action={
                    <span className="flex items-center gap-1 text-xs text-ink-400">
                      <Bot className="h-3.5 w-3.5" aria-hidden /> AI written
                    </span>
                  }
                />
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink-200">{data.aiRecap.content}</p>
              </Card>
            )}
          </div>
          <div className="space-y-4">
            {mode === "season" && home.standings.length > 0 ? (
              <StandingsCard home={home} leagueId={id} leagueName={data.league.name} />
            ) : (
              <Card>
                <CardHeader title="Teams" />
                <ul className="divide-y divide-ink-700">
                  {data.teams.map((t) => (
                    <li key={t.id} className="flex items-center gap-2.5 py-2">
                      <Avatar url={t.avatar_url} size={24} />
                      <Link href={`/leagues/${id}/teams/${t.id}`} className="flex-1 truncate text-sm text-ink-100 hover:text-gold">
                        {t.name}
                      </Link>
                      {t.is_cpu && <Users className="h-3.5 w-3.5 text-ink-400" aria-label="CPU" />}
                    </li>
                  ))}
                </ul>
              </Card>
            )}
            {home.my_team && mode === "season" && <PlayerNewsCard teamId={home.my_team.id} title="News on your players" digest={false} limit={4} />}
          </div>
        </div>
      )}

      <AdSlot placement="league-page-bottom" />
    </div>
  );
}
