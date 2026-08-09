"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { teamsApi, leaguesApi, playersApi, standingsApi } from "@/lib/api-client";
import { getAvatarStyle } from "@/lib/team-avatars";
import PositionBadge, { POSITION_ORDER } from "@/components/PositionBadge";
import { PlayerAvatar, PlayerCardOverlay } from "@/components/PlayerAvatar";
import {
  ChevronLeft,
  Bot,
  UserCheck,
  Trophy,
  Swords,
  Calendar,
} from "lucide-react";

// ─── Interfaces ───────────────────────────────────────────────

interface Team {
  id: string;
  name: string;
  owner_id: string | null;
  co_owner_id: string | null;
  league_id: string;
  avatar_url: string | null;
  is_cpu: boolean;
  wins: number;
  losses: number;
  ties: number;
  points_for: number;
  points_against: number;
  roster: string[] | null;
}

interface LeagueData {
  id: string;
  name: string;
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

const CURRENT_YEAR = new Date().getFullYear();

export default function TeamPage() {
  const params = useParams();
  const leagueId = params.id as string;
  const teamId = params.teamId as string;

  const [team, setTeam] = useState<Team | null>(null);
  const [league, setLeague] = useState<LeagueData | null>(null);
  const [playersById, setPlayersById] = useState<Record<string, RosterPlayer>>({});
  const [schedule, setSchedule] = useState<ScheduleWeek[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      teamsApi.get(teamId) as Promise<Team>,
      leaguesApi.get(leagueId) as Promise<LeagueData>,
    ])
      .then(([t, l]) => {
        setTeam(t);
        setLeague(l);
      })
      .catch(() => setError("Failed to load team"))
      .finally(() => setLoading(false));

    standingsApi
      .getSchedule(leagueId, CURRENT_YEAR)
      .then((data) => setSchedule((data as { schedule: ScheduleWeek[] }).schedule || []))
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

  const avatar = getAvatarStyle(team.avatar_url);
  const roster = (team.roster || []).map((pid) => playersById[pid]).filter(Boolean) as RosterPlayer[];
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
          <Link href={`/leagues/${leagueId}`} className="text-surface-400 hover:text-white transition-colors">
            <ChevronLeft className="w-5 h-5" />
          </Link>
          <h1 className="text-lg font-semibold text-white">{league?.name} — Team</h1>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        {/* Team header */}
        <div className="bg-surface-800 border border-surface-700 rounded-2xl p-6 flex items-center gap-4">
          <div
            className="w-16 h-16 rounded-2xl flex items-center justify-center text-3xl shrink-0 border border-surface-700/50"
            style={{ backgroundColor: avatar.bg }}
          >
            {avatar.icon}
          </div>
          <div className="flex-1 min-w-0">
            <h2 className="text-2xl font-bold text-white truncate">{team.name}</h2>
            <p className="text-surface-400 text-sm flex items-center gap-1.5 mt-1">
              {team.is_cpu ? (
                <>
                  <Bot className="w-3.5 h-3.5" /> CPU-controlled
                </>
              ) : (
                <>
                  <UserCheck className="w-3.5 h-3.5" /> Owner-managed
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
          </div>
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
                      <PlayerAvatar player={p as any} size="sm" onHover={handlePlayerHover as any} />
                      <span className="text-sm text-white truncate flex-1">{p.full_name}</span>
                      {p.season_points != null && (
                        <span className="text-[10px] text-gold-400/80 font-semibold">
                          {Math.round(p.season_points * 10) / 10}
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
                    <div className="flex items-center gap-2 flex-1 justify-center">
                      <Swords className="w-3.5 h-3.5 text-surface-600" />
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

      <PlayerCardOverlay player={hoveredPlayer} position={hoverPos} />
    </div>
  );
}
