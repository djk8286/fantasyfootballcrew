"use client";

import PlayerLink from "@/components/PlayerLink";
import { useState, useEffect, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { teamsApi, leaguesApi, playersApi, standingsApi, teamNewsApi, getCurrentUserId, isCurrentUser, isLoggedIn } from "@/lib/api-client";
import Avatar from "@/components/Avatar";
import PositionBadge, { POSITION_ORDER } from "@/components/PositionBadge";
import { PlayerAvatar, PlayerCardOverlay } from "@/components/PlayerAvatar";
import CoachStaffPanel from "@/components/CoachStaffPanel";
import { ConferenceBadge, conferenceShortLabel, SalaryCapBadge, BestBallBadge, PartnerBadge } from "@/components/LeagueBadges";
import ManagementWindowIndicator from "@/components/ManagementWindowIndicator";
import {
  Bot,
  UserCheck,
  Trophy,
  Swords,
  Calendar,
  ListChecks,
  Shield,
  Skull,
  DollarSign,
  Newspaper,
} from "lucide-react";
import type { HoverPlayer, PlayerHoverHandler } from "@/components/PlayerAvatar";

// ─── Interfaces ───────────────────────────────────────────────

interface Team {
  id: string;
  name: string;
  owner_id: string | null;
  co_owner_id: string | null;
  partner_team_id: string | null;
  league_id: string;
  avatar_url: string | null;
  is_cpu: boolean;
  conference: string | null;
  wins: number;
  losses: number;
  ties: number;
  points_for: number;
  points_against: number;
  roster: string[] | null;
  eliminated_week: number | null;
  last_words: string | null;
}

interface LeagueData {
  id: string;
  name: string;
  league_type?: string;
  conference_a_name?: string | null;
  conference_b_name?: string | null;
}

interface RosterPlayer {
  id: string;
  full_name: string;
  first_name: string;
  last_name: string;
  position: string;
  team: string | null;
  avatar_url: string | null;
  sleeper_id: string | null;
  season_points: number | null;
  season_points_year: number | null;
}

interface ScheduleTeamEntry {
  id: string;
  name: string;
  score: number | null;
  projected_score: number | null;
  is_projected: boolean;
}

interface ScheduleMatchup {
  team_a: ScheduleTeamEntry;
  team_b: ScheduleTeamEntry;
}

interface ScheduleWeek {
  week: number;
  matchups: ScheduleMatchup[];
}

// Salary-Cap + Contract Leagues (Phase 5) -- mirrors
// salary_cap_service.team_cap_summary's response shape exactly.
interface CapSummary {
  cap_total: number;
  contracts_total: number;
  dead_money_total: number;
  cap_used: number;
  cap_space: number;
  max_roster_size: number;
  roster_size: number;
  contracts: { player_id: string; salary: number; contract_years: number; signed_year: number }[];
}

const CURRENT_YEAR = new Date().getFullYear();

// ─── Player News (2026-09-22, real articles 2026-10-18) ─────────────────
// Real ESPN articles about this roster's players (headline links straight
// to the published story) plus the daily digest from backend
// team_news_service.py. Ungated public read. A 404 just means there's no
// digest and no article yet -- rendered as an empty state, not an error.

interface TeamNewsArticle {
  id: string;
  player_id: string;
  player_name: string;
  headline: string;
  url: string;
  source: string;
  published_at: string;
}

interface TeamNews {
  content: string | null;
  updated_at: string | null;
  articles?: TeamNewsArticle[];
}

function timeAgo(iso: string): string {
  // Backend may send a naive timestamp (SQLite); treat it as UTC.
  const t = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`).getTime();
  const mins = Math.max(0, Math.round((Date.now() - t) / 60000));
  if (mins < 60) return `${mins || 1}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

function PlayerNewsPanel({ teamId, hasRoster }: { teamId: string; hasRoster: boolean }) {
  const [news, setNews] = useState<TeamNews | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    teamNewsApi
      .get(teamId)
      .then((data) => setNews(data as TeamNews))
      .catch(() => setNews(null))
      .finally(() => setLoading(false));
  }, [teamId]);

  if (!hasRoster) return null;

  const articles = news?.articles || [];

  return (
    <div className="bg-surface-800 border border-surface-700 rounded-2xl p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-white flex items-center gap-2">
          <Newspaper className="w-4 h-4 text-gold-400" />
          Player News
        </h3>
      </div>
      {loading ? (
        <div className="flex items-center justify-center py-6">
          <div className="w-5 h-5 border-2 border-gold-400 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : !news || (!news.content && articles.length === 0) ? (
        <p className="text-surface-500 text-sm">
          No recent news for this roster yet -- check back after the next refresh.
        </p>
      ) : (
        <div className="space-y-4">
          {articles.length > 0 && (
            <ul className="divide-y divide-surface-700/60">
              {articles.map((a) => (
                <li key={a.id} className="py-2.5 first:pt-0 last:pb-0">
                  <a
                    href={a.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm text-white hover:text-gold-400 transition-colors font-medium leading-snug"
                  >
                    {a.headline}
                  </a>
                  <div className="mt-0.5 text-[11px] text-surface-500">
                    <span className="text-surface-300">{a.player_name}</span> &middot; {a.source} &middot;{" "}
                    <time dateTime={a.published_at}>{timeAgo(a.published_at)}</time>
                  </div>
                </li>
              ))}
            </ul>
          )}
          {news.content && (
            <div>
              <div className="flex items-center gap-1.5 mb-1.5 text-[10px] font-bold uppercase tracking-wider text-purple-300">
                <Bot className="w-3 h-3" /> Roster digest
              </div>
              <div className="p-4 rounded-xl border bg-purple-400/5 border-purple-400/20 text-surface-200 text-sm leading-relaxed whitespace-pre-wrap">
                {news.content}
              </div>
              {news.updated_at && (
                <p className="text-surface-500 text-[10px] mt-2">
                  Updated {new Date(news.updated_at).toLocaleString()}
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function TeamPage() {
  const params = useParams();
  const router = useRouter();
  const leagueId = params.id as string;
  const teamId = params.teamId as string;

  const [team, setTeam] = useState<Team | null>(null);
  const [league, setLeague] = useState<LeagueData | null>(null);
  const [playersById, setPlayersById] = useState<Record<string, RosterPlayer>>({});
  const [schedule, setSchedule] = useState<ScheduleWeek[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [claimingCoOwner, setClaimingCoOwner] = useState(false);
  const [lastWordsInput, setLastWordsInput] = useState("");
  const [savingLastWords, setSavingLastWords] = useState(false);
  const [capEnabled, setCapEnabled] = useState(false);
  const [cap, setCap] = useState<CapSummary | null>(null);
  const [bestBallEnabled, setBestBallEnabled] = useState(false);

  const currentUserId = getCurrentUserId();

  const handleClaimCoOwner = async () => {
    setClaimingCoOwner(true);
    try {
      const updated = await teamsApi.claimCoOwner(teamId);
      setTeam(updated as Team);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to claim co-owner slot");
    }
    setClaimingCoOwner(false);
  };

  const handleSubmitLastWords = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!lastWordsInput.trim()) return;
    setSavingLastWords(true);
    try {
      const updated = await teamsApi.update(teamId, { last_words: lastWordsInput.trim() });
      setTeam(updated as Team);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save last words");
    }
    setSavingLastWords(false);
  };

  useEffect(() => {
    Promise.all([
      teamsApi.get(teamId) as Promise<Team>,
      leaguesApi.get(leagueId) as Promise<LeagueData>,
      // Team.wins/losses columns are never written server-side; the real
      // record comes from the standings endpoint (computed from weekly scores).
      standingsApi.getStandings(leagueId).catch(() => null),
    ])
      .then(([t, l, st]) => {
        const rows = ((st as { standings?: Array<{ team_id: string; wins: number; losses: number; ties: number }> } | null)?.standings) || [];
        const rec = rows.find((r) => r.team_id === t.id);
        setTeam(rec ? { ...t, wins: rec.wins, losses: rec.losses, ties: rec.ties } : t);
        setLeague(l);
      })
      .catch(() => setError("Failed to load team"))
      .finally(() => setLoading(false));

    standingsApi
      .getSchedule(leagueId, CURRENT_YEAR)
      .then((data) => setSchedule((data as { schedule: ScheduleWeek[] }).schedule || []))
      .catch(() => {});

    // Salary-Cap + Contract Leagues (Phase 5) -- only fetch the (join-
    // heavy) cap summary when the league actually has the feature on.
    leaguesApi
      .getSalaryCapSettings(leagueId)
      .then((data) => {
        const enabled = !!(data as { enabled?: boolean })?.enabled;
        setCapEnabled(enabled);
        if (enabled) {
          teamsApi.getCap(teamId).then((c) => setCap(c as CapSummary)).catch(() => {});
        }
      })
      .catch(() => {});

    leaguesApi
      .getBestBallSettings(leagueId)
      .then((data) => setBestBallEnabled(!!(data as { enabled?: boolean })?.enabled))
      .catch(() => {});
  }, [leagueId, teamId]);

  // Resolve roster player IDs into actual player data (same pattern as the
  // league page's roster grid).
  useEffect(() => {
    if (!team) return;
    const ids = (team.roster || []).filter((pid) => !(pid in playersById));
    if (ids.length === 0) return;

    Promise.all(
      ids.map((pid) =>
        playersApi
          .get(pid, leagueId)
          .then((p) => {
            const raw = p as Omit<RosterPlayer, "full_name">;
            const full_name = `${raw.first_name ?? ""} ${raw.last_name ?? ""}`.trim() || "Unknown Player";
            return [pid, { ...raw, full_name } as RosterPlayer] as const;
          })
          .catch(() => [pid, null] as const),
      ),
    ).then((pairs) => {
      setPlayersById((prev) => {
        const next = { ...prev };
        for (const [pid, p] of pairs) if (p) next[pid] = p;
        return next;
      });
    });
  }, [team, playersById, leagueId]);

  // Fixed hover card state -- same pattern the draft room already uses.
  const [hoveredPlayer, setHoveredPlayer] = useState<RosterPlayer | null>(null);
  const [hoverPos, setHoverPos] = useState<{ x: number; y: number } | null>(null);
  const handlePlayerHover = useCallback((player: RosterPlayer | null, el: HTMLElement | null) => {
    if (player && el) {
      setHoveredPlayer(player);
      const rect = el.getBoundingClientRect();
      setHoverPos({ x: rect.left + rect.width / 2, y: rect.top });
    } else {
      setHoveredPlayer(null);
      setHoverPos(null);
    }
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen bg-surface-900 flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-gold-400 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (error || !team) {
    return (
      <div className="min-h-screen bg-surface-900 flex items-center justify-center">
        <p className="text-red-400">{error || "Team not found"}</p>
      </div>
    );
  }

  const roster = (team.roster || []).map((pid) => playersById[pid]).filter(Boolean) as RosterPlayer[];
  const salaryByPlayerId = new Map((cap?.contracts || []).map((c) => [c.player_id, c.salary]));
  const rosterByPos: Record<string, RosterPlayer[]> = {};
  roster.forEach((p) => {
    if (!rosterByPos[p.position]) rosterByPos[p.position] = [];
    rosterByPos[p.position].push(p);
  });

  // This team's matchup each week, whichever side of the pairing it's on.
  const myMatchups = schedule
    .map((wk) => {
      const m = wk.matchups.find((mm) => mm.team_a.id === teamId || mm.team_b.id === teamId);
      if (!m) return null;
      const me = m.team_a.id === teamId ? m.team_a : m.team_b;
      const opp = m.team_a.id === teamId ? m.team_b : m.team_a;
      return { week: wk.week, me, opp };
    })
    .filter((x): x is { week: number; me: ScheduleTeamEntry; opp: ScheduleTeamEntry } => !!x);

  return (
    <div className="min-h-screen bg-surface-900">
      <div className="sticky top-0 z-40 bg-surface-900/95 backdrop-blur-md border-b border-surface-700">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-3 flex items-center gap-3">
          <h1 className="text-lg font-semibold text-white">{league?.name} — Team</h1>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        {/* Guillotine (Phase 4): elimination banner + optional "last
            words" -- an eliminated manager can leave a short farewell
            message once, shown here and on the standings page's
            Elimination History section. */}
        {team.eliminated_week != null && (
          <div className="bg-red-500/10 border border-red-500/20 rounded-2xl p-5">
            <div className="flex items-center gap-2 text-red-400 font-semibold text-sm">
              <Skull className="w-4 h-4" />
              Eliminated in Week {team.eliminated_week}
            </div>
            {team.last_words ? (
              <p className="text-surface-300 text-sm mt-2 italic">&ldquo;{team.last_words}&rdquo;</p>
            ) : isCurrentUser(team.owner_id) || isCurrentUser(team.co_owner_id) ? (
              <form onSubmit={handleSubmitLastWords} className="mt-3 flex gap-2">
                <input
                  value={lastWordsInput}
                  onChange={(e) => setLastWordsInput(e.target.value)}
                  maxLength={280}
                  placeholder="Any last words?"
                  className="flex-1 bg-surface-900 border border-surface-700 rounded-lg px-3 py-2 text-sm text-white placeholder:text-surface-600"
                />
                <button
                  type="submit"
                  disabled={savingLastWords || !lastWordsInput.trim()}
                  className="text-sm text-gold-400 hover:text-gold-300 font-medium disabled:opacity-50 shrink-0"
                >
                  {savingLastWords ? "Saving…" : "Submit"}
                </button>
              </form>
            ) : null}
          </div>
        )}

        {/* Team header */}
        <div className="bg-surface-800 border border-surface-700 rounded-2xl p-6 flex items-center gap-4 flex-wrap gap-y-4">
          <Avatar url={team.avatar_url} size={64} className="border border-surface-700/50" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <h2 className="text-2xl font-bold text-white truncate">{team.name}</h2>
              <ConferenceBadge
                conference={team.conference}
                displayName={conferenceShortLabel(team.conference, league?.conference_a_name, league?.conference_b_name)}
              />
              {capEnabled && <SalaryCapBadge />}
              {bestBallEnabled && <BestBallBadge />}
              {bestBallEnabled && <ManagementWindowIndicator leagueId={leagueId} />}
              {team.partner_team_id && (
                <PartnerBadge onClick={() => router.push(`/leagues/${leagueId}/teams/${team.partner_team_id}`)} />
              )}
            </div>
            <p className="text-surface-400 text-sm flex items-center gap-1.5 mt-1 flex-wrap">
              {team.is_cpu ? (
                <>
                  <Bot className="w-3.5 h-3.5" /> CPU-controlled
                </>
              ) : (
                <>
                  <UserCheck className="w-3.5 h-3.5" />
                  {isCurrentUser(team.owner_id) ? "You own this team" : "Owner-managed"}
                  {team.co_owner_id && (
                    <span className="text-surface-500">
                      {" "}
                      &middot; {isCurrentUser(team.co_owner_id) ? "you're co-owner" : "has a co-owner"}
                    </span>
                  )}
                  {/* Co-Owner (2-Man Teams) only makes sense for TWO_MAN
                      leagues -- see teams.py's matching server-side gate. */}
                  {league?.league_type === "two_man" && !team.co_owner_id && team.owner_id !== currentUserId && team.eliminated_week == null && isLoggedIn() && (
                    <button
                      onClick={handleClaimCoOwner}
                      disabled={claimingCoOwner}
                      className="ml-1 text-[11px] text-gold-400 hover:text-gold-300 transition-colors font-medium underline decoration-dotted disabled:opacity-50"
                    >
                      {claimingCoOwner ? "Joining…" : "Join as Co-Owner"}
                    </button>
                  )}
                </>
              )}
            </p>
          </div>
          <div className="flex gap-6 text-center shrink-0">
            <div>
              <div className="text-xl font-bold text-white">
                {team.wins}-{team.losses}{team.ties > 0 ? `-${team.ties}` : ""}
              </div>
              <div className="text-[10px] text-surface-500 uppercase tracking-wider">Record</div>
            </div>
            <div>
              <div className="text-xl font-bold text-white">{team.points_for.toFixed(1)}</div>
              <div className="text-[10px] text-surface-500 uppercase tracking-wider">Points For</div>
            </div>
            <div>
              <div className="text-xl font-bold text-white">{team.points_against.toFixed(1)}</div>
              <div className="text-[10px] text-surface-500 uppercase tracking-wider">Points Against</div>
            </div>
            {capEnabled && cap && (
              <div>
                <div className={`text-xl font-bold ${cap.cap_space >= 0 ? "text-gold-400" : "text-red-400"}`}>
                  ${cap.cap_space.toFixed(1)}
                </div>
                <div className="text-[10px] text-surface-500 uppercase tracking-wider">Cap Space</div>
              </div>
            )}
          </div>
          {(isCurrentUser(team.owner_id) || isCurrentUser(team.co_owner_id)) && team.eliminated_week == null && (
            <Link
              href={`/leagues/${leagueId}/teams/${teamId}/lineup`}
              className="inline-flex items-center gap-2 bg-gold-400 hover:bg-gold-300 text-surface-900 px-4 py-2.5 rounded-xl font-semibold text-sm transition-all shrink-0"
            >
              <ListChecks className="w-4 h-4" />
              Set Lineup
            </Link>
          )}
        </div>

        {/* Roster */}
        <div className="bg-surface-800 border border-surface-700 rounded-2xl p-6">
          <h3 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
            <Trophy className="w-4 h-4 text-gold-400" />
            Roster
          </h3>
          {(team.roster || []).length === 0 ? (
            <p className="text-surface-500 text-sm">No players drafted yet.</p>
          ) : roster.length < (team.roster || []).length ? (
            <p className="text-surface-500 text-sm">Loading roster…</p>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1">
              {POSITION_ORDER.filter((pos) => rosterByPos[pos]).map((pos) => (
                <div key={pos} className="contents">
                  {rosterByPos[pos].map((p) => (
                    <div key={p.id} className="flex items-center gap-2 py-1.5 border-b border-surface-800/50">
                      <PlayerAvatar player={p as unknown as HoverPlayer} size="sm" onHover={handlePlayerHover as unknown as PlayerHoverHandler} />
                      <PlayerLink id={p.id} className="text-sm text-white truncate flex-1">{p.full_name}</PlayerLink>
                      {p.season_points != null && (
                        <span className="text-[10px] text-gold-400/80 font-semibold">
                          {Math.round(p.season_points * 10) / 10}
                        </span>
                      )}
                      {capEnabled && salaryByPlayerId.has(p.id) && (
                        <span className="text-[10px] text-blue-400/80 font-semibold">
                          ${salaryByPlayerId.get(p.id)}
                        </span>
                      )}
                      <span className="text-[10px] text-surface-500">{p.team}</span>
                      <PositionBadge pos={p.position} />
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Player News -- see PlayerNewsPanel above */}
        <PlayerNewsPanel teamId={teamId} hasRoster={(team.roster || []).length > 0} />

        {/* Coaching Staff -- was previously invisible anywhere a team
            owner could see it themselves; only the commissioner's admin
            tab could show/manage coaches at all. The list itself renders
            for any visitor (matches list_coaches being a public read,
            same as Roster/Schedule above); management controls are
            gated the same way "Set Lineup" already is. */}
        <div className="bg-surface-800 border border-surface-700 rounded-2xl p-6">
          <h3 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
            <Shield className="w-4 h-4 text-gold-400" />
            Coaching Staff
          </h3>
          <CoachStaffPanel
            teamId={teamId}
            canManage={(isCurrentUser(team.owner_id) || isCurrentUser(team.co_owner_id)) && team.eliminated_week == null}
          />
        </div>

        {/* Schedule / results */}
        <div className="bg-surface-800 border border-surface-700 rounded-2xl p-6">
          <h3 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
            <Calendar className="w-4 h-4 text-gold-400" />
            Schedule
          </h3>
          {myMatchups.length === 0 ? (
            <p className="text-surface-500 text-sm">Schedule not available yet.</p>
          ) : (
            <div className="space-y-1.5">
              {myMatchups.map(({ week, me, opp }) => {
                const decided = !me.is_projected && !opp.is_projected;
                const won = decided && (me.score ?? 0) > (opp.score ?? 0);
                const lost = decided && (me.score ?? 0) < (opp.score ?? 0);
                return (
                  <div
                    key={week}
                    className="flex items-center justify-between px-3 py-2 rounded-lg border border-surface-700 bg-surface-900 text-sm"
                  >
                    <span className="text-surface-500 text-xs font-mono w-14 shrink-0">Week {week}</span>
                    <div className="flex items-center gap-2 flex-1 min-w-0 justify-center">
                      <Swords className="w-3.5 h-3.5 text-surface-600 shrink-0" />
                      <Link
                        href={`/leagues/${leagueId}/teams/${opp.id}`}
                        className="text-surface-300 hover:text-gold-400 transition-colors truncate"
                      >
                        vs {opp.name}
                      </Link>
                    </div>
                    <div className="flex items-center gap-2 shrink-0 w-32 justify-end">
                      <span className={won ? "text-green-400 font-semibold" : lost ? "text-red-400 font-semibold" : "text-surface-400"}>
                        {me.score ?? me.projected_score ?? "—"}
                      </span>
                      <span className="text-surface-600">-</span>
                      <span className="text-surface-400">{opp.score ?? opp.projected_score ?? "—"}</span>
                      {me.is_projected && (
                        <span className="text-[9px] text-surface-600 uppercase">proj</span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      <PlayerCardOverlay player={hoveredPlayer} position={hoverPos} onDismiss={() => handlePlayerHover(null, null)} />
    </div>
  );
}
