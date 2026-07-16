"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { leaguesApi } from "@/lib/api-client";
import { Trophy, Plus, Users, Shield, Swords, ExternalLink, Calendar } from "lucide-react";

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

/* ---------- Dashboard Page ---------- */

export default function DashboardPage() {
  const [leagues, setLeagues] = useState<League[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    leaguesApi
      .list()
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
            <Link
              href="/leagues/create"
              className="inline-flex items-center gap-2 bg-gold-400 hover:bg-gold-300 text-surface-900 px-6 py-3 rounded-xl font-bold text-sm transition-all hover:shadow-xl hover:shadow-gold-400/30 hover:-translate-y-0.5 active:translate-y-0 shrink-0"
            >
              <Plus className="w-4 h-4" />
              Create League
            </Link>
          </div>
        </div>
      </section>

      {/* League Cards */}
      <section className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
        {loading ? (
          <div className="flex items-center justify-center py-24">
            <div className="w-8 h-8 border-2 border-gold-400 border-t-transparent rounded-full animate-spin" />
            <span className="ml-3 text-surface-400">Loading leagues...</span>
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
              No leagues yet
            </h2>
            <p className="text-surface-400 text-sm max-w-md">
              Join or create your first league to get started on your fantasy
              football journey.
            </p>
            <Link
              href="/leagues/create"
              className="mt-6 inline-flex items-center gap-2 bg-gold-400 hover:bg-gold-300 text-surface-900 px-6 py-3 rounded-xl font-bold text-sm transition-all hover:shadow-lg hover:shadow-gold-400/25"
            >
              <Plus className="w-4 h-4" />
              Create Your First League
            </Link>
          </div>
        )}
      </section>
    </div>
  );
}
