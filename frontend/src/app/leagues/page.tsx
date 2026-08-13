"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { leaguesApi, LeagueListFilters } from "@/lib/api-client";
import { Trophy, Search, Plus } from "lucide-react";
import { LeagueTypeBadge, VisibilityBadge, OpenSpotsBadge } from "@/components/LeagueBadges";

interface League {
  id: string;
  name: string;
  league_type: string;
  max_teams: number;
  team_count: number | null;
  draft_status: string;
  description: string | null;
  visibility: string;
}

type LeagueTypeFilter = "all" | "standard" | "two_man" | "conference";
type VisibilityFilter = "all" | "open" | "invite_only";
type SortOption = "newest" | "open_spots" | "name" | "size";

export default function LeaguesBrowsePage() {
  const [leagues, setLeagues] = useState<League[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [openOnly, setOpenOnly] = useState(false);
  const [leagueType, setLeagueType] = useState<LeagueTypeFilter>("all");
  const [visibility, setVisibility] = useState<VisibilityFilter>("all");
  const [sort, setSort] = useState<SortOption>("newest");

  const load = useCallback(() => {
    setLoading(true);
    const filters: LeagueListFilters = { sort };
    if (openOnly) filters.open_only = true;
    if (leagueType !== "all") filters.league_type = leagueType;
    if (visibility !== "all") filters.visibility = visibility;
    leaguesApi
      .list(filters)
      .then((data) => setLeagues(Array.isArray(data) ? (data as League[]) : []))
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load leagues"))
      .finally(() => setLoading(false));
  }, [sort, openOnly, leagueType, visibility]);

  useEffect(() => {
    load();
  }, [load]);

  // Free-text search stays client-side -- everything else (visibility,
  // type, open-slots, sort) is a real server-side filter now instead of
  // fetching every league and filtering in the browser.
  const filtered = search
    ? leagues.filter((l) => l.name.toLowerCase().includes(search.toLowerCase()))
    : leagues;

  return (
    <div className="min-h-screen">
      {/* Header */}
      <section className="relative overflow-hidden border-b border-surface-700">
        <div className="absolute inset-0 bg-gradient-to-b from-surface-850 via-surface-900 to-surface-900" />
        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12 md:py-16">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-6">
            <div>
              <h1 className="text-3xl md:text-4xl font-bold text-white tracking-tight">
                Browse Leagues
              </h1>
              <p className="text-surface-400 mt-2 text-sm md:text-base">
                Find a league with an open slot and jump in.
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

      <section className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
        {/* Filters */}
        <div className="flex flex-col sm:flex-row flex-wrap gap-3 mb-8">
          <div className="relative flex-1 min-w-50 max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-surface-500" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search leagues..."
              className="w-full pl-10 pr-3 py-2.5 bg-surface-800 border border-surface-700 rounded-xl text-sm text-white placeholder-surface-500 focus:outline-none focus:ring-1 focus:ring-gold-400"
            />
          </div>

          <select
            value={leagueType}
            onChange={(e) => setLeagueType(e.target.value as LeagueTypeFilter)}
            className="px-3.5 py-2.5 bg-surface-800 border border-surface-700 rounded-xl text-sm text-white focus:outline-none focus:ring-1 focus:ring-gold-400"
          >
            <option value="all">All Types</option>
            <option value="standard">Standard</option>
            <option value="two_man">2-Man</option>
            <option value="conference">Conference</option>
          </select>

          <select
            value={visibility}
            onChange={(e) => setVisibility(e.target.value as VisibilityFilter)}
            className="px-3.5 py-2.5 bg-surface-800 border border-surface-700 rounded-xl text-sm text-white focus:outline-none focus:ring-1 focus:ring-gold-400"
          >
            <option value="all">Any Visibility</option>
            <option value="open">Open</option>
            <option value="invite_only">Invite Only</option>
          </select>

          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as SortOption)}
            className="px-3.5 py-2.5 bg-surface-800 border border-surface-700 rounded-xl text-sm text-white focus:outline-none focus:ring-1 focus:ring-gold-400"
          >
            <option value="newest">Newest</option>
            <option value="open_spots">Most Open Spots</option>
            <option value="name">Name (A-Z)</option>
            <option value="size">League Size</option>
          </select>

          <button
            type="button"
            onClick={() => setOpenOnly(!openOnly)}
            className={`inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold border transition-all ${
              openOnly
                ? "bg-gold-400/20 text-gold-400 border-gold-400/30"
                : "bg-surface-800 text-surface-400 border-surface-700 hover:text-white"
            }`}
          >
            Open Slots Only
          </button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-24">
            <div className="w-8 h-8 border-2 border-gold-400 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : error ? (
          <div className="text-center py-24 text-surface-400 text-sm">{error}</div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-24 text-center">
            <Trophy className="w-12 h-12 text-gold-400/40 mb-4" />
            <h2 className="text-lg font-semibold text-white mb-1">No leagues found</h2>
            <p className="text-surface-400 text-sm max-w-md">
              {leagues.length === 0
                ? "No leagues match these filters yet — try widening your search, or be the first to create one."
                : "Try adjusting your search or filters."}
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {filtered.map((league) => (
              <Link
                key={league.id}
                href={`/leagues/${league.id}`}
                className="group bg-surface-800 border border-surface-700 rounded-2xl p-6 hover:border-gold-400/30 transition-all hover:-translate-y-1 hover:shadow-xl hover:shadow-gold-400/5"
              >
                <div className="flex items-start justify-between gap-2 mb-4">
                  <h3 className="text-lg font-bold text-white group-hover:text-gold-400 transition-colors truncate">
                    {league.name}
                  </h3>
                  <VisibilityBadge visibility={league.visibility} />
                </div>

                <div className="flex items-center gap-4 mb-3">
                  <div className="flex items-baseline gap-1">
                    <span className="text-xl font-bold font-mono tabular-nums text-white">
                      {league.team_count ?? 0}
                    </span>
                    <span className="text-surface-500 text-sm font-mono">/{league.max_teams}</span>
                  </div>
                  <OpenSpotsBadge teamCount={league.team_count} maxTeams={league.max_teams} />
                </div>

                <LeagueTypeBadge leagueType={league.league_type} />

                {league.description && (
                  <p className="text-surface-500 text-xs mt-3 line-clamp-2">{league.description}</p>
                )}
              </Link>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
