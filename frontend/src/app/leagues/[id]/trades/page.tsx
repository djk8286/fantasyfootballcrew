"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ChevronLeft, ArrowLeftRight, Send } from "lucide-react";
import { leaguesApi, teamsApi, tradesApi, playersApi, getCurrentUserId } from "@/lib/api-client";

interface Team {
  id: string;
  name: string;
  owner_id: string | null;
  co_owner_id: string | null;
  roster: string[] | null;
}

interface League {
  id: string;
  name: string;
}

interface TradeItem {
  id: string;
  team_id: string;
  status: string;
  details?: {
    target_team_id?: string;
    offered_player_ids?: string[];
    requested_player_ids?: string[];
  };
  processed_at: string;
}

const statusColor: Record<string, string> = {
  pending: "bg-yellow-500/15 text-yellow-400 border-yellow-500/25",
  approved: "bg-green-500/15 text-green-400 border-green-500/25",
  denied: "bg-red-500/15 text-red-400 border-red-500/25",
};

export default function TradesPage() {
  const params = useParams();
  const leagueId = params.id as string;

  const [league, setLeague] = useState<League | null>(null);
  const [teams, setTeams] = useState<Team[]>([]);
  const [trades, setTrades] = useState<TradeItem[]>([]);
  const [playerNames, setPlayerNames] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const [targetTeamId, setTargetTeamId] = useState("");
  const [offeredIds, setOfferedIds] = useState<string[]>([]);
  const [requestedIds, setRequestedIds] = useState<string[]>([]);

  const userId = getCurrentUserId();
  const myTeam = teams.find((t) => t.owner_id === userId || t.co_owner_id === userId);
  const targetTeam = teams.find((t) => t.id === targetTeamId);

  const loadTrades = useCallback(async () => {
    try {
      const data = await tradesApi.list(leagueId);
      setTrades(Array.isArray(data) ? (data as TradeItem[]) : []);
    } catch {
      // silent
    }
  }, [leagueId]);

  useEffect(() => {
    Promise.all([
      leaguesApi.get(leagueId) as Promise<League>,
      teamsApi.getByLeague(leagueId) as Promise<Team[]>,
    ])
      .then(([l, t]) => {
        setLeague(l);
        setTeams(t);
      })
      .catch(() => setError("Failed to load league"))
      .finally(() => setLoading(false));
    loadTrades();
  }, [leagueId, loadTrades]);

  // Resolve player names for anything shown (my roster, target roster, trade history)
  useEffect(() => {
    const ids = new Set<string>();
    teams.forEach((t) => (t.roster || []).forEach((id) => ids.add(id)));
    trades.forEach((t) => {
      (t.details?.offered_player_ids || []).forEach((id) => ids.add(id));
      (t.details?.requested_player_ids || []).forEach((id) => ids.add(id));
    });
    const unresolved = [...ids].filter((id) => !(id in playerNames));
    if (unresolved.length === 0) return;

    Promise.all(
      unresolved.map((id) =>
        playersApi
          .get(id)
          .then((p) => {
            const player = p as { first_name?: string; last_name?: string };
            return [id, `${player.first_name ?? ""} ${player.last_name ?? ""}`.trim() || id] as const;
          })
          .catch(() => [id, id] as const),
      ),
    ).then((pairs) => {
      setPlayerNames((prev) => ({ ...prev, ...Object.fromEntries(pairs) }));
    });
  }, [teams, trades, playerNames]);

  const playerLabel = (id: string) => playerNames[id] || id;

  const toggleId = (list: string[], setList: (v: string[]) => void, id: string) => {
    setList(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!myTeam || !targetTeamId) return;
    setError("");
    setSubmitting(true);
    try {
      await tradesApi.propose(leagueId, {
        team_id: myTeam.id,
        target_team_id: targetTeamId,
        offered_player_ids: offeredIds,
        requested_player_ids: requestedIds,
      });
      setOfferedIds([]);
      setRequestedIds([]);
      setTargetTeamId("");
      await loadTrades();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to propose trade");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-surface-900 flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-gold-400 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-surface-900">
      <div className="sticky top-0 z-40 bg-surface-900/95 backdrop-blur-md border-b border-surface-700">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-3 flex items-center gap-3">
          <Link href={`/leagues/${leagueId}`} className="text-surface-400 hover:text-white transition-colors">
            <ChevronLeft className="w-5 h-5" />
          </Link>
          <h1 className="text-lg font-semibold text-white">{league?.name} — Trades</h1>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        {error && (
          <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm">
            {error}
          </div>
        )}

        {/* Propose trade */}
        <div className="bg-surface-800 border border-surface-700 rounded-2xl p-6">
          <h2 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
            <ArrowLeftRight className="w-4 h-4 text-gold-400" />
            Propose a Trade
          </h2>

          {!myTeam ? (
            <p className="text-surface-400 text-sm">
              You need to own a team in this league to propose a trade.
            </p>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-5">
              <div>
                <label className="block text-xs text-surface-400 mb-1.5">Trade with</label>
                <select
                  value={targetTeamId}
                  onChange={(e) => {
                    setTargetTeamId(e.target.value);
                    setRequestedIds([]);
                  }}
                  className="w-full px-3 py-2 bg-surface-900 border border-surface-600 rounded-lg text-white text-sm focus:outline-none focus:ring-1 focus:ring-gold-400"
                >
                  <option value="">Select a team...</option>
                  {teams
                    .filter((t) => t.id !== myTeam.id)
                    .map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name}
                      </option>
                    ))}
                </select>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
                <div>
                  <p className="text-xs text-surface-400 mb-1.5">You give ({myTeam.name})</p>
                  <div className="space-y-1.5 max-h-48 overflow-y-auto">
                    {(myTeam.roster || []).length === 0 && (
                      <p className="text-surface-600 text-xs">No players on your roster.</p>
                    )}
                    {(myTeam.roster || []).map((pid) => (
                      <label
                        key={pid}
                        className="flex items-center gap-2 text-sm text-surface-300 cursor-pointer"
                      >
                        <input
                          type="checkbox"
                          checked={offeredIds.includes(pid)}
                          onChange={() => toggleId(offeredIds, setOfferedIds, pid)}
                          className="accent-gold-400"
                        />
                        {playerLabel(pid)}
                      </label>
                    ))}
                  </div>
                </div>

                <div>
                  <p className="text-xs text-surface-400 mb-1.5">
                    You get {targetTeam ? `(${targetTeam.name})` : ""}
                  </p>
                  <div className="space-y-1.5 max-h-48 overflow-y-auto">
                    {!targetTeam && (
                      <p className="text-surface-600 text-xs">Select a team first.</p>
                    )}
                    {targetTeam && (targetTeam.roster || []).length === 0 && (
                      <p className="text-surface-600 text-xs">That team has no players.</p>
                    )}
                    {(targetTeam?.roster || []).map((pid) => (
                      <label
                        key={pid}
                        className="flex items-center gap-2 text-sm text-surface-300 cursor-pointer"
                      >
                        <input
                          type="checkbox"
                          checked={requestedIds.includes(pid)}
                          onChange={() => toggleId(requestedIds, setRequestedIds, pid)}
                          className="accent-gold-400"
                        />
                        {playerLabel(pid)}
                      </label>
                    ))}
                  </div>
                </div>
              </div>

              <button
                type="submit"
                disabled={submitting || !targetTeamId || (offeredIds.length === 0 && requestedIds.length === 0)}
                className="inline-flex items-center gap-2 bg-gold-400 hover:bg-gold-300 text-surface-900 px-5 py-2.5 rounded-xl text-sm font-semibold transition-all disabled:opacity-50"
              >
                <Send className="w-4 h-4" />
                {submitting ? "Sending..." : "Propose Trade"}
              </button>
            </form>
          )}
        </div>

        {/* Trade history */}
        <div className="bg-surface-800 border border-surface-700 rounded-2xl p-6">
          <h2 className="text-sm font-semibold text-white mb-4">Trade History</h2>
          {trades.length === 0 ? (
            <p className="text-surface-500 text-sm">No trades yet.</p>
          ) : (
            <div className="space-y-3">
              {trades.map((t) => {
                const proposer = teams.find((tm) => tm.id === t.team_id);
                const target = teams.find((tm) => tm.id === t.details?.target_team_id);
                return (
                  <div
                    key={t.id}
                    className="border border-surface-700 rounded-xl p-4 flex flex-col gap-2"
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-white font-medium">
                        {proposer?.name || "Unknown"} ↔ {target?.name || "Unknown"}
                      </span>
                      <span
                        className={`px-2.5 py-0.5 rounded-full text-[11px] font-semibold border ${
                          statusColor[t.status] || statusColor.pending
                        }`}
                      >
                        {t.status}
                      </span>
                    </div>
                    <p className="text-xs text-surface-400">
                      Offered: {(t.details?.offered_player_ids || []).map(playerLabel).join(", ") || "—"}
                    </p>
                    <p className="text-xs text-surface-400">
                      Requested: {(t.details?.requested_player_ids || []).map(playerLabel).join(", ") || "—"}
                    </p>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
