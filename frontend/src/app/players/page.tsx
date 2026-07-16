"use client";

import { useState, useEffect, useCallback } from "react";
import { Search, Loader2, Trophy } from "lucide-react";
import { playersApi } from "@/lib/api-client";
import { PlayerAvatar, PlayerCardOverlay } from "@/components/PlayerAvatar";
import type { HoverPlayer } from "@/components/PlayerAvatar";
import PositionBadge, { POSITION_ORDER } from "@/components/PositionBadge";
import RankBadge from "@/components/ui/RankBadge";

interface PlayerRead {
  id: string;
  sleeper_id?: string;
  first_name: string;
  last_name: string;
  position: string;
  team: string | null;
  bye_week: number | null;
  injury_status: string | null;
  fantasy_positions?: string[] | null;
  age?: number | null;
  rank?: number;
  avatar_url?: string | null;
  headline_stats?: Record<string, number> | null;
}

const STAT_LABELS: Record<string, string> = {
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

function statLine(stats?: Record<string, number> | null): string {
  if (!stats) return "";
  return Object.entries(stats)
    .map(([key, value]) => `${Math.round(value * 10) / 10} ${STAT_LABELS[key] || key}`)
    .join(" · ");
}

// PlayerAvatar/PlayerCardOverlay were built for the draft room's richer player
// shape (full_name, rank_score, etc.) — adapt the plain /players response to match.
function toHoverPlayer(p: PlayerRead): HoverPlayer {
  return {
    id: p.id,
    full_name: `${p.first_name} ${p.last_name}`.trim(),
    first_name: p.first_name,
    last_name: p.last_name,
    position: p.position,
    team: p.team || "",
    age: p.age ?? null,
    number: null,
    bye_week: p.bye_week,
    injury_status: p.injury_status,
    fantasy_positions: p.fantasy_positions ?? null,
    avatar_url: p.avatar_url ?? null,
    sleeper_id: p.sleeper_id ?? null,
    rank_score: p.rank ?? 9999,
    pos_rank: 0,
    headline_stats: p.headline_stats ?? null,
  };
}

export default function PlayersPage() {
  const [players, setPlayers] = useState<PlayerRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [positionFilter, setPositionFilter] = useState("ALL");

  const [hoveredPlayer, setHoveredPlayer] = useState<HoverPlayer | null>(null);
  const [hoverPos, setHoverPos] = useState<{ x: number; y: number } | null>(null);
  const handleHover = useCallback(
    (player: HoverPlayer | null, el: HTMLElement | null) => {
      if (player && el) {
        setHoveredPlayer(player);
        const rect = el.getBoundingClientRect();
        setHoverPos({ x: rect.left + rect.width / 2, y: rect.top });
      } else {
        setHoveredPlayer(null);
        setHoverPos(null);
      }
    },
    [],
  );

  const showingProspects = !search.trim() && positionFilter === "ALL";

  const loadPlayers = useCallback(() => {
    setLoading(true);

    if (showingProspects) {
      playersApi
        .topProspects(100)
        .then((data) => setPlayers(Array.isArray(data) ? (data as PlayerRead[]) : []))
        .catch((err) => setError(err instanceof Error ? err.message : "Failed to load players"))
        .finally(() => setLoading(false));
      return;
    }

    const params: Record<string, string> = { limit: "100" };
    if (search.trim()) params.search = search.trim();
    if (positionFilter !== "ALL") params.position = positionFilter;

    playersApi
      .list(params)
      .then((data) => setPlayers(Array.isArray(data) ? (data as PlayerRead[]) : []))
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load players"))
      .finally(() => setLoading(false));
  }, [search, positionFilter, showingProspects]);

  useEffect(() => {
    const handle = setTimeout(loadPlayers, 300);
    return () => clearTimeout(handle);
  }, [loadPlayers]);

  return (
    <div className="min-h-screen">
      <section className="relative overflow-hidden border-b border-surface-700">
        <div className="absolute inset-0 bg-gradient-to-b from-surface-850 via-surface-900 to-surface-900" />
        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
          <h1 className="text-3xl md:text-4xl font-bold text-white tracking-tight">Players</h1>
          <p className="text-surface-400 mt-2 text-sm md:text-base">
            {showingProspects
              ? "Top 100 draft prospects, ranked. Search or filter to browse everyone else."
              : "Browse NFL players, positions, and status."}
          </p>
        </div>
      </section>

      <section className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Search + filters */}
        <div className="bg-surface-800/50 border border-surface-700 rounded-2xl p-4 mb-6">
          <div className="relative mb-3">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-surface-500" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by name..."
              className="w-full pl-10 pr-3 py-2.5 bg-surface-900 border border-surface-700 rounded-xl text-sm text-white placeholder-surface-500 focus:outline-none focus:ring-1 focus:ring-gold-400"
            />
          </div>
          <div className="flex flex-wrap gap-1.5">
            <button
              type="button"
              onClick={() => setPositionFilter("ALL")}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                positionFilter === "ALL"
                  ? "bg-gold-400/20 text-gold-400 border border-gold-400/30"
                  : "bg-surface-900 text-surface-400 border border-surface-700 hover:border-surface-500"
              }`}
            >
              All
            </button>
            {POSITION_ORDER.map((pos) => (
              <button
                key={pos}
                type="button"
                onClick={() => setPositionFilter(pos)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                  positionFilter === pos
                    ? "bg-gold-400/20 text-gold-400 border border-gold-400/30"
                    : "bg-surface-900 text-surface-400 border border-surface-700 hover:border-surface-500"
                }`}
              >
                {pos}
              </button>
            ))}
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-24">
            <Loader2 className="w-6 h-6 text-gold-400 animate-spin" />
          </div>
        ) : error ? (
          <div className="text-center py-24 text-surface-400 text-sm">{error}</div>
        ) : players.length === 0 ? (
          <div className="text-center py-24 text-surface-400 text-sm">
            No players found. If this is a fresh deployment, the Sleeper player sync may not have
            run yet.
          </div>
        ) : (
          <div className="bg-surface-800/50 border border-surface-700 rounded-2xl overflow-hidden divide-y divide-surface-700/50">
            {showingProspects && (
              <div className="flex items-center gap-2 px-4 py-2.5 bg-surface-900/50 text-xs font-semibold text-gold-400 uppercase tracking-wider">
                <Trophy className="w-3.5 h-3.5" />
                Top 100 Draft Prospects
              </div>
            )}
            {players.map((p) => {
              const hp = toHoverPlayer(p);
              return (
                <div
                  key={p.id}
                  className="flex items-center gap-3 px-4 py-3 hover:bg-surface-700/30 transition-colors"
                >
                  {showingProspects && p.rank && <RankBadge rank={p.rank} size="sm" />}
                  <PlayerAvatar player={hp} size="md" onHover={handleHover} />
                  <div
                    className="flex-1 min-w-0"
                    onMouseEnter={(e) => handleHover(hp, e.currentTarget)}
                    onMouseLeave={() => handleHover(null, null)}
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold text-white truncate">{hp.full_name}</span>
                      <PositionBadge pos={p.position} />
                    </div>
                    <div className="flex items-center gap-3 text-xs text-surface-500 mt-0.5">
                      <span>{p.team || "FA"}</span>
                      {p.bye_week && <span>Bye {p.bye_week}</span>}
                      {p.injury_status && p.injury_status !== "None" && (
                        <span className="text-yellow-400">{p.injury_status}</span>
                      )}
                    </div>
                    {p.headline_stats && Object.keys(p.headline_stats).length > 0 && (
                      <p className="text-[11px] text-surface-400 mt-0.5">
                        {statLine(p.headline_stats)}{" "}
                        <span className="text-surface-600">(last season)</span>
                      </p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      <PlayerCardOverlay player={hoveredPlayer} position={hoverPos} />
    </div>
  );
}
