"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { leaguesApi } from "@/lib/api-client";
import { Trophy, Users, Swords, Search, Plus } from "lucide-react";

interface League {
  id: string;
  name: string;
  league_type: string;
  max_teams: number;
  team_count: number | null;
  draft_status: string;
  description: string | null;
}

const leagueTypeLabels: Record<string, string> = {
  standard: "Standard",
  two_man: "2-Man",
  conference: "Conference",
};

const leagueTypeIcons: Record<string, typeof Users> = {
  standard: Users,
  two_man: Users,
  conference: Swords,
};

export default function LeaguesBrowsePage() {
  const [leagues, setLeagues] = useState<League[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [openOnly, setOpenOnly] = useState(false);

  useEffect(() => {
    leaguesApi
      .list()
      .then((data) => setLeagues(Array.isArray(data) ? (data as League[]) : []))
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load leagues"))
      .finally(() => setLoading(false));
  }, []);

  const filtered = leagues.filter((l) => {
    const teamCount = l.team_count ?? 0;
    if (openOnly && teamCount >= l.max_teams) return false;
    if (search && !l.name.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

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
        <div className="flex flex-col sm:flex-row gap-3 mb-8">
          <div className="relative flex-1 max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-surface-500" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search leagues..."
              className="w-full pl-10 pr-3 py-2.5 bg-surface-800 border border-surface-700 rounded-xl text-sm text-white placeholder-surface-500 focus:outline-none focus:ring-1 focus:ring-gold-400"
            />
          </div>
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
                ? "No leagues have been created yet — be the first."
                : "Try adjusting your search or filters."}
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {filtered.map((league) => {
              const teamCount = league.team_count ?? 0;
              const slotsOpen = league.max_teams - teamCount;
              const isFull = slotsOpen <= 0;
              const TypeIcon = leagueTypeIcons[league.league_type] || Users;

              return (
                <Link
                  key={league.id}
                  href={`/leagues/${league.id}`}
                  className="group bg-surface-800 border border-surface-700 rounded-2xl p-6 hover:border-gold-400/30 transition-all hover:-translate-y-1 hover:shadow-xl hover:shadow-gold-400/5"
                >
                  <div className="flex items-center gap-3 mb-4">
                    <div className="w-12 h-12 rounded-xl bg-gold-400/10 border border-gold-400/20 flex items-center justify-center shrink-0">
                      <TypeIcon className="w-6 h-6 text-gold-400" />
                    </div>
                    <h3 className="text-lg font-bold text-white group-hover:text-gold-400 transition-colors truncate">
                      {league.name}
                    </h3>
                  </div>

                  <div className="flex items-center gap-4 mb-3">
                    <div className="flex items-baseline gap-1">
                      <span className="text-xl font-bold font-mono tabular-nums text-white">
                        {teamCount}
                      </span>
                      <span className="text-surface-500 text-sm font-mono">/{league.max_teams}</span>
                    </div>
                    {isFull ? (
                      <span className="text-xs text-surface-500 font-semibold">Full</span>
                    ) : (
                      <span className="text-xs text-gold-400 font-semibold">
                        {slotsOpen} slot{slotsOpen !== 1 ? "s" : ""} open
                      </span>
                    )}
                  </div>

                  <span className="inline-flex items-center gap-1.5 text-xs text-surface-400">
                    <span className="w-1.5 h-1.5 rounded-full bg-gold-400/60" />
                    {leagueTypeLabels[league.league_type] || league.league_type}
                  </span>

                  {league.description && (
                    <p className="text-surface-500 text-xs mt-3 line-clamp-2">{league.description}</p>
                  )}
                </Link>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
