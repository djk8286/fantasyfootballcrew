"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { leaguesApi, playersApi, dashboardApi, isLoggedIn } from "@/lib/api-client";
import { Trophy, Plus, Users, Shield, Swords, ExternalLink, Calendar, ArrowRight, Sparkles, Flame, Radio, Bot } from "lucide-react";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import PositionBadge from "@/components/PositionBadge";
import RankBadge from "@/components/ui/RankBadge";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

interface League {
  id: string;
  name: string;
  league_type: string;
  max_teams: number;
  team_count: number | null;
  draft_status: string;
  commissioner_id: string;
  description: string | null;
  created_at?: string;
}

const leagueTypeLabels: Record<string, string> = {
  standard: "Standard",
  two_man: "2-Man",
  conference: "Conference",
};

const draftStatusConfig: Record<string, { label: string; color: string }> = {
  not_started: {
    label: "Not Started",
    color: "bg-yellow-500/15 text-yellow-400 border-yellow-500/25",
  },
  in_progress: {
    label: "In Progress",
    color: "bg-blue-500/15 text-blue-400 border-blue-500/25",
  },
  completed: {
    label: "Completed",
    color: "bg-green-500/15 text-green-400 border-green-500/25",
  },
};

const leagueTypeIcons: Record<string, typeof Users> = {
  standard: Users,
  two_man: Users,
  conference: Swords,
};

/** Format an ISO date string as a relative time ("Created 2 days ago") */
function timeAgo(dateStr: string | undefined): string | null {
  if (!dateStr) return null;
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  if (isNaN(then)) return null;
  const diffMs = now - then;
  const minutes = Math.floor(diffMs / 60000);
  const hours = Math.floor(diffMs / 3600000);
  const days = Math.floor(diffMs / 86400000);
  const weeks = Math.floor(days / 7);
  const months = Math.floor(days / 30);

  let label: string;
  if (minutes < 1) label = "just now";
  else if (minutes < 60) label = `${minutes}m ago`;
  else if (hours < 24) label = `${hours}h ago`;
  else if (days < 7) label = `${days}d ago`;
  else if (weeks < 5) label = `${weeks}w ago`;
  else label = `${months}mo ago`;

  return `Created ${label}`;
}

/* ---------- Individual league card with quick actions ---------- */

function LeagueCard({ league }: { league: League }) {
  const [draftId, setDraftId] = useState<string | null>(null);
  const [draftLoading, setDraftLoading] = useState(false);

  const typeLabel = leagueTypeLabels[league.league_type] || league.league_type;
  const statusConf =
    draftStatusConfig[league.draft_status] || draftStatusConfig.not_started;
  const TypeIcon = leagueTypeIcons[league.league_type] || Users;

  const teamCount = league.team_count ?? 0;
  const slotsOpen = league.max_teams - teamCount;
  const isFull = slotsOpen <= 0;
  const hasDraft = league.draft_status !== "not_started";
  const isLive = league.draft_status === "in_progress";
  const createdLabel = timeAgo(league.created_at);

  // Fetch draft ID when the league has an active/completed draft
  useEffect(() => {
    if (!hasDraft) return;
    let cancelled = false;
    setDraftLoading(true);
    fetch(`${API_BASE}/api/v1/drafts/find?league_id=${league.id}`)
      .then((res) => res.json())
      .then((data) => {
        if (!cancelled && data?.id) setDraftId(data.id);
      })
      .catch(() => {
        /* draft not found — buttons simply won't render */
      })
      .finally(() => {
        if (!cancelled) setDraftLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [league.id, hasDraft]);

  const quickActions = [
    ...(hasDraft && draftId
      ? [
          {
            href: `/draft/${draftId}`,
            label: "Draft Room",
            icon: Shield,
          },
        ]
      : []),
    {
      href: `/leagues/${league.id}/standings`,
      label: "Standings",
      icon: Trophy,
    },
    {
      href: `/leagues/${league.id}/scoring`,
      label: "Settings",
      icon: ExternalLink,
    },
  ];

  // Prevent the quick-action link clicks from navigating to the league page
  const stopPropagation = useCallback(
    (e: React.MouseEvent) => e.stopPropagation(),
    [],
  );

  return (
    <div
      className={`relative group rounded-2xl p-6 transition-all hover:-translate-y-1 ${
        isLive
          ? "bg-gold-400/10 border-2 border-gold-400/40 ring-2 ring-gold-400/20 shadow-[0_0_30px_rgba(255,215,0,0.12)]"
          : "bg-surface-800 border border-surface-700 hover:border-gold-400/30 hover:shadow-xl hover:shadow-gold-400/5"
      }`}
    >
      {/* Main card link — wraps everything except quick actions */}
      <Link href={`/leagues/${league.id}`} className="block">
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3 min-w-0">
            <div
              className={`w-12 h-12 rounded-xl flex items-center justify-center shrink-0 ${
                isLive
                  ? "bg-gold-400/20 border border-gold-400/40"
                  : "bg-gold-400/10 border border-gold-400/20"
              }`}
            >
              <TypeIcon className="w-6 h-6 text-gold-400" />
            </div>
            <h3 className="text-lg font-bold text-white group-hover:text-gold-400 transition-colors truncate">
              {league.name}
            </h3>
          </div>
          <span
            className={`px-2.5 py-0.5 rounded-full text-[11px] font-semibold border shrink-0 ${statusConf.color}`}
          >
            {isLive && <span className="inline-block w-1.5 h-1.5 bg-current rounded-full animate-pulse mr-1" />}
            {statusConf.label}
          </span>
        </div>

        {/* Stat row */}
        <div className="flex items-center gap-4 mb-3">
          <div className="flex items-baseline gap-1" title={`${teamCount} of ${league.max_teams} teams`}>
            <span className="text-xl font-bold font-mono tabular-nums text-white">{teamCount}</span>
            <span className="text-surface-500 text-sm font-mono">/{league.max_teams}</span>
            <Users className="w-3.5 h-3.5 text-surface-500 ml-1" />
          </div>
          {isFull ? (
            <span className="text-xs text-green-400 font-semibold">Full</span>
          ) : (
            <span className="text-xs text-gold-400 font-semibold">
              {slotsOpen} slot{slotsOpen !== 1 ? "s" : ""} open
            </span>
          )}
        </div>

        {/* Details */}
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-surface-400">
          <span className="inline-flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-gold-400/60" />
            {typeLabel}
          </span>
          {createdLabel && (
            <span className="inline-flex items-center gap-1.5 w-full sm:w-auto mt-1 sm:mt-0">
              <Calendar className="w-3 h-3 text-surface-500" />
              <span className="text-surface-500 text-xs">{createdLabel}</span>
            </span>
          )}
        </div>

        {league.description && (
          <p className="text-surface-500 text-xs mt-3 line-clamp-1">
            {league.description}
          </p>
        )}
      </Link>

      {/* Quick action buttons — appear on hover */}
      <div className="absolute bottom-4 right-4 flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none group-hover:pointer-events-auto">
        {draftLoading && hasDraft && (
          <span className="text-xs text-surface-500 mr-1">Loading...</span>
        )}
        {quickActions.map((action) => {
          const Icon = action.icon;
          return (
            <Link
              key={action.href}
              href={action.href}
              onClick={stopPropagation}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-surface-700 hover:bg-surface-600 border border-surface-600 text-xs font-medium text-surface-300 hover:text-gold-400 hover:border-gold-400/30 transition-all"
            >
              <Icon className="w-3.5 h-3.5" />
              {action.label}
            </Link>
          );
        })}
      </div>
    </div>
  );
}

/* ---------- Top draft prospects widget ---------- */

interface Prospect {
  rank: number;
  id: string;
  first_name: string;
  last_name: string;
  position: string;
  team: string | null;
  bye_week: number | null;
  injury_status: string | null;
  avatar_url?: string | null;
  sleeper_id?: string | null;
  headline_stats?: Record<string, number> | null;
}

const PROSPECT_STAT_LABELS: Record<string, string> = {
  pass_yd: "pass yd",
  pass_td: "pass TD",
  pass_int: "INT",
  rush_yd: "rush yd",
  rush_td: "rush TD",
  rec: "rec",
  rec_yd: "rec yd",
  rec_td: "rec TD",
  fgm: "FG",
  xpm: "XP",
  idp_tkl: "tkl",
  idp_sack: "sack",
  idp_int: "INT",
};

function prospectStatLine(stats?: Record<string, number> | null): string {
  if (!stats) return "";
  return Object.entries(stats)
    .map(([key, value]) => `${Math.round(value * 10) / 10} ${PROSPECT_STAT_LABELS[key] || key}`)
    .join(" · ");
}

function TopProspectsWidget() {
  const [prospects, setProspects] = useState<Prospect[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    playersApi
      .topProspects(10)
      .then((data) => setProspects(Array.isArray(data) ? (data as Prospect[]) : []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (!loading && prospects.length === 0) return null;

  return (
    <div className="bg-surface-800 border border-surface-700 rounded-2xl p-6 mb-10">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-bold text-white flex items-center gap-2">
          <Trophy className="w-4 h-4 text-gold-400" />
          Top Draft Prospects
        </h2>
        <Link
          href="/players"
          className="inline-flex items-center gap-1 text-gold-400 hover:text-gold-300 text-xs font-semibold"
        >
          View all 100 <ArrowRight className="w-3 h-3" />
        </Link>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-8">
          <div className="w-6 h-6 border-2 border-gold-400 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {prospects.map((p) => (
            <Link
              key={p.id}
              href="/players"
              className="flex items-center gap-3 px-3 py-2 rounded-xl hover:bg-surface-700/50 transition-colors"
            >
              <RankBadge rank={p.rank} size="sm" />
              <PlayerAvatar
                player={{
                  id: p.id,
                  full_name: `${p.first_name} ${p.last_name}`.trim(),
                  first_name: p.first_name,
                  last_name: p.last_name,
                  position: p.position,
                  team: p.team || "",
                  age: null,
                  number: null,
                  bye_week: p.bye_week,
                  injury_status: p.injury_status,
                  fantasy_positions: null,
                  avatar_url: p.avatar_url ?? null,
                  sleeper_id: p.sleeper_id ?? null,
                  rank_score: p.rank,
                  pos_rank: 0,
                  headline_stats: p.headline_stats,
                }}
                size="sm"
              />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="text-sm font-medium text-white truncate">
                    {p.first_name} {p.last_name}
                  </span>
                  <PositionBadge pos={p.position} />
                </div>
                <span className="text-surface-500 text-xs">{p.team || "FA"}</span>
                {p.headline_stats && Object.keys(p.headline_stats).length > 0 && (
                  <p className="text-[10px] text-surface-500 truncate">
                    {prospectStatLine(p.headline_stats)}
                  </p>
                )}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function AIBadge() {
  return (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-purple-400/20 text-purple-300 text-[9px] font-bold uppercase tracking-wider">
      <Bot className="w-2.5 h-2.5" /> AI-Generated
    </span>
  );
}

interface TopPerformer {
  name: string;
  position: string;
  team: string;
  points: number;
}

function TopPerformersWidget({ onHasData }: { onHasData?: (hasData: boolean) => void }) {
  const [data, setData] = useState<{ content: string; top_players: TopPerformer[]; week: number } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    dashboardApi
      .getTopPerformers()
      .then((d) => setData(d as { content: string; top_players: TopPerformer[]; week: number }))
      .catch(() => setData(null)) // 404 just means nothing generated yet -- not an error banner
      .finally(() => setLoading(false));
  }, []);

  // Reports up once loading settles -- lets the parent grid collapse to a
  // single, full-width column when this widget has nothing to show (e.g.
  // all preseason, before any real weekly stats are synced) instead of
  // leaving its sibling stuck at half-width/off-center in an otherwise-
  // empty 2-column grid. See NFLScoresWidget's matching effect.
  useEffect(() => {
    if (!loading) onHasData?.(data !== null);
  }, [loading, data, onHasData]);

  if (loading) {
    return (
      <div className="bg-surface-800 border border-surface-700 rounded-2xl p-6 mb-6 flex items-center justify-center h-130">
        <div className="w-6 h-6 border-2 border-gold-400 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }
  if (!data) return null;

  return (
    <div className="bg-surface-800 border border-surface-700 rounded-2xl p-6 mb-6 flex flex-col h-130">
      <div className="flex items-center justify-between mb-3 shrink-0">
        <h2 className="text-lg font-bold text-white flex items-center gap-2">
          <Flame className="w-4 h-4 text-gold-400" />
          Top Performers -- Week {data.week}
        </h2>
        <AIBadge />
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto">
        <div className="p-4 rounded-xl border bg-purple-400/5 border-purple-400/20 text-surface-200 text-sm leading-relaxed whitespace-pre-wrap mb-4">
          {data.content}
        </div>
        {data.top_players?.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1">
            {data.top_players.slice(0, 10).map((p, i) => (
              <div key={`${p.name}-${i}`} className="flex items-center justify-between py-1.5 border-b border-surface-800/50 text-sm">
                <span className="text-white truncate">
                  <span className="text-surface-500 mr-1.5">{i + 1}.</span>
                  {p.name} <span className="text-surface-500">({p.position} - {p.team})</span>
                </span>
                <span className="text-gold-400 font-semibold shrink-0 ml-2">{p.points} pts</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

interface NflGame {
  home_team: string;
  home_team_name: string;
  home_score: number | null;
  away_team: string;
  away_team_name: string;
  away_score: number | null;
  status_detail: string;
  completed: boolean;
}

function NFLScoresWidget({ onHasData }: { onHasData?: (hasData: boolean) => void }) {
  const [data, setData] = useState<{ week: number; games: NflGame[]; recap: string | null } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    dashboardApi
      .getNflScores()
      .then((d) => setData(d as { week: number; games: NflGame[]; recap: string | null }))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, []);

  // See TopPerformersWidget's matching effect.
  useEffect(() => {
    if (!loading) onHasData?.(data !== null);
  }, [loading, data, onHasData]);

  if (loading) {
    return (
      <div className="bg-surface-800 border border-surface-700 rounded-2xl p-6 mb-6 flex items-center justify-center h-130">
        <div className="w-6 h-6 border-2 border-gold-400 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }
  if (!data) return null;

  return (
    <div className="bg-surface-800 border border-surface-700 rounded-2xl p-6 mb-6 flex flex-col h-130">
      <div className="flex items-center justify-between mb-3 shrink-0">
        <h2 className="text-lg font-bold text-white flex items-center gap-2">
          <Radio className="w-4 h-4 text-gold-400" />
          NFL Scores -- Week {data.week}
        </h2>
        {data.recap && <AIBadge />}
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto">
        {data.recap && (
          <div className="p-4 rounded-xl border bg-purple-400/5 border-purple-400/20 text-surface-200 text-sm leading-relaxed whitespace-pre-wrap mb-4">
            {data.recap}
          </div>
        )}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {data.games.map((g, i) => (
            <div key={i} className="flex items-center justify-between px-3 py-2 rounded-lg bg-surface-900 border border-surface-700 text-sm">
              <div className="min-w-0">
                <div className="text-white truncate">{g.away_team} @ {g.home_team}</div>
                <div className="text-surface-500 text-[10px]">{g.status_detail}</div>
              </div>
              {g.home_score !== null && g.away_score !== null && (
                <div className="text-gold-400 font-semibold shrink-0 ml-2">{g.away_score} - {g.home_score}</div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ---------- Dashboard Page ---------- */

export default function DashboardPage() {
  const [leagues, setLeagues] = useState<League[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [loggedIn, setLoggedIn] = useState(true);

  // null = still loading / not yet reported -- defaults the grid to its
  // normal 2-column shape so the common case (both widgets have data)
  // never flashes single-column first. Once both have reported in,
  // collapses to 1 column (full width) if only one of them actually has
  // anything to show -- see TopPerformersWidget/NFLScoresWidget's
  // onHasData effects for why this can legitimately happen (e.g. no real
  // weekly stats synced yet during the preseason).
  const [topPerformersHasData, setTopPerformersHasData] = useState<boolean | null>(null);
  const [nflScoresHasData, setNflScoresHasData] = useState<boolean | null>(null);
  const bothReported = topPerformersHasData !== null && nflScoresHasData !== null;
  const summariesGridCols =
    bothReported && (topPerformersHasData ? 1 : 0) + (nflScoresHasData ? 1 : 0) <= 1
      ? "grid-cols-1"
      : "grid-cols-1 lg:grid-cols-2";

  useEffect(() => {
    if (!isLoggedIn()) {
      setLoggedIn(false);
      setLoading(false);
      return;
    }
    leaguesApi
      .list({ mine: true })
      .then((data) => {
        setLeagues(Array.isArray(data) ? data : []);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Failed to load leagues");
      })
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="min-h-screen bg-surface-900">
      {/* Hero Section */}
      <section className="relative overflow-hidden border-b border-surface-700">
        <div className="absolute inset-0 bg-gradient-to-b from-surface-850 via-surface-900 to-surface-900" />
        <div className="absolute top-0 right-0 w-[600px] h-[400px] bg-gold-400/5 rounded-full blur-3xl" />

        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12 md:py-16">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-6">
            <div>
              <h1 className="text-3xl md:text-4xl font-bold text-white tracking-tight">
                My Leagues
              </h1>
              <p className="text-surface-400 mt-2 text-sm md:text-base">
                Manage your leagues, start drafts, and track standings.
              </p>
            </div>
            <div className="flex items-center gap-3 shrink-0">
              <Link
                href="/mock-draft"
                className="inline-flex items-center gap-2 bg-surface-800 hover:bg-surface-700 border border-surface-600 text-surface-200 hover:text-white px-5 py-3 rounded-xl font-bold text-sm transition-all"
              >
                <Sparkles className="w-4 h-4 text-gold-400" />
                Mock Draft
              </Link>
              <Link
                href="/leagues/create"
                className="inline-flex items-center gap-2 bg-gold-400 hover:bg-gold-300 text-surface-900 px-6 py-3 rounded-xl font-bold text-sm transition-all hover:shadow-xl hover:shadow-gold-400/30 hover:-translate-y-0.5 active:translate-y-0"
              >
                <Plus className="w-4 h-4" />
                Create League
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* Dashboard AI Summaries -- top real performers + NFL scores recap.
          Hidden outright once both widgets have confirmed they have
          nothing to show (rather than rendering an empty, padded section)
          -- summariesGridCols above handles the "only one has data" case
          by collapsing to a single full-width column instead of leaving
          the other stuck at half-width in an otherwise-empty grid slot. */}
      {topPerformersHasData !== false || nflScoresHasData !== false ? (
      <section className={`max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-10 grid ${summariesGridCols} gap-6`}>
        <TopPerformersWidget onHasData={setTopPerformersHasData} />
        <NFLScoresWidget onHasData={setNflScoresHasData} />
      </section>
      ) : null}

      {/* Top Draft Prospects */}
      <section className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <TopProspectsWidget />
      </section>

      {/* League Cards */}
      <section className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pb-10">
        {loading ? (
          <div className="flex items-center justify-center py-24">
            <div className="w-8 h-8 border-2 border-gold-400 border-t-transparent rounded-full animate-spin" />
            <span className="ml-3 text-surface-400">Loading leagues...</span>
          </div>
        ) : !loggedIn ? (
          <div className="flex flex-col items-center justify-center py-24 text-center">
            <div className="w-16 h-16 rounded-2xl bg-surface-800 border border-surface-700 flex items-center justify-center mb-4">
              <Trophy className="w-8 h-8 text-gold-400/60" />
            </div>
            <h2 className="text-lg font-semibold text-white mb-1">Log in to see your leagues</h2>
            <p className="text-surface-400 text-sm mb-4">
              Sign in to manage the leagues you own or play in.
            </p>
            <Link
              href="/login"
              className="inline-flex items-center gap-2 bg-gold-400 hover:bg-gold-300 text-surface-900 px-6 py-2.5 rounded-xl font-bold text-sm transition-all"
            >
              Log In
            </Link>
          </div>
        ) : error ? (
          <div className="flex flex-col items-center justify-center py-24 text-center">
            <div className="w-16 h-16 rounded-2xl bg-surface-800 border border-surface-700 flex items-center justify-center mb-4">
              <Trophy className="w-8 h-8 text-red-400/60" />
            </div>
            <h2 className="text-lg font-semibold text-white mb-1">
              Could not load leagues
            </h2>
            <p className="text-surface-400 text-sm">{error}</p>
            <button
              onClick={() => window.location.reload()}
              className="mt-4 text-gold-400 hover:text-gold-300 text-sm font-medium"
            >
              Try again
            </button>
          </div>
        ) : leagues.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {leagues.map((league) => (
              <LeagueCard key={league.id} league={league} />
            ))}
          </div>
        ) : (
          /* Empty State */
          <div className="flex flex-col items-center justify-center py-24 text-center">
            <div className="w-20 h-20 rounded-2xl bg-surface-800 border border-surface-700 flex items-center justify-center mb-6">
              <Trophy className="w-10 h-10 text-gold-400/60" />
            </div>
            <h2 className="text-xl font-semibold text-white mb-2">
              You&apos;re not in any leagues yet
            </h2>
            <p className="text-surface-400 text-sm max-w-md">
              Create your own league, or browse existing ones with open slots.
            </p>
            <div className="flex flex-col sm:flex-row gap-3 mt-6">
              <Link
                href="/leagues/create"
                className="inline-flex items-center gap-2 bg-gold-400 hover:bg-gold-300 text-surface-900 px-6 py-3 rounded-xl font-bold text-sm transition-all hover:shadow-lg hover:shadow-gold-400/25"
              >
                <Plus className="w-4 h-4" />
                Create a League
              </Link>
              <Link
                href="/leagues"
                className="inline-flex items-center gap-2 border border-surface-600 hover:border-gold-400/50 text-surface-300 hover:text-gold-400 px-6 py-3 rounded-xl font-semibold text-sm transition-all"
              >
                Browse Leagues
              </Link>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
