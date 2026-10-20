"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ChevronLeft, ChevronRight, Lock, Sparkles, X } from "lucide-react";
import PlayerLink from "@/components/PlayerLink";
import { InjuryTag, PositionChip } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Num } from "@/components/ui/Num";
import { SkeletonRows } from "@/components/ui/Skeleton";
import { friendlyErrorMessage, isCurrentUser, isLoggedIn, leaguesApi, lineupsApi, nflApi, standingsApi, teamsApi } from "@/lib/api-client";
import {
  applyMove,
  benchIds,
  issuesFor,
  moveWarning,
  playerWarning,
  targetsFor,
  type Issue,
  type LineupPlayer,
  type Pick,
  type Slot,
} from "@/lib/lineup";
import { initialWeek, withWeekParam } from "@/lib/current-week";

interface Game {
  opponent: string;
  home: boolean;
  kickoff_at: string;
  status: "pre" | "in" | "post";
  detail: string;
  locked: boolean;
}

interface RosterPlayer {
  id: string;
  full_name: string;
  position: string;
  team: string;
  injury_status: string | null;
  avatar_url: string | null;
  season_points: number | null;
  last_week_points: number | null;
  game: Game | null;
  on_bye: boolean;
}

interface LineupResponse {
  best_ball: boolean;
  has_lineup_set: boolean;
  slots: Slot[];
  roster: RosterPlayer[];
}

interface ScheduleSide {
  id: string;
  name: string;
  score: number | null;
}

interface Matchup {
  me: ScheduleSide;
  opp: ScheduleSide;
}

const CURRENT_YEAR = new Date().getFullYear();
const POSITION_ORDER = ["QB", "RB", "WR", "TE", "K", "DEF", "DL", "LB", "DB"];
const kickoffFormat = new Intl.DateTimeFormat(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" });

function errorText(err: unknown, fallback: string): string {
  return friendlyErrorMessage(err, fallback);
}

async function fetchLineupPage(teamId: string, leagueId: string, wk: number, year: number) {
  const [lineup, team, league, schedule] = await Promise.all([
    lineupsApi.get(teamId, wk, year).catch(() => null) as Promise<LineupResponse | null>,
    teamsApi.get(teamId).catch(() => null) as Promise<{ name?: string; owner_id?: string | null; co_owner_id?: string | null } | null>,
    leaguesApi.get(leagueId).catch(() => null) as Promise<{ commissioner_id?: string | null; co_commissioner_ids?: string[] | null } | null>,
    standingsApi.getSchedule(leagueId, year, Math.max(14, wk)).catch(() => null) as Promise<{
      schedule?: { week: number; matchups: { team_a: ScheduleSide; team_b: ScheduleSide }[] }[];
    } | null>,
  ]);
  const canEdit =
    isLoggedIn() &&
    (isCurrentUser(team?.owner_id) ||
      isCurrentUser(team?.co_owner_id) ||
      isCurrentUser(league?.commissioner_id) ||
      (league?.co_commissioner_ids || []).some((cid) => isCurrentUser(cid)));
  const m = schedule?.schedule?.find((w) => w.week === wk)?.matchups.find((x) => x.team_a.id === teamId || x.team_b.id === teamId);
  const matchup: Matchup | null = m ? (m.team_a.id === teamId ? { me: m.team_a, opp: m.team_b } : { me: m.team_b, opp: m.team_a }) : null;
  return { lineup, teamName: team?.name || "", canEdit, matchup };
}

function GameMeta({ player }: { player: RosterPlayer }) {
  if (player.on_bye) return <span className="text-ink-400">Bye</span>;
  const g = player.game;
  if (!g) return <span className="text-ink-400">—</span>;
  const when =
    g.status === "in" ? <span className="text-live">Live {g.detail}</span>
    : g.status === "post" ? <span className="text-ink-400">{g.detail || "Final"}</span>
    : <span className="text-ink-400">{kickoffFormat.format(new Date(g.kickoff_at))}</span>;
  return (
    <span className="flex items-center gap-1.5">
      <span className="text-ink-300">{g.home ? "vs" : "@"} {g.opponent}</span>
      {when}
      {g.locked && <Lock className="h-3 w-3 text-ink-400" aria-label="Locked" />}
    </span>
  );
}

type RowMode = "idle" | "picked" | "target" | "dim";

function LineupRow({
  label,
  player,
  mode,
  issue,
  warning,
  canEdit,
  onTap,
}: {
  label: string;
  player: RosterPlayer | null;
  mode: RowMode;
  issue: Issue | undefined;
  warning: string | null;
  canEdit: boolean;
  onTap: () => void;
}) {
  const locked = !!player?.game?.locked;
  const tone = issue ? (issue.kind === "empty" ? "border-l-warn" : "border-l-loss") : "border-l-transparent";
  return (
    <div
      className={`grid grid-cols-[3rem_1fr_auto] items-center gap-3 border-l-2 px-3 py-2 md:grid-cols-[3rem_1fr_11rem_4rem_4rem_5.5rem] ${tone} ${
        mode === "picked" ? "bg-gold/[0.07] ring-1 ring-inset ring-gold" : mode === "target" ? "bg-ink-850 ring-1 ring-inset ring-ink-400" : ""
      } ${mode === "dim" ? "opacity-35" : ""}`}
    >
      <PositionChip pos={label} />
      <div className="min-w-0">
        {player ? (
          <>
            <div className="flex min-w-0 items-center gap-2">
              <PlayerLink id={player.id} className="truncate text-sm font-medium text-ink-100">
                {player.full_name}
              </PlayerLink>
              <span className="shrink-0 text-xs text-ink-400">
                {player.position} · {player.team}
              </span>
              <InjuryTag status={player.injury_status} onBye={player.on_bye} />
            </div>
            <div className="mt-0.5 text-xs md:hidden">
              <GameMeta player={player} />
            </div>
          </>
        ) : (
          <span className="text-sm text-ink-400">Empty</span>
        )}
        {issue && issue.kind !== "empty" && <p className="mt-0.5 text-xs text-loss">{issue.message}</p>}
        {mode === "target" && warning && (
          <p className="mt-0.5 flex items-center gap-1 text-xs text-loss">
            <AlertTriangle className="h-3 w-3 shrink-0" aria-hidden /> {warning}
          </p>
        )}
      </div>
      <div className="hidden text-xs md:block">{player && <GameMeta player={player} />}</div>
      <Num value={player?.last_week_points} className="hidden text-right text-sm text-ink-300 md:block" />
      <Num value={player?.season_points} className="hidden text-right text-sm text-ink-300 md:block" />
      <div className="flex justify-end">
        {canEdit &&
          (locked ? (
            <span className="flex h-8 items-center gap-1 px-2 text-xs text-ink-400">
              <Lock className="h-3 w-3" aria-hidden /> Locked
            </span>
          ) : mode === "target" ? (
            <Button variant="primary" size="sm" onClick={onTap}>
              Swap
            </Button>
          ) : mode === "picked" ? (
            <Button variant="ghost" size="sm" onClick={onTap}>
              Cancel
            </Button>
          ) : (
            <Button size="sm" onClick={onTap} disabled={mode === "dim"}>
              {player ? "Move" : "Fill"}
            </Button>
          ))}
      </div>
    </div>
  );
}

function TableHead({ title }: { title: string }) {
  return (
    <div className="grid grid-cols-[3rem_1fr_auto] gap-3 border-b border-ink-700 px-3 pb-2 text-label font-semibold uppercase text-ink-400 md:grid-cols-[3rem_1fr_11rem_4rem_4rem_5.5rem]">
      <span>Slot</span>
      <span>{title}</span>
      <span className="hidden md:block">Game</span>
      <span className="hidden text-right md:block">Last wk</span>
      <span className="hidden text-right md:block">Season</span>
      <span />
    </div>
  );
}

export default function LineupPage() {
  const params = useParams();
  const leagueId = params.id as string;
  const teamId = params.teamId as string;
  const [year, setYear] = useState(CURRENT_YEAR);
  const [week, setWeek] = useState<number | null>(null);
  const [seasonNotStarted, setSeasonNotStarted] = useState(false);
  const [data, setData] = useState<LineupResponse | null>(null);
  const [slots, setSlots] = useState<Slot[]>([]);
  const [teamName, setTeamName] = useState("");
  const [canEdit, setCanEdit] = useState(false);
  const [matchup, setMatchup] = useState<Matchup | null>(null);
  const [error, setError] = useState("");
  const [pick, setPick] = useState<Pick | null>(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<{ message: string; undo: Slot[] | null } | null>(null);

  useEffect(() => {
    let live = true;
    Promise.all([nflApi.getCurrentWeek().catch(() => null), leaguesApi.get(leagueId).catch(() => null)]).then(([s, l]) => {
      if (!live) return;
      const draftStatus = (l as { draft_status?: string } | null)?.draft_status;
      const notStarted = !!draftStatus && draftStatus !== "completed";
      setSeasonNotStarted(notStarted);
      if (s?.season) setYear(s.season);
      setWeek(
        initialWeek({ param: new URLSearchParams(window.location.search).get("week"), state: s, draftComplete: !notStarted }),
      );
    });
    return () => {
      live = false;
    };
  }, [leagueId]);

  // Keep the shown week in the URL (?week=) so a reload or a shared link
  // opens the same week instead of snapping back to the live one.
  useEffect(() => {
    if (week === null) return;
    const next = withWeekParam(window.location.search, week);
    if (next !== window.location.search) window.history.replaceState(window.history.state, "", next);
  }, [week]);

  useEffect(() => {
    if (week === null) return;
    let live = true;
    fetchLineupPage(teamId, leagueId, week, year).then((r) => {
      if (!live) return;
      setCanEdit(r.canEdit);
      setTeamName(r.teamName);
      setMatchup(r.matchup);
      setError(r.lineup ? "" : "Couldn't load this lineup. Try again in a moment.");
      if (r.lineup) {
        setData(r.lineup);
        setSlots(r.lineup.slots);
      }
      setPick(null);
    });
    return () => {
      live = false;
    };
  }, [teamId, leagueId, week, year]);

  useEffect(() => {
    if (!pick) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setPick(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pick]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 6000);
    return () => clearTimeout(t);
  }, [toast]);

  const roster = useMemo(() => data?.roster ?? [], [data]);
  const byId = useMemo(() => Object.fromEntries(roster.map((p) => [p.id, p])), [roster]);
  const players = useMemo(
    () =>
      Object.fromEntries(
        roster.map((p): [string, LineupPlayer] => [
          p.id,
          { id: p.id, name: p.full_name, position: p.position, injuryStatus: p.injury_status, locked: !!p.game?.locked, onBye: p.on_bye },
        ]),
      ),
    [roster],
  );
  const bench = useMemo(
    () =>
      benchIds(slots, roster.map((p) => p.id)).sort(
        (a, b) => POSITION_ORDER.indexOf(byId[a].position) - POSITION_ORDER.indexOf(byId[b].position),
      ),
    [slots, roster, byId],
  );
  const issues = useMemo(() => issuesFor(slots, players), [slots, players]);
  const targets = pick ? targetsFor(slots, pick, players, bench) : null;
  const editable = canEdit && !data?.best_ball;
  const pickedPlayer =
    pick?.kind === "bench" ? players[pick.playerId] : pick?.kind === "slot" ? players[slots[pick.index]?.player_id ?? ""] : undefined;
  const pickedWarning = pick?.kind === "bench" && pickedPlayer ? playerWarning(pickedPlayer)?.message ?? null : null;

  function warningFor(row: Pick): string | null {
    if (!pick || !targets) return null;
    const isTarget = row.kind === "slot" ? targets.slots.has(row.index) : targets.bench.has(row.playerId);
    return isTarget ? moveWarning(slots, pick, row, players) : null;
  }

  async function save(next: Slot[], message: string, undo: Slot[] | null) {
    if (week === null) return;
    const prev = slots;
    setSlots(next);
    setPick(null);
    setBusy(true);
    try {
      const res = (await lineupsApi.setSlots(teamId, week, year, next)) as { slots: Slot[]; warnings?: string[] };
      setSlots(res.slots);
      setData((d) => (d ? { ...d, has_lineup_set: true } : d));
      setError("");
      const added = (res.warnings ?? []).filter((w) => !issues.some((i) => i.message === w));
      setToast({ message: added.length ? `${message}. ${added[0]}` : message, undo });
    } catch (err) {
      setSlots(prev);
      setError(errorText(err, "Couldn't save that move."));
    } finally {
      setBusy(false);
    }
  }

  function tap(row: Pick) {
    if (busy) return;
    if (!pick) {
      setPick(row);
      return;
    }
    const same = pick.kind === row.kind && (row.kind === "slot" ? pick.kind === "slot" && pick.index === row.index : pick.kind === "bench" && pick.playerId === row.playerId);
    if (same) {
      setPick(null);
      return;
    }
    const legal = row.kind === "slot" ? targets?.slots.has(row.index) : targets?.bench.has(row.playerId);
    if (!legal) {
      setPick(row);
      return;
    }
    save(applyMove(slots, pick, row), "Lineup saved", slots);
  }

  async function autoFill() {
    if (week === null) return;
    setBusy(true);
    setPick(null);
    const prev = slots;
    try {
      const res = (await lineupsApi.optimize(teamId, week, year)) as { slots: Slot[]; skipped_inactive?: string[] };
      setSlots(res.slots);
      setData((d) => (d ? { ...d, has_lineup_set: true } : d));
      setError("");
      const skipped = res.skipped_inactive?.length ? ` Skipped ${res.skipped_inactive.join(", ")}.` : "";
      setToast({ message: `Auto-filled your best lineup.${skipped}`, undo: prev });
    } catch (err) {
      setError(errorText(err, "Auto-fill didn't work. Try again."));
    } finally {
      setBusy(false);
    }
  }

  function modeFor(row: Pick): RowMode {
    if (!pick || !targets) return "idle";
    const isPicked = pick.kind === row.kind && (row.kind === "slot" ? pick.kind === "slot" && pick.index === row.index : pick.kind === "bench" && pick.playerId === row.playerId);
    if (isPicked) return "picked";
    const legal = row.kind === "slot" ? targets.slots.has(row.index) : targets.bench.has(row.playerId);
    return legal ? "target" : "dim";
  }

  const pickedName =
    pick?.kind === "bench" ? byId[pick.playerId]?.full_name : pick?.kind === "slot" ? byId[slots[pick.index]?.player_id ?? ""]?.full_name : null;
  const pickedSlot = pick?.kind === "slot" ? slots[pick.index]?.slot : null;

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 sm:px-6 lg:px-8">
      <header className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <p className="text-label font-semibold uppercase text-ink-400">Lineup</p>
          <h1 className="truncate text-2xl font-semibold text-ink-100 md:text-title">{teamName || " "}</h1>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center rounded-control border border-ink-700 bg-ink-900">
            <button
              type="button"
              aria-label="Previous week"
              onClick={() => setWeek((w) => (w ? Math.max(1, w - 1) : w))}
              disabled={!week || week <= 1}
              className="flex h-8 w-8 items-center justify-center text-ink-300 hover:text-ink-100 disabled:opacity-30"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="num w-16 text-center text-sm text-ink-100">{week ? `Week ${week}` : "—"}</span>
            <button
              type="button"
              aria-label="Next week"
              onClick={() => setWeek((w) => (w ? Math.min(18, w + 1) : w))}
              disabled={!week || week >= 18}
              className="flex h-8 w-8 items-center justify-center text-ink-300 hover:text-ink-100 disabled:opacity-30"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
          {editable && (
            <Button size="sm" onClick={autoFill} disabled={busy}>
              <Sparkles className="h-3.5 w-3.5" aria-hidden /> Auto-fill
            </Button>
          )}
        </div>
      </header>

      {matchup && (
        <Card className="mb-4">
          <div className="flex items-center justify-between gap-4">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-gold">{matchup.me.name}</p>
              <Num value={matchup.me.score} digits={2} size="lg" className="text-ink-100" />
            </div>
            <span className="text-xs text-ink-400">vs</span>
            <div className="min-w-0 text-right">
              <p className="truncate text-sm font-medium text-ink-300">{matchup.opp.name}</p>
              <Num value={matchup.opp.score} digits={2} size="lg" className="text-ink-300" />
            </div>
          </div>
          <p className="mt-2 text-xs text-ink-400">Each player locks at his own game&apos;s kickoff.</p>
        </Card>
      )}

      {error && (
        <div role="alert" className="mb-4 rounded-card border border-loss/40 bg-loss/10 px-4 py-3 text-sm text-loss">
          {error}
        </div>
      )}
      {seasonNotStarted && (
        <p className="mb-4 rounded-card border border-ink-700 bg-ink-900 px-4 py-3 text-sm text-ink-300">
          This league&apos;s draft isn&apos;t done yet, so this is the Week 1 lineup.
        </p>
      )}
      {data?.best_ball && (
        <p className="mb-4 rounded-card border border-ink-700 bg-ink-900 px-4 py-3 text-sm text-ink-300">
          Best ball league. Your highest-scoring legal lineup is picked for you after each week&apos;s games.
        </p>
      )}
      {data && !data.best_ball && !data.has_lineup_set && (
        <p className="mb-4 rounded-card border border-ink-700 bg-ink-900 px-4 py-3 text-sm text-ink-300">
          No lineup saved for Week {week} yet. The default lineup below scores unless you change it, and any change saves it as
          yours.
        </p>
      )}
      {data && !canEdit && (
        <p className="mb-4 rounded-card border border-ink-700 bg-ink-900 px-4 py-3 text-sm text-ink-300">
          {isLoggedIn() ? (
            "Only this team's owner or the commissioner can change this lineup."
          ) : (
            <>
              <Link href={`/login?next=${encodeURIComponent(`/leagues/${leagueId}/teams/${teamId}/lineup`)}`} className="font-semibold text-gold">
                Log in
              </Link>{" "}
              to manage your team.
            </>
          )}
        </p>
      )}

      {editable && issues.length > 0 && (
        <Card className="mb-4 border-loss/40">
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-loss" aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-ink-100">
                {issues.length === 1 ? "1 problem is costing you points" : `${issues.length} problems are costing you points`}
              </p>
              <ul className="mt-2 space-y-1.5">
                {issues.map((i) => (
                  <li key={`${i.kind}-${i.slotIndex}`} className="flex items-center justify-between gap-3 text-sm text-ink-300">
                    <span>{i.message}</span>
                    {!players[i.playerId ?? ""]?.locked && (
                      <Button size="sm" variant="ghost" onClick={() => setPick({ kind: "slot", index: i.slotIndex })}>
                        Fix
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </Card>
      )}

      {pick && targets && (
        <div className="sticky top-16 z-30 mb-3 flex flex-wrap items-center justify-between gap-2 rounded-card border border-gold/40 bg-ink-900 px-4 py-2.5">
          <p className="text-sm text-ink-100">
            {pickedName ? `Pick where ${pickedName} goes.` : `Pick a player for ${pickedSlot}.`}
            {pickedWarning && <span className="text-loss"> {pickedWarning}</span>}
            {targets.slots.size + targets.bench.size === 0 && <span className="text-ink-400"> No legal moves.</span>}
          </p>
          <div className="flex gap-2">
            {targets.toBench && (
              <Button size="sm" onClick={() => pick && save(applyMove(slots, pick, "bench"), "Moved to bench", slots)}>
                Move to bench
              </Button>
            )}
            <Button size="sm" variant="ghost" onClick={() => setPick(null)}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      {!data && !error ? (
        <Card>
          <SkeletonRows rows={9} />
        </Card>
      ) : (
        data && (
          <div className="space-y-4">
            <Card className="px-0 lg:px-0">
              <TableHead title="Starters" />
              <div className="divide-y divide-ink-700">
                {slots.map((s, i) => (
                  <LineupRow
                    key={`${s.slot}-${i}`}
                    label={s.slot}
                    player={s.player_id ? byId[s.player_id] ?? null : null}
                    mode={modeFor({ kind: "slot", index: i })}
                    issue={issues.find((x) => x.slotIndex === i)}
                    warning={warningFor({ kind: "slot", index: i })}
                    canEdit={editable}
                    onTap={() => tap({ kind: "slot", index: i })}
                  />
                ))}
              </div>
            </Card>
            <Card className="px-0 lg:px-0">
              <TableHead title={`Bench (${bench.length})`} />
              {bench.length === 0 ? (
                <p className="px-4 py-6 text-center text-sm text-ink-400">Nobody on the bench.</p>
              ) : (
                <div className="divide-y divide-ink-700">
                  {bench.map((id) => (
                    <LineupRow
                      key={id}
                      label="BN"
                      player={byId[id]}
                      mode={modeFor({ kind: "bench", playerId: id })}
                      issue={undefined}
                      warning={warningFor({ kind: "bench", playerId: id })}
                      canEdit={editable}
                      onTap={() => tap({ kind: "bench", playerId: id })}
                    />
                  ))}
                </div>
              )}
            </Card>
          </div>
        )
      )}

      {toast && (
        <div
          role="status"
          aria-live="polite"
          className="fixed inset-x-4 bottom-20 z-50 mx-auto flex max-w-md items-center justify-between gap-3 rounded-card border border-ink-600 bg-ink-850 px-4 py-3 text-sm text-ink-100 shadow-xl md:bottom-6"
        >
          <span>{toast.message}</span>
          <div className="flex items-center gap-1">
            {toast.undo && (
              <Button size="sm" variant="ghost" onClick={() => toast.undo && save(toast.undo, "Undone", null)}>
                Undo
              </Button>
            )}
            <button type="button" aria-label="Dismiss" onClick={() => setToast(null)} className="p-1 text-ink-400 hover:text-ink-100">
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
