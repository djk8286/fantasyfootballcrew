"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeftRight, Bot, Check, ListChecks, Lock, Pencil, Skull, UserCheck, X } from "lucide-react";
import Avatar from "@/components/Avatar";
import AvatarEditor from "@/components/AvatarEditor";
import PlayerLink from "@/components/PlayerLink";
import CoachStaffPanel from "@/components/CoachStaffPanel";
import ManagementWindowIndicator from "@/components/ManagementWindowIndicator";
import { ActivityFeed, type ActivityItem } from "@/components/ActivityFeed";
import { PlayerNewsCard } from "@/components/PlayerNewsCard";
import { BestBallBadge, ConferenceBadge, PartnerBadge, SalaryCapBadge, conferenceShortLabel } from "@/components/LeagueBadges";
import { Badge, InjuryTag, PositionChip } from "@/components/ui/Badge";
import { Button, buttonClasses } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { Num, StatBlock } from "@/components/ui/Num";
import { Skeleton, SkeletonRows } from "@/components/ui/Skeleton";
import { Tabs } from "@/components/ui/Tabs";
import {
  friendlyErrorMessage,
  getCurrentUserId,
  isCurrentUser,
  isLoggedIn,
  leaguesApi,
  nflApi,
  standingsApi,
  syncSession,
  teamsApi,
  tradesApi,
  waiversApi,
} from "@/lib/api-client";
import { errorStatus, loadProblem, type LoadProblem } from "@/lib/access-problem";
import { initialWeek } from "@/lib/current-week";
import { groupRoster, ordinal, preDraftNote, recordText, scheduleRows, type ScheduleWeek } from "@/lib/team-page";

// ─── Data ─────────────────────────────────────────────────────

interface Game {
  opponent: string;
  home: boolean;
  kickoff_at: string;
  status: "pre" | "in" | "post";
  detail: string;
  locked: boolean;
}

interface RosterRow {
  id: string;
  full_name: string;
  position: string;
  team: string;
  injury_status: string | null;
  season_points: number | null;
  last_week_points: number | null;
  game: Game | null;
  on_bye: boolean;
  /** null for guests: lineups need a login (rosters don't, outside private leagues). */
  slot: string | null;
}

interface TeamRoster {
  team: {
    id: string;
    name: string;
    avatar_url: string | null;
    is_cpu: boolean;
    owner_id: string | null;
    co_owner_id: string | null;
    owner_username: string | null;
    co_owner_username: string | null;
  };
  record: { wins: number; losses: number; ties: number; points_for: number; points_against: number; rank: number | null; teams: number; streak: string | null };
  week: number;
  league_start_week: number;
  lineup_visible?: boolean;
  has_lineup_set: boolean | null;
  issues: { kind: string; message: string }[] | null;
  roster: RosterRow[];
}

interface TeamExtras {
  partner_team_id: string | null;
  conference: string | null;
  eliminated_week: number | null;
  last_words: string | null;
}

interface LeagueData {
  name: string;
  league_type?: string;
  draft_status?: string;
  conference_a_name?: string | null;
  conference_b_name?: string | null;
}

interface CapSummary {
  cap_space: number;
}

const CURRENT_YEAR = new Date().getFullYear();
const kickoffFormat = new Intl.DateTimeFormat(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" });

/** Everything the page needs, in parallel. Module-level so effects only set state in .then. */
async function fetchTeamPage(leagueId: string, teamId: string) {
  await syncSession();
  let rosterStatus: number | null = null;
  const [state, league] = await Promise.all([
    nflApi.getCurrentWeek().catch(() => null),
    leaguesApi.get(leagueId).catch(() => null) as Promise<LeagueData | null>,
  ]);
  const year = state?.season ?? CURRENT_YEAR;
  const week = initialWeek({ param: null, state, draftComplete: league?.draft_status === "completed" });
  const [roster, extras, schedule, activity, capSettings, bestBall] = await Promise.all([
    teamsApi.getRoster(teamId, week, year).catch((err: unknown) => {
      rosterStatus = errorStatus(err);
      return null;
    }) as Promise<TeamRoster | null>,
    teamsApi.get(teamId).catch(() => null) as Promise<TeamExtras | null>,
    standingsApi.getSchedule(leagueId, year).catch(() => null) as Promise<{ league_start_week?: number; schedule?: ScheduleWeek[] } | null>,
    leaguesApi.getActivity(leagueId, teamId, 20).catch(() => null) as Promise<{ items?: ActivityItem[] } | null>,
    leaguesApi.getSalaryCapSettings(leagueId).catch(() => null) as Promise<{ enabled?: boolean } | null>,
    leaguesApi.getBestBallSettings(leagueId).catch(() => null) as Promise<{ enabled?: boolean } | null>,
  ]);
  const cap = capSettings?.enabled ? ((await teamsApi.getCap(teamId).catch(() => null)) as CapSummary | null) : null;
  return {
    league,
    roster,
    rosterProblem: roster ? null : loadProblem(rosterStatus, "team"),
    extras,
    schedule: schedule?.schedule ?? [],
    activity: activity?.items ?? [],
    capEnabled: !!capSettings?.enabled,
    cap,
    bestBall: !!bestBall?.enabled,
  };
}

type PageData = Awaited<ReturnType<typeof fetchTeamPage>>;

// ─── Pieces ───────────────────────────────────────────────────

function GameCell({ row }: { row: RosterRow }) {
  if (row.on_bye) return <span className="text-ink-400">Bye</span>;
  const g = row.game;
  if (!g) return <span className="text-ink-400">—</span>;
  const when =
    g.status === "in" ? <span className="text-live">Live {g.detail}</span>
    : g.status === "post" ? <span className="text-ink-400">{g.detail || "Final"}</span>
    : <span className="text-ink-400">{kickoffFormat.format(new Date(g.kickoff_at))}</span>;
  return (
    <span className="flex items-center gap-1.5 whitespace-nowrap">
      <span className="text-ink-300">{g.home ? "vs" : "@"} {g.opponent}</span>
      {when}
      {g.locked && <Lock className="h-3 w-3 text-ink-400" aria-label="Locked" />}
    </span>
  );
}

function RosterTable({ rows, week }: { rows: RosterRow[]; week: number }) {
  const groups = groupRoster(rows);
  return (
    <Card className="px-0 lg:px-0">
      <div className="grid grid-cols-[1fr_auto_3.5rem] gap-3 border-b border-ink-700 px-4 pb-2 text-label font-semibold uppercase text-ink-400 md:grid-cols-[1fr_11rem_4rem_4rem_4rem]">
        <span>Player</span>
        <span className="hidden md:block">Week {week}</span>
        <span className="text-right md:text-left">Status</span>
        <span className="hidden text-right md:block">Last wk</span>
        <span className="text-right">Season</span>
      </div>
      {groups.map((g) => (
        <div key={g.position}>
          {g.players.map((p) => (
            <div
              key={p.id}
              className="grid grid-cols-[1fr_auto_3.5rem] items-center gap-3 border-b border-ink-700 px-4 py-2.5 last:border-b-0 md:grid-cols-[1fr_11rem_4rem_4rem_4rem]"
            >
              <div className="flex min-w-0 items-center gap-2.5">
                <PositionChip pos={p.position} />
                <div className="min-w-0">
                  <div className="flex min-w-0 items-center gap-2">
                    <PlayerLink id={p.id} className="truncate text-sm font-medium text-ink-100">
                      {p.full_name}
                    </PlayerLink>
                    <span className="hidden shrink-0 text-xs text-ink-400 sm:inline">{p.team}</span>
                    <InjuryTag status={p.injury_status} onBye={p.on_bye} />
                  </div>
                  <div className="mt-0.5 flex gap-1 overflow-hidden text-xs md:hidden">
                    <span className="shrink-0 text-ink-400 sm:hidden">{p.team} ·</span>
                    <GameCell row={p} />
                  </div>
                </div>
              </div>
              <div className="hidden text-xs md:block">
                <GameCell row={p} />
              </div>
              <span className="text-right md:text-left">
                {p.slot == null ? <span className="text-xs text-ink-500">—</span> : p.slot === "BN" ? <Badge>BN</Badge> : <Badge tone="win">Start</Badge>}
              </span>
              <Num value={p.last_week_points} className="hidden text-right text-sm text-ink-300 md:block" />
              <Num value={p.season_points} className="text-right text-sm text-ink-300" />
            </div>
          ))}
        </div>
      ))}
    </Card>
  );
}

function ScheduleCard({ weeks, teamId, leagueId, startWeek }: { weeks: ScheduleWeek[]; teamId: string; leagueId: string; startWeek: number }) {
  const rows = scheduleRows(weeks, teamId);
  const note = preDraftNote(startWeek);
  return (
    <Card>
      <CardHeader title="Schedule" />
      {note && <p className="mb-2 text-xs text-ink-400">{note}</p>}
      {rows.length === 0 ? (
        <p className="text-sm text-ink-400">The schedule shows up once the league drafts.</p>
      ) : (
        <ul className="divide-y divide-ink-700">
          {rows.map((r) => (
            <li
              key={r.week}
              className={`-mx-2 flex items-center gap-3 rounded-control px-2 py-2 text-sm ${r.next ? "bg-gold/[0.07] ring-1 ring-inset ring-gold/40" : ""}`}
            >
              <span className="num w-8 shrink-0 text-xs text-ink-400">W{r.week}</span>
              <span className="min-w-0 flex-1 truncate">
                {r.opponent ? (
                  <Link href={`/leagues/${leagueId}/teams/${r.opponent.id}`} className="text-ink-300 hover:text-ink-100">
                    vs {r.opponent.name}
                  </Link>
                ) : (
                  <span className="text-ink-400">Bye</span>
                )}
              </span>
              {r.result ? (
                <Badge tone={r.result === "W" ? "win" : r.result === "L" ? "loss" : "neutral"}>{r.result}</Badge>
              ) : r.status === "live" ? (
                <Badge tone="live">Live</Badge>
              ) : r.next ? (
                <Badge tone="you">Next</Badge>
              ) : null}
              <span className="num w-[6.5rem] shrink-0 text-right text-xs text-ink-300">
                {r.status === "upcoming" ? "—" : `${(r.me ?? 0).toFixed(1)} – ${(r.them ?? 0).toFixed(1)}`}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function ProblemText({ problem, fallback, next }: { problem: LoadProblem | null; fallback: string; next: string }) {
  if (problem?.kind === "login") {
    return (
      <p className="text-sm text-ink-300">
        <Link href={`/login?next=${encodeURIComponent(next)}`} className="font-semibold text-gold">
          Log in
        </Link>{" "}
        {problem.text}
      </p>
    );
  }
  return <p className="text-sm text-loss">{problem?.text ?? fallback}</p>;
}

function PageSkeleton() {
  return (
    <div className="mx-auto max-w-6xl space-y-4 px-4 py-6 sm:px-6 lg:px-8">
      <Card>
        <div className="flex items-center gap-4">
          <Skeleton className="h-14 w-14 rounded-full" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-6 w-48" />
            <Skeleton className="h-4 w-32" />
          </div>
        </div>
      </Card>
      <Card>
        <SkeletonRows rows={10} />
      </Card>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────

type TabId = "roster" | "schedule" | "moves" | "news";
const TABS = [
  { id: "roster", label: "Roster" },
  { id: "schedule", label: "Schedule" },
  { id: "moves", label: "Moves" },
  { id: "news", label: "News" },
] as const;

export default function TeamPage() {
  const params = useParams();
  const router = useRouter();
  const leagueId = params.id as string;
  const teamId = params.teamId as string;

  const [data, setData] = useState<PageData | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<TabId>("roster");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [lastWords, setLastWords] = useState("");
  const [saving, setSaving] = useState(false);
  const [claiming, setClaiming] = useState(false);
  const [rename, setRename] = useState<string | null>(null);
  const [editingAvatar, setEditingAvatar] = useState(false);

  useEffect(() => {
    let live = true;
    fetchTeamPage(leagueId, teamId).then((d) => {
      if (!live) return;
      setData(d);
      setError(d.rosterProblem?.text ?? "");
    });
    return () => {
      live = false;
    };
  }, [leagueId, teamId]);

  const team = data?.roster?.team;
  const isMine = !!team && (isCurrentUser(team.owner_id) || isCurrentUser(team.co_owner_id));
  const extras = data?.extras;
  const eliminated = extras?.eliminated_week != null;
  const startWeek = data?.roster?.league_start_week ?? 1;
  const issues = data?.roster?.issues?.length ?? 0;
  const ownerLine = useMemo(() => {
    if (!team) return "";
    if (team.is_cpu) return "CPU-controlled";
    if (isMine) return team.co_owner_id ? "You manage this team with a co-owner" : "You manage this team";
    if (!team.owner_username) return "Unclaimed";
    return team.co_owner_username ? `Managed by ${team.owner_username} and ${team.co_owner_username}` : `Managed by ${team.owner_username}`;
  }, [team, isMine]);

  if (!data) return <PageSkeleton />;
  if (!data.roster || !team) {
    return (
      <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6 lg:px-8">
        <Card>
          <ProblemText problem={data.rosterProblem} fallback={error || "Team not found."} next={`/leagues/${leagueId}/teams/${teamId}`} />
        </Card>
      </div>
    );
  }

  const { record, roster, week } = data.roster;

  async function cancelMove(item: ActivityItem) {
    if (!item.cancel) return;
    setBusyId(item.id);
    try {
      if (item.cancel.type === "trade") await tradesApi.cancel(leagueId, item.cancel.id);
      else await waiversApi.cancelClaim(leagueId, item.cancel.id);
      setData((d) => (d ? { ...d, activity: d.activity.filter((a) => a.id !== item.id) } : d));
    } catch (err) {
      setError(friendlyErrorMessage(err, "Couldn't cancel that. Try again."));
    } finally {
      setBusyId(null);
    }
  }

  async function submitLastWords(e: React.FormEvent) {
    e.preventDefault();
    if (!lastWords.trim()) return;
    setSaving(true);
    try {
      const updated = (await teamsApi.update(teamId, { last_words: lastWords.trim() })) as TeamExtras;
      setData((d) => (d ? { ...d, extras: updated } : d));
    } catch (err) {
      setError(friendlyErrorMessage(err, "Couldn't save that. Try again."));
    } finally {
      setSaving(false);
    }
  }

  async function claimCoOwner() {
    setClaiming(true);
    try {
      await teamsApi.claimCoOwner(teamId);
      const d = await fetchTeamPage(leagueId, teamId);
      setData(d);
    } catch (err) {
      setError(friendlyErrorMessage(err, "Couldn't join as co-owner."));
    } finally {
      setClaiming(false);
    }
  }

  async function saveName(e: React.FormEvent) {
    e.preventDefault();
    const name = rename?.trim();
    if (!name || name === team?.name) return setRename(null);
    setSaving(true);
    try {
      await teamsApi.update(teamId, { name });
      setData(await fetchTeamPage(leagueId, teamId));
      setRename(null);
    } catch (err) {
      setError(friendlyErrorMessage(err, "Couldn't rename the team."));
    } finally {
      setSaving(false);
    }
  }

  async function saveAvatar(url: string) {
    await teamsApi.update(teamId, { avatar_url: url });
    setData(await fetchTeamPage(leagueId, teamId));
    setEditingAvatar(false);
  }

  const canJoinAsCoOwner =
    data.league?.league_type === "two_man" && !team.co_owner_id && team.owner_id !== getCurrentUserId() && !eliminated && isLoggedIn() && !team.is_cpu;

  const rosterCard =
    roster.length === 0 ? (
      <Card>
        <p className="text-sm text-ink-400">No players yet. The roster fills in at the draft.</p>
      </Card>
    ) : (
      <div className="space-y-2">
        {data.roster.lineup_visible === false && (
          <p className="rounded-card border border-ink-700 bg-ink-900 px-4 py-2 text-sm text-ink-300">
            <Link href={`/login?next=${encodeURIComponent(`/leagues/${leagueId}/teams/${teamId}`)}`} className="font-semibold text-gold">
              Log in
            </Link>{" "}
            to see who&apos;s starting.
          </p>
        )}
        <RosterTable rows={roster} week={week} />
      </div>
    );
  const scheduleCard = <ScheduleCard weeks={data.schedule} teamId={teamId} leagueId={leagueId} startWeek={startWeek} />;
  const movesCard = (
    <Card>
      <CardHeader title="Moves" />
      <ActivityFeed items={data.activity} onCancel={cancelMove} busyId={busyId} empty="No trades or claims yet." />
    </Card>
  );
  const newsCard = roster.length > 0 ? <PlayerNewsCard teamId={teamId} /> : null;
  const staffCard =
    isMine && !eliminated ? (
      <Card>
        <CardHeader title="Coaching staff" />
        <CoachStaffPanel teamId={teamId} canManage />
      </Card>
    ) : null;

  return (
    <div className="mx-auto max-w-6xl space-y-4 px-4 py-6 sm:px-6 lg:px-8">
      {eliminated && (
        <Card className="border-loss/40 bg-loss/10">
          <p className="flex items-center gap-2 text-sm font-semibold text-loss">
            <Skull className="h-4 w-4" aria-hidden /> Eliminated in Week {extras?.eliminated_week}
          </p>
          {extras?.last_words ? (
            <p className="mt-2 text-sm italic text-ink-300">&ldquo;{extras.last_words}&rdquo;</p>
          ) : isMine ? (
            <form onSubmit={submitLastWords} className="mt-3 flex gap-2">
              <input
                value={lastWords}
                onChange={(e) => setLastWords(e.target.value)}
                maxLength={280}
                placeholder="Any last words?"
                className="h-9 flex-1 rounded-control border border-ink-700 bg-ink-950 px-3 text-sm text-ink-100 placeholder:text-ink-400"
              />
              <Button type="submit" size="sm" disabled={saving || !lastWords.trim()}>
                {saving ? "Saving" : "Post"}
              </Button>
            </form>
          ) : null}
        </Card>
      )}

      {error && data.roster && (
        <div role="alert" className="rounded-card border border-loss/40 bg-loss/10 px-4 py-3 text-sm text-loss">
          {error}
        </div>
      )}

      {editingAvatar && (
        <AvatarEditor title="Team avatar" currentUrl={team.avatar_url} onSave={saveAvatar} onClose={() => setEditingAvatar(false)} />
      )}

      <Card you={isMine}>
        <div className="flex flex-wrap items-center gap-4">
          {isMine ? (
            <button type="button" onClick={() => setEditingAvatar(true)} aria-label="Change team avatar" className="shrink-0 rounded-full hover:opacity-80">
              <Avatar url={team.avatar_url} size={56} className="border border-ink-700" />
            </button>
          ) : (
            <Avatar url={team.avatar_url} size={56} className="shrink-0 border border-ink-700" />
          )}
          <div className="min-w-0 flex-1 basis-48">
            <div className="flex flex-wrap items-center gap-2">
              {rename !== null ? (
                <form onSubmit={saveName} className="flex items-center gap-1.5">
                  <input
                    autoFocus
                    aria-label="Team name"
                    value={rename}
                    maxLength={60}
                    onChange={(e) => setRename(e.target.value)}
                    onKeyDown={(e) => e.key === "Escape" && setRename(null)}
                    className="h-9 w-56 rounded-control border border-ink-700 bg-ink-950 px-3 text-sm text-ink-100"
                  />
                  <Button type="submit" size="sm" variant="ghost" aria-label="Save name" disabled={saving}>
                    <Check className="h-4 w-4" />
                  </Button>
                  <Button size="sm" variant="ghost" aria-label="Cancel rename" onClick={() => setRename(null)}>
                    <X className="h-4 w-4" />
                  </Button>
                </form>
              ) : (
                <>
                  <h1 className="truncate text-title font-semibold text-ink-100">{team.name}</h1>
                  {isMine && (
                    <button type="button" onClick={() => setRename(team.name)} aria-label="Rename team" className="text-ink-400 hover:text-gold">
                      <Pencil className="h-4 w-4" />
                    </button>
                  )}
                </>
              )}
              <ConferenceBadge
                conference={extras?.conference}
                displayName={conferenceShortLabel(extras?.conference, data.league?.conference_a_name, data.league?.conference_b_name)}
              />
              {data.capEnabled && <SalaryCapBadge />}
              {data.bestBall && <BestBallBadge />}
              {data.bestBall && <ManagementWindowIndicator leagueId={leagueId} />}
              {extras?.partner_team_id && <PartnerBadge onClick={() => router.push(`/leagues/${leagueId}/teams/${extras.partner_team_id}`)} />}
            </div>
            <p className="mt-1 flex flex-wrap items-center gap-1.5 text-sm text-ink-400">
              {team.is_cpu ? <Bot className="h-3.5 w-3.5" aria-hidden /> : <UserCheck className="h-3.5 w-3.5" aria-hidden />}
              {ownerLine}
              {canJoinAsCoOwner && (
                <button type="button" onClick={claimCoOwner} disabled={claiming} className="ml-1 font-medium text-gold hover:text-gold-hi disabled:opacity-50">
                  {claiming ? "Joining" : "Join as co-owner"}
                </button>
              )}
            </p>
          </div>
          <div className="flex w-full shrink-0 gap-2 sm:w-auto">
            {isMine && !eliminated && !data.bestBall && (
              <Link href={`/leagues/${leagueId}/teams/${teamId}/lineup`} className={buttonClasses("primary", "md")}>
                <ListChecks className="h-4 w-4" aria-hidden />
                Set lineup
                {issues > 0 && <span className="num ml-1 rounded-chip bg-ink-950/30 px-1.5 text-xs">{issues}</span>}
              </Link>
            )}
            {!isMine && isLoggedIn() && !eliminated && (
              <Link href={`/leagues/${leagueId}/trades`} className={buttonClasses("secondary", "md")}>
                <ArrowLeftRight className="h-4 w-4" aria-hidden />
                Propose trade
              </Link>
            )}
          </div>
        </div>
        <div className="mt-4 grid grid-cols-3 gap-4 border-t border-ink-700 pt-4 sm:grid-cols-5">
          <StatBlock label="Record">{recordText(record)}</StatBlock>
          <StatBlock label={`Rank of ${record.teams}`}>{record.rank ? ordinal(record.rank) : "—"}</StatBlock>
          <StatBlock label="Streak">{record.streak ?? "—"}</StatBlock>
          <StatBlock label="Pts for">
            <Num value={record.points_for} size="lg" />
          </StatBlock>
          <StatBlock label="Pts against">
            <Num value={record.points_against} size="lg" />
          </StatBlock>
          {data.capEnabled && data.cap && (
            <StatBlock label="Cap space">
              <span className={data.cap.cap_space >= 0 ? "text-ink-100" : "text-loss"}>${data.cap.cap_space.toFixed(1)}</span>
            </StatBlock>
          )}
        </div>
      </Card>

      {/* One render. Mobile shows the chosen tab; desktop shows the roster with a rail. */}
      <div className="lg:hidden">
        <Tabs tabs={TABS} value={tab} onChange={setTab} label="Team sections" />
      </div>
      <div className="mt-3 gap-4 lg:mt-0 lg:grid lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className={`space-y-4 ${tab === "roster" ? "" : "hidden"} lg:block`}>
          {rosterCard}
          {staffCard}
        </div>
        <div className="space-y-4">
          <div className={`${tab === "schedule" ? "" : "hidden"} lg:block`}>{scheduleCard}</div>
          <div className={`${tab === "moves" ? "" : "hidden"} lg:block`}>{movesCard}</div>
          <div className={`${tab === "news" ? "" : "hidden"} lg:block`}>
            {newsCard ?? (
              <Card className="lg:hidden">
                <p className="text-sm text-ink-400">No players yet, so no news.</p>
              </Card>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
