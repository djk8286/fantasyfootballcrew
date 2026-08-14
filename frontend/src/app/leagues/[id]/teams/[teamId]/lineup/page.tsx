"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { lineupsApi, teamsApi } from "@/lib/api-client";
import PositionBadge from "@/components/PositionBadge";
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  Loader2,
  Save,
  RefreshCw,
  Sparkles,
  Plus,
  Minus,
} from "lucide-react";

interface RosterPlayer {
  id: string;
  full_name: string;
  position: string;
  team: string;
  injury_status: string | null;
  bye_week: number | null;
  avatar_url: string | null;
  season_points: number | null;
  season_points_year: number | null;
  is_starter: boolean;
}

interface LineupResponse {
  team_id: string;
  week: number;
  year: number;
  roster_slots: Record<string, number>;
  best_ball: boolean;
  has_lineup_set: boolean;
  starters: string[];
  roster: RosterPlayer[];
}

const CURRENT_YEAR = new Date().getFullYear();
const POSITION_ORDER = ["QB", "RB", "WR", "TE", "K", "DEF", "DL", "LB", "DB"];

function PlayerRow({
  player,
  onToggle,
  toggleDisabled,
  readOnly = false,
}: {
  player: RosterPlayer;
  onToggle: (id: string) => void;
  toggleDisabled: boolean;
  readOnly?: boolean;
}) {
  return (
    <div className="flex items-center gap-3 px-4 py-2.5 hover:bg-surface-800/40 transition-colors">
      <div className="w-8 h-8 rounded-full bg-surface-700 flex-shrink-0 overflow-hidden border border-surface-600">
        {player.avatar_url ? (
          <img src={player.avatar_url} alt={player.full_name} className="w-full h-full object-cover" />
        ) : (
          <div className="w-full h-full flex items-center justify-center">
            <span className="text-xs text-surface-500 font-bold">{player.full_name.charAt(0)}</span>
          </div>
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="text-sm font-medium text-white truncate">{player.full_name}</span>
          <PositionBadge pos={player.position} />
          {player.injury_status && (
            <span className="text-[10px] font-semibold text-red-400">{player.injury_status}</span>
          )}
        </div>
        <div className="text-[11px] text-surface-500">
          {player.team || "FA"}
          {player.bye_week ? ` · Bye ${player.bye_week}` : ""}
          {player.season_points != null && (
            <span className="text-gold-400/80 ml-2">
              {Math.round(player.season_points * 10) / 10} pts
              {player.season_points_year ? ` (${player.season_points_year})` : ""}
            </span>
          )}
        </div>
      </div>
      {readOnly ? (
        <span
          className={`inline-flex items-center px-2.5 py-1.5 rounded-lg text-[11px] font-bold shrink-0 ${
            player.is_starter ? "bg-gold-400/15 text-gold-400" : "bg-surface-700 text-surface-400"
          }`}
        >
          {player.is_starter ? "Starting" : "Bench"}
        </span>
      ) : (
        <button
          onClick={() => onToggle(player.id)}
          disabled={!player.is_starter && toggleDisabled}
          className={`inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11px] font-bold shrink-0 transition-all disabled:opacity-30 disabled:cursor-not-allowed ${
            player.is_starter
              ? "bg-surface-700 hover:bg-red-500/20 hover:text-red-400 text-surface-300"
              : "bg-gold-400 hover:bg-gold-300 text-surface-900"
          }`}
        >
          {player.is_starter ? (
            <><Minus className="w-3 h-3" /> Bench</>
          ) : (
            <><Plus className="w-3 h-3" /> Start</>
          )}
        </button>
      )}
    </div>
  );
}

export default function LineupPage() {
  const params = useParams();
  const leagueId = params.id as string;
  const teamId = params.teamId as string;

  const [week, setWeek] = useState(1);
  const [year] = useState(CURRENT_YEAR);
  const [data, setData] = useState<LineupResponse | null>(null);
  const [teamName, setTeamName] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [optimizing, setOptimizing] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  // Local starter-id set, decoupled from `data` so toggling is instant
  // without waiting on a round-trip -- only synced back to the server on
  // explicit Save.
  const [starterIds, setStarterIds] = useState<Set<string>>(new Set());

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    Promise.all([
      lineupsApi.get(teamId, week, year).catch(() => null),
      teamsApi.get(teamId).catch(() => null),
    ])
      .then(([lineupData, teamData]) => {
        if (!lineupData) {
          setError("Failed to load lineup");
          return;
        }
        const d = lineupData as LineupResponse;
        setData(d);
        setStarterIds(new Set(d.starters));
        if (teamData) setTeamName((teamData as { name?: string }).name || "");
      })
      .finally(() => setLoading(false));
  }, [teamId, week, year]);

  useEffect(() => {
    load();
  }, [load]);

  const totalSlots = data ? Object.values(data.roster_slots).reduce((a, b) => a + b, 0) : 0;
  const toggle = (playerId: string) => {
    setStarterIds((prev) => {
      const next = new Set(prev);
      if (next.has(playerId)) {
        next.delete(playerId);
      } else {
        if (next.size >= totalSlots) return prev; // full -- no-op, button is disabled anyway
        next.add(playerId);
      }
      return next;
    });
    setSaved(false);
  };

  const handleSave = async () => {
    setSaving(true);
    setError("");
    try {
      await lineupsApi.set(teamId, week, year, Array.from(starterIds));
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
      load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to save lineup");
    } finally {
      setSaving(false);
    }
  };

  const handleOptimize = async () => {
    setOptimizing(true);
    setError("");
    try {
      const result = await lineupsApi.optimize(teamId, week, year) as { starters: string[] };
      setStarterIds(new Set(result.starters));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to auto-fill lineup");
    } finally {
      setOptimizing(false);
    }
  };

  if (loading && !data) {
    return (
      <div className="min-h-screen bg-surface-900 flex items-center justify-center">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 border-2 border-gold-400 border-t-transparent rounded-full animate-spin" />
          <span className="text-surface-400">Loading lineup...</span>
        </div>
      </div>
    );
  }

  const roster = data?.roster || [];
  const starters = roster
    .filter((p) => starterIds.has(p.id))
    .sort((a, b) => POSITION_ORDER.indexOf(a.position) - POSITION_ORDER.indexOf(b.position));
  const bench = roster
    .filter((p) => !starterIds.has(p.id))
    .sort((a, b) => POSITION_ORDER.indexOf(a.position) - POSITION_ORDER.indexOf(b.position));
  const atCapacity = starterIds.size >= totalSlots;

  return (
    <div className="min-h-screen bg-surface-900">
      <div className="sticky top-0 z-40 bg-surface-900/95 backdrop-blur-md border-b border-surface-700">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-3">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3 min-w-0">
              <Link
                href={`/leagues/${leagueId}/teams/${teamId}`}
                className="text-surface-400 hover:text-white transition-colors shrink-0"
              >
                <ArrowLeft className="w-5 h-5" />
              </Link>
              <div className="min-w-0">
                <h1 className="text-lg font-bold text-white truncate">Set Lineup</h1>
                {teamName && <span className="text-surface-400 text-xs truncate">{teamName}</span>}
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button
                onClick={() => setWeek((w) => Math.max(1, w - 1))}
                disabled={week <= 1}
                title="Previous week"
                aria-label="Previous week"
                className="p-1.5 rounded-lg text-surface-400 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <span className="text-sm font-semibold text-white w-16 text-center">Week {week}</span>
              <button
                onClick={() => setWeek((w) => Math.min(18, w + 1))}
                disabled={week >= 18}
                title="Next week"
                aria-label="Next week"
                className="p-1.5 rounded-lg text-surface-400 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {error && (
          <div className="mb-4 p-3 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400 text-sm" role="alert">
            {error}
          </div>
        )}

        {data?.best_ball ? (
          <div className="mb-4 p-3 bg-gold-400/10 border border-gold-400/30 rounded-xl text-gold-300 text-sm">
            This league uses Best-Ball auto-lineups -- your highest-scoring eligible starters are
            selected automatically from real per-week results, no lineup management needed.
          </div>
        ) : (
          data && !data.has_lineup_set && (
            <div className="mb-4 p-3 bg-blue-500/10 border border-blue-500/30 rounded-xl text-blue-300 text-sm">
              No lineup set for week {week} yet -- this team is currently scoring its whole roster.
              Set starters below and save to switch to starter-only scoring for this week.
            </div>
          )
        )}

        {!data?.best_ball && (
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <span className="text-sm text-surface-400">
                Starters: <span className={`font-bold ${atCapacity ? "text-gold-400" : "text-white"}`}>{starterIds.size}</span> / {totalSlots}
              </span>
              <button
                onClick={handleOptimize}
                disabled={optimizing}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-surface-800 border border-surface-700 text-surface-300 hover:text-gold-400 hover:border-gold-400/40 transition-all disabled:opacity-50"
              >
                {optimizing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
                Auto-Fill Best Lineup
              </button>
            </div>
            <button
              onClick={handleSave}
              disabled={saving}
              className={`inline-flex items-center gap-1.5 px-5 py-2 rounded-lg text-xs font-bold transition-all ${
                saved
                  ? "bg-green-500 text-white"
                  : "bg-gold-400 hover:bg-gold-300 text-surface-900 disabled:opacity-50"
              }`}
            >
              {saving ? (
                <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Saving...</>
              ) : saved ? (
                <><RefreshCw className="w-3.5 h-3.5" /> Saved!</>
              ) : (
                <><Save className="w-3.5 h-3.5" /> Save Lineup</>
              )}
            </button>
          </div>
        )}
        {data?.best_ball && (
          <div className="flex items-center justify-end mb-4">
            <span className="text-sm text-surface-400">
              Starters: <span className="font-bold text-gold-400">{starterIds.size}</span> / {totalSlots}
            </span>
          </div>
        )}

        <div className="space-y-4">
          <div className="bg-surface-800/60 border border-surface-700 rounded-2xl overflow-hidden">
            <div className="px-4 py-3 bg-surface-800 border-b border-surface-700">
              <h3 className="text-white font-bold text-sm">Starting ({starters.length})</h3>
            </div>
            {starters.length === 0 ? (
              <div className="p-6 text-center text-surface-500 text-sm">
                No starters set. Add players from your bench below, or auto-fill.
              </div>
            ) : (
              <div className="divide-y divide-surface-700/50">
                {starters.map((p) => (
                  <PlayerRow key={p.id} player={{ ...p, is_starter: true }} onToggle={toggle} toggleDisabled={false} readOnly={!!data?.best_ball} />
                ))}
              </div>
            )}
          </div>

          <div className="bg-surface-800/60 border border-surface-700 rounded-2xl overflow-hidden">
            <div className="px-4 py-3 bg-surface-800 border-b border-surface-700">
              <h3 className="text-white font-bold text-sm">Bench ({bench.length})</h3>
            </div>
            {bench.length === 0 ? (
              <div className="p-6 text-center text-surface-500 text-sm">Everyone&apos;s starting.</div>
            ) : (
              <div className="divide-y divide-surface-700/50">
                {bench.map((p) => (
                  <PlayerRow key={p.id} player={{ ...p, is_starter: false }} onToggle={toggle} toggleDisabled={atCapacity} readOnly={!!data?.best_ball} />
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
