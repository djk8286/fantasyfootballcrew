"use client";

import { useState, useEffect } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { leaguesApi } from "@/lib/api-client";
import { conferenceFullLabel } from "@/components/LeagueBadges";
import { ArrowLeft, Trophy, Crown } from "lucide-react";

interface TeamRef {
  id: string;
  name: string;
}

interface Matchup {
  id: string;
  bracket: string;
  round: number;
  slot: number;
  week: number;
  team_a: TeamRef | null;
  team_b: TeamRef | null;
  is_bye: boolean;
  winner_team_id: string | null;
}

interface PlayoffSettings {
  enabled: boolean;
  regular_season_weeks: number;
  num_teams: number;
  seeding_method: string;
  conference_bracket_mode: string;
}

interface PlayoffData {
  has_bracket: boolean;
  settings: PlayoffSettings;
  year?: number;
  status?: string;
  seeding_method?: string;
  total_rounds?: number;
  current_round?: number;
  seeds?: Record<string, { team_id: string; seed: number; team_name: string }[]>;
  matchups?: Matchup[];
}

function MatchupCard({ m }: { m: Matchup }) {
  const side = (team: TeamRef | null, isWinner: boolean) => (
    <div
      className={`px-3 py-2 flex items-center justify-between text-xs ${
        isWinner ? "bg-gold-400/10 text-gold-400 font-semibold" : "text-surface-300"
      }`}
    >
      <span className="truncate">{team ? team.name : m.is_bye ? "—" : "TBD"}</span>
      {isWinner && <Crown className="w-3 h-3 shrink-0 ml-1" />}
    </div>
  );

  return (
    <div className="bg-surface-800/70 border border-surface-700 rounded-xl overflow-hidden divide-y divide-surface-700/60 w-48">
      {side(m.team_a, m.winner_team_id === m.team_a?.id)}
      {side(m.team_b, m.winner_team_id === m.team_b?.id)}
      {m.is_bye && (
        <div className="px-3 py-1 text-[10px] text-surface-500 bg-surface-900/40">Bye</div>
      )}
    </div>
  );
}

function BracketColumns({ matchups, totalRounds }: { matchups: Matchup[]; totalRounds: number }) {
  const byRound: Record<number, Matchup[]> = {};
  for (const m of matchups) {
    (byRound[m.round] ||= []).push(m);
  }
  for (const round of Object.values(byRound)) {
    round.sort((a, b) => a.slot - b.slot);
  }

  const roundLabel = (round: number) => {
    const roundsLeft = totalRounds - round;
    if (roundsLeft === 0) return "Final";
    if (roundsLeft === 1) return "Semifinal";
    if (roundsLeft === 2) return "Quarterfinal";
    return `Round ${round}`;
  };

  return (
    <div className="flex gap-8 overflow-x-auto pb-4">
      {Array.from({ length: totalRounds }, (_, i) => i + 1).map((round) => (
        <div key={round} className="shrink-0 flex flex-col gap-6">
          <h4 className="text-xs font-semibold text-surface-400 uppercase tracking-wider">
            {roundLabel(round)} · Wk {byRound[round]?.[0]?.week ?? "—"}
          </h4>
          <div className="flex flex-col gap-6 justify-around flex-1">
            {(byRound[round] || []).map((m) => (
              <MatchupCard key={m.id} m={m} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export default function PlayoffsPage() {
  const params = useParams();
  const id = params.id as string;

  const [league, setLeague] = useState<{ name: string; conference_a_name?: string | null; conference_b_name?: string | null } | null>(null);
  const [data, setData] = useState<PlayoffData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    Promise.all([leaguesApi.get(id).catch(() => null), leaguesApi.getPlayoffs(id).catch(() => null)])
      .then(([leagueData, playoffData]) => {
        if (leagueData) setLeague(leagueData as { name: string });
        if (playoffData) setData(playoffData as PlayoffData);
      })
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) {
    return (
      <div className="min-h-screen bg-surface-900 flex items-center justify-center">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 border-2 border-gold-400 border-t-transparent rounded-full animate-spin" />
          <span className="text-surface-400">Loading playoffs...</span>
        </div>
      </div>
    );
  }

  const brackets = data?.matchups ? Array.from(new Set(data.matchups.map((m) => m.bracket))).sort() : [];

  return (
    <div className="min-h-screen bg-surface-900">
      <div className="sticky top-0 z-40 bg-surface-900/95 backdrop-blur-md border-b border-surface-700">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-3 flex items-center gap-3">
          <Link href={`/leagues/${id}`} className="text-surface-400 hover:text-white transition-colors shrink-0">
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <h1 className="text-lg font-bold text-white flex items-center gap-2">
            <Trophy className="w-4 h-4 text-gold-400" />
            Playoffs
          </h1>
          {league && <span className="text-surface-400 text-sm hidden sm:inline">{league.name}</span>}
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {!data?.settings?.enabled && (
          <div className="bg-surface-800/50 border border-surface-700 rounded-2xl p-10 text-center">
            <Trophy className="w-10 h-10 mx-auto mb-3 text-surface-600" />
            <p className="text-surface-300 font-semibold mb-1">Playoffs aren&apos;t enabled for this league.</p>
            <p className="text-surface-500 text-sm">
              A commissioner can turn them on in{" "}
              <Link href={`/leagues/${id}/playoff-settings`} className="text-gold-400 hover:text-gold-300 underline">
                Playoff Settings
              </Link>
              .
            </p>
          </div>
        )}

        {data?.settings?.enabled && !data.has_bracket && (
          <div className="bg-surface-800/50 border border-surface-700 rounded-2xl p-10 text-center">
            <Trophy className="w-10 h-10 mx-auto mb-3 text-gold-400/60" />
            <p className="text-surface-300 font-semibold mb-1">The bracket hasn&apos;t generated yet.</p>
            <p className="text-surface-500 text-sm">
              It'll be built automatically once the regular season ({data.settings.regular_season_weeks} weeks) ends —
              no action needed.
            </p>
          </div>
        )}

        {data?.has_bracket && (
          <div className="space-y-10">
            <div className="flex items-center gap-3 flex-wrap">
              <span
                className={`text-xs font-bold px-3 py-1 rounded-full ${
                  data.status === "completed"
                    ? "bg-green-500/20 text-green-400"
                    : "bg-gold-400/20 text-gold-400"
                }`}
              >
                {data.status === "completed" ? "Completed" : `In Progress · Round ${data.current_round}/${data.total_rounds}`}
              </span>
              <span className="text-xs text-surface-500">
                {data.seeding_method === "points" ? "Seeded by total points" : "Seeded by record"}
                {data.year ? ` · ${data.year}` : ""}
              </span>
            </div>

            {brackets.map((bracketLabel) => (
              <div key={bracketLabel}>
                {brackets.length > 1 && (
                  <h3 className="text-sm font-bold text-white mb-4">
                    {conferenceFullLabel(bracketLabel, league?.conference_a_name, league?.conference_b_name)}
                  </h3>
                )}
                <BracketColumns
                  matchups={(data.matchups || []).filter((m) => m.bracket === bracketLabel)}
                  totalRounds={data.total_rounds || 1}
                />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
