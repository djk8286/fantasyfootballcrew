"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ChevronLeft, ListOrdered, Send, X, PlayCircle } from "lucide-react";
import { leaguesApi, teamsApi, waiversApi, playersApi, getCurrentUserId } from "@/lib/api-client";

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
  commissioner_id: string;
  co_commissioner_ids: string[] | null;
}

interface Claim {
  id: string;
  team_id: string;
  status: string;
  details?: { add_player_id?: string; drop_player_id?: string | null };
  processed_at: string;
}

interface PlayerSearchResult {
  id: string;
  first_name: string;
  last_name: string;
  position: string;
  team: string | null;
}

interface ProcessReport {
  granted: { team_id: string; add_player_id: string; drop_player_id?: string | null }[];
  denied: { team_id: string; add_player_id?: string; reason?: string }[];
  updated_priority: string[];
}

const statusColor: Record<string, string> = {
  pending: "bg-yellow-500/15 text-yellow-400 border-yellow-500/25",
  approved: "bg-green-500/15 text-green-400 border-green-500/25",
  denied: "bg-red-500/15 text-red-400 border-red-500/25",
};

export default function WaiversPage() {
  const params = useParams();
  const leagueId = params.id as string;

  const [league, setLeague] = useState<League | null>(null);
  const [teams, setTeams] = useState<Team[]>([]);
  const [claims, setClaims] = useState<Claim[]>([]);
  const [priority, setPriority] = useState<{ id: string; name: string }[]>([]);
  const [playerNames, setPlayerNames] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [processReport, setProcessReport] = useState<ProcessReport | null>(null);
  const [processing, setProcessing] = useState(false);

  const [search, setSearch] = useState("");
  const [searchResults, setSearchResults] = useState<PlayerSearchResult[]>([]);
  const [addPlayerId, setAddPlayerId] = useState("");
  const [dropPlayerId, setDropPlayerId] = useState("");

  const userId = getCurrentUserId();
  const myTeam = teams.find((t) => t.owner_id === userId || t.co_owner_id === userId);
  const isCommissioner =
    league && (league.commissioner_id === userId || league.co_commissioner_ids?.includes(userId || ""));

  const loadClaims = useCallback(async () => {
    try {
      const data = await waiversApi.listClaims(leagueId);
      setClaims(Array.isArray(data) ? (data as Claim[]) : []);
    } catch {
      // silent
    }
  }, [leagueId]);

  const loadPriority = useCallback(async () => {
    try {
      const data = (await waiversApi.getPriority(leagueId)) as { priority: { id: string; name: string }[] };
      setPriority(data.priority || []);
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
    loadClaims();
    loadPriority();
  }, [leagueId, loadClaims, loadPriority]);

  // Resolve names for roster players (drop candidates) + claim history
  useEffect(() => {
    const ids = new Set<string>();
    (myTeam?.roster || []).forEach((id) => ids.add(id));
    claims.forEach((c) => {
      if (c.details?.add_player_id) ids.add(c.details.add_player_id);
      if (c.details?.drop_player_id) ids.add(c.details.drop_player_id);
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
    ).then((pairs) => setPlayerNames((prev) => ({ ...prev, ...Object.fromEntries(pairs) })));
  }, [myTeam, claims, playerNames]);

  const playerLabel = (id: string) => playerNames[id] || id;

  useEffect(() => {
    if (search.trim().length < 2) {
      setSearchResults([]);
      return;
    }
    const handle = setTimeout(() => {
      playersApi
        .list({ search: search.trim(), limit: "10" })
        .then((data) => setSearchResults(Array.isArray(data) ? (data as PlayerSearchResult[]) : []))
        .catch(() => setSearchResults([]));
    }, 300);
    return () => clearTimeout(handle);
  }, [search]);

  const handleSubmitClaim = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!myTeam || !addPlayerId) return;
    setError("");
    setSubmitting(true);
    try {
      await waiversApi.submitClaim(leagueId, {
        team_id: myTeam.id,
        add_player_id: addPlayerId,
        drop_player_id: dropPlayerId || undefined,
      });
      setAddPlayerId("");
      setDropPlayerId("");
      setSearch("");
      setSearchResults([]);
      await loadClaims();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit claim");
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancelClaim = async (claimId: string) => {
    try {
      await waiversApi.cancelClaim(leagueId, claimId);
      await loadClaims();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to cancel claim");
    }
  };

  const handleProcess = async () => {
    setProcessing(true);
    setError("");
    try {
      const report = (await waiversApi.process(leagueId)) as ProcessReport;
      setProcessReport(report);
      await Promise.all([loadClaims(), loadPriority()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to process waivers");
    } finally {
      setProcessing(false);
    }
  };

  const teamMap = Object.fromEntries(teams.map((t) => [t.id, t.name]));

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
          <h1 className="text-lg font-semibold text-white">{league?.name} — Waivers</h1>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        {error && (
          <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm">
            {error}
          </div>
        )}

        {/* Submit a claim */}
        <div className="bg-surface-800 border border-surface-700 rounded-2xl p-6">
          <h2 className="text-sm font-semibold text-white mb-4">Submit a Waiver Claim</h2>

          {!myTeam ? (
            <p className="text-surface-400 text-sm">You need to own a team in this league to submit a claim.</p>
          ) : (
            <form onSubmit={handleSubmitClaim} className="space-y-4">
              <div>
                <label className="block text-xs text-surface-400 mb-1.5">Search free agents to add</label>
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search by name..."
                  className="w-full px-3 py-2 bg-surface-900 border border-surface-600 rounded-lg text-white text-sm placeholder-surface-500 focus:outline-none focus:ring-1 focus:ring-gold-400"
                />
                {searchResults.length > 0 && (
                  <div className="mt-2 border border-surface-700 rounded-lg overflow-hidden max-h-48 overflow-y-auto">
                    {searchResults.map((p) => (
                      <button
                        key={p.id}
                        type="button"
                        onClick={() => {
                          setAddPlayerId(p.id);
                          setSearch(`${p.first_name} ${p.last_name}`);
                          setSearchResults([]);
                        }}
                        className={`w-full text-left px-3 py-2 text-sm hover:bg-surface-700 transition-colors ${
                          addPlayerId === p.id ? "bg-surface-700 text-gold-400" : "text-surface-300"
                        }`}
                      >
                        {p.first_name} {p.last_name}{" "}
                        <span className="text-surface-500 text-xs">
                          {p.position} {p.team ? `· ${p.team}` : ""}
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </div>

              <div>
                <label className="block text-xs text-surface-400 mb-1.5">Drop (optional)</label>
                <select
                  value={dropPlayerId}
                  onChange={(e) => setDropPlayerId(e.target.value)}
                  className="w-full px-3 py-2 bg-surface-900 border border-surface-600 rounded-lg text-white text-sm focus:outline-none focus:ring-1 focus:ring-gold-400"
                >
                  <option value="">No drop</option>
                  {(myTeam.roster || []).map((pid) => (
                    <option key={pid} value={pid}>
                      {playerLabel(pid)}
                    </option>
                  ))}
                </select>
              </div>

              <button
                type="submit"
                disabled={submitting || !addPlayerId}
                className="inline-flex items-center gap-2 bg-gold-400 hover:bg-gold-300 text-surface-900 px-5 py-2.5 rounded-xl text-sm font-semibold transition-all disabled:opacity-50"
              >
                <Send className="w-4 h-4" />
                {submitting ? "Submitting..." : "Submit Claim"}
              </button>
            </form>
          )}
        </div>

        {/* My claims */}
        {myTeam && (
          <div className="bg-surface-800 border border-surface-700 rounded-2xl p-6">
            <h2 className="text-sm font-semibold text-white mb-4">Your Claims</h2>
            {claims.filter((c) => c.team_id === myTeam.id).length === 0 ? (
              <p className="text-surface-500 text-sm">No claims yet.</p>
            ) : (
              <div className="space-y-2">
                {claims
                  .filter((c) => c.team_id === myTeam.id)
                  .map((c) => (
                    <div
                      key={c.id}
                      className="flex items-center justify-between border border-surface-700 rounded-xl p-3"
                    >
                      <div className="text-sm text-surface-300">
                        Add <span className="text-white font-medium">{playerLabel(c.details?.add_player_id || "")}</span>
                        {c.details?.drop_player_id && (
                          <>
                            {" "}
                            / Drop <span className="text-white font-medium">{playerLabel(c.details.drop_player_id)}</span>
                          </>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        <span
                          className={`px-2.5 py-0.5 rounded-full text-[11px] font-semibold border ${
                            statusColor[c.status] || statusColor.pending
                          }`}
                        >
                          {c.status}
                        </span>
                        {c.status === "pending" && (
                          <button
                            type="button"
                            onClick={() => handleCancelClaim(c.id)}
                            className="text-surface-500 hover:text-red-400 transition-colors"
                            title="Cancel claim"
                          >
                            <X className="w-4 h-4" />
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
              </div>
            )}
          </div>
        )}

        {/* Commissioner: priority + process */}
        {isCommissioner && (
          <div className="bg-surface-800 border border-surface-700 rounded-2xl p-6">
            <h2 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
              <ListOrdered className="w-4 h-4 text-gold-400" />
              Waiver Priority (Commissioner)
            </h2>
            <ol className="space-y-1.5 mb-4">
              {priority.map((p, i) => (
                <li key={p.id} className="text-sm text-surface-300">
                  <span className="text-surface-500 mr-2">{i + 1}.</span>
                  {p.name}
                </li>
              ))}
            </ol>
            <button
              type="button"
              onClick={handleProcess}
              disabled={processing}
              className="inline-flex items-center gap-2 bg-gold-400 hover:bg-gold-300 text-surface-900 px-5 py-2.5 rounded-xl text-sm font-semibold transition-all disabled:opacity-50"
            >
              <PlayCircle className="w-4 h-4" />
              {processing ? "Processing..." : "Process Waivers"}
            </button>

            {processReport && (
              <div className="mt-4 space-y-2 text-sm">
                {processReport.granted.map((g, i) => (
                  <p key={`g-${i}`} className="text-green-400">
                    ✓ {teamMap[g.team_id] || g.team_id} was awarded {playerLabel(g.add_player_id)}
                  </p>
                ))}
                {processReport.denied.map((d, i) => (
                  <p key={`d-${i}`} className="text-red-400">
                    ✗ {teamMap[d.team_id] || d.team_id} claim denied{d.reason ? ` (${d.reason})` : ""}
                  </p>
                ))}
                {processReport.granted.length === 0 && processReport.denied.length === 0 && (
                  <p className="text-surface-500">No pending claims to process.</p>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
