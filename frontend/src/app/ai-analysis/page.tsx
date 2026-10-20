"use client";

import { leagueLabel, historySummaryLabel } from "@/lib/league-label";
import Markdown from "@/components/Markdown";
import { tradeOptionLabel, defaultComparePair } from "@/lib/trade-label";

import { useState, useEffect, useCallback } from "react";
import { Bot, Sparkles, ArrowLeftRight, TrendingUp, Send, Loader2, Users, Scale } from "lucide-react";
import { leaguesApi, teamsApi, tradesApi, playersApi, aiApi, getCurrentUserId, isCurrentUser, isLoggedIn } from "@/lib/api-client";

interface League {
  id: string;
  name: string;
  created_at?: string | null;
}

interface Team {
  id: string;
  name: string;
  owner_id: string | null;
  co_owner_id: string | null;
}

interface TradeItem {
  id: string;
  team_id: string;
  status: string;
  details?: { target_team_id?: string; offered_player_ids?: string[]; requested_player_ids?: string[] };
}

interface HistoryItem {
  id: string;
  league_id: string | null;
  summary: string;
  result: string;
  created_at: string | null;
}

interface RosterTeam {
  id: string;
  name: string;
  roster: string[] | null;
}

interface RosterPlayerOption {
  id: string;
  first_name: string;
  last_name: string;
  position: string;
}

type Tab = "lineup" | "trade" | "bet" | "compare-teams" | "compare-players";

export default function AIAnalysisPage() {
  const [activeTab, setActiveTab] = useState<Tab>("lineup");
  const loggedIn = isLoggedIn();

  return (
    <div className="min-h-screen">
      <section className="relative overflow-hidden border-b border-surface-700">
        <div className="absolute inset-0 bg-gradient-to-b from-surface-850 via-surface-900 to-surface-900" />
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[700px] h-[400px] bg-purple-400/5 rounded-full blur-3xl" />
        <div className="relative max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-14 text-center">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-purple-400 to-pink-500 p-3 mx-auto mb-4">
            <Bot className="w-full h-full text-white" />
          </div>
          <h1 className="text-3xl md:text-4xl font-bold text-white tracking-tight mb-3">
            AI Analysis
          </h1>
          <p className="text-surface-400 max-w-xl mx-auto">
            Lineup optimization, trade evaluation, and betting angles — powered by AI that
            considers your actual roster and scoring settings.
          </p>
        </div>
      </section>

      <section className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
        {!loggedIn ? (
          <div className="text-center py-16 text-surface-400 text-sm">
            Log in to use AI analysis.
          </div>
        ) : (
          <>
            <div className="flex flex-wrap gap-1 bg-surface-800 rounded-xl p-1 border border-surface-700 mb-8">
              {[
                { id: "lineup" as Tab, label: "Lineup", icon: Sparkles },
                { id: "trade" as Tab, label: "Trade", icon: ArrowLeftRight },
                { id: "bet" as Tab, label: "Bet", icon: TrendingUp },
                { id: "compare-teams" as Tab, label: "Compare Teams", icon: Users },
                { id: "compare-players" as Tab, label: "Compare Players", icon: Scale },
              ].map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => setActiveTab(id)}
                  className={`flex-1 min-w-[calc(50%-0.125rem)] sm:min-w-0 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold transition-all ${
                    activeTab === id
                      ? "bg-surface-700 text-white shadow-sm"
                      : "text-surface-400 hover:text-white"
                  }`}
                >
                  <Icon className="w-4 h-4" />
                  {label}
                </button>
              ))}
            </div>

            {activeTab === "lineup" && <LineupTab />}
            {activeTab === "trade" && <TradeTab />}
            {activeTab === "bet" && <BetTab />}
            {activeTab === "compare-teams" && <CompareTeamsTab />}
            {activeTab === "compare-players" && <ComparePlayersTab />}
          </>
        )}
      </section>
    </div>
  );
}

function AnalysisResult({ analysis }: { analysis: string }) {
  const notConfigured = analysis.startsWith("AI Analysis: LLM API not configured");
  return (
    <div
      className={`mt-6 p-5 rounded-2xl border text-sm leading-relaxed ${
        notConfigured
          ? "bg-surface-800/50 border-surface-700 text-surface-400 whitespace-pre-wrap"
          : "bg-purple-400/5 border-purple-400/20 text-surface-200"
      }`}
    >
      {/* Model output is Markdown; rendered safely (no raw HTML). */}
      {notConfigured ? analysis : <Markdown text={analysis} />}
    </div>
  );
}

// Past results for the current tool (scoped by league where the tool
// itself is), newest first. Clicking one just redisplays its saved
// result -- these tools are one-shot Q&A, not a re-runnable chat, so
// there's nothing to "continue," only to look back at.
// The user's leagues (once per page) so Recent rows can tell same-named
// leagues apart.
let myLeaguesOnce: Promise<League[]> | null = null;
function useMyLeagues(): League[] {
  const [leagues, setLeagues] = useState<League[]>([]);
  useEffect(() => {
    myLeaguesOnce ??= leaguesApi
      .list({ mine: true })
      .then((d) => (Array.isArray(d) ? (d as League[]) : []))
      .catch(() => []);
    let alive = true;
    myLeaguesOnce.then((l) => alive && setLeagues(l));
    return () => {
      alive = false;
    };
  }, []);
  return leagues;
}

function HistoryList({ items, onSelect }: { items: HistoryItem[]; onSelect: (result: string) => void }) {
  const leagues = useMyLeagues();
  if (items.length === 0) return null;
  return (
    <div className="mt-8">
      <h3 className="text-xs font-semibold text-surface-400 uppercase tracking-wide mb-2">
        Recent
      </h3>
      <div className="space-y-1.5">
        {items.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => onSelect(item.result)}
            className="w-full flex items-center justify-between gap-3 text-left px-3 py-2 rounded-lg bg-surface-800/50 border border-surface-700 hover:border-gold-400/40 text-sm text-surface-300 hover:text-white transition-all"
          >
            <span className="truncate">{historySummaryLabel(item, leagues)}</span>
            {item.created_at && (
              <span className="text-xs text-surface-500 shrink-0">
                {new Date(item.created_at).toLocaleString(undefined, { month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit" })}
              </span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}

function LineupTab() {
  const [leagues, setLeagues] = useState<League[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);
  const [leagueId, setLeagueId] = useState("");
  const [teamId, setTeamId] = useState("");
  const [analysis, setAnalysis] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [history, setHistory] = useState<HistoryItem[]>([]);

  const userId = getCurrentUserId();
  const [teamsLoading, setTeamsLoading] = useState(false);

  const loadHistory = useCallback((lid: string) => {
    aiApi
      .history("lineup", lid || undefined)
      .then((data) => setHistory((data as { history: HistoryItem[] }).history))
      .catch(() => {});
  }, []);

  useEffect(() => {
    leaguesApi
      .list({ mine: true })
      .then((data) => setLeagues(Array.isArray(data) ? (data as League[]) : []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!leagueId) {
      setTeams([]);
      setTeamId("");
      return;
    }
    // Ignore responses for a league that's no longer selected: an older,
    // slower response used to land last and reset teamId to "", leaving the
    // select *showing* a team (a controlled <select> with an unmatched
    // value renders its first option) while Analyze stayed disabled.
    let stale = false;
    setTeamsLoading(true);
    teamsApi
      .getByLeague(leagueId)
      .then((data) => {
        if (stale) return;
        const all = Array.isArray(data) ? (data as Team[]) : [];
        const mine = all.filter((t) => isCurrentUser(t.owner_id) || isCurrentUser(t.co_owner_id));
        setTeams(mine);
        setTeamId(mine[0]?.id || "");
      })
      .catch(() => {})
      .finally(() => { if (!stale) setTeamsLoading(false); });
    return () => { stale = true; };
  }, [leagueId, userId]);

  // Past lineup analyses -- scoped to whichever league is selected (or
  // this user's lineup history across every league, before one is).
  useEffect(() => {
    loadHistory(leagueId);
  }, [leagueId, loadHistory]);

  const handleSubmit = async () => {
    if (!teamId) return;
    setLoading(true);
    setError("");
    setAnalysis("");
    try {
      const res = (await aiApi.lineup(teamId)) as { analysis: string };
      setAnalysis(res.analysis);
      loadHistory(leagueId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to get analysis");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div className="space-y-4">
        <div>
          <label className="block text-xs text-surface-400 mb-1.5">League</label>
          <select
            value={leagueId}
            onChange={(e) => setLeagueId(e.target.value)}
            className="w-full px-3 py-2.5 bg-surface-800 border border-surface-700 rounded-xl text-sm text-white focus:outline-none focus:ring-1 focus:ring-gold-400"
          >
            <option value="">Select a league...</option>
            {leagues.map((l) => (
              <option key={l.id} value={l.id}>{leagueLabel(l, leagues)}</option>
            ))}
          </select>
        </div>
        {leagueId && (
          <div>
            <label className="block text-xs text-surface-400 mb-1.5">Your Team</label>
            {teams.length === 0 ? (
              <p className="text-surface-500 text-sm">You don&apos;t own a team in this league.</p>
            ) : (
              <select
                value={teamId}
                onChange={(e) => setTeamId(e.target.value)}
                className="w-full px-3 py-2.5 bg-surface-800 border border-surface-700 rounded-xl text-sm text-white focus:outline-none focus:ring-1 focus:ring-gold-400"
              >
                {teams.map((t) => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
              </select>
            )}
          </div>
        )}
      </div>

      {error && <p className="text-red-400 text-sm mt-3">{error}</p>}

      {!teamId && !loading && (
        <p className="text-surface-500 text-xs mt-3" data-testid="analyze-disabled-reason">
          {!leagueId
            ? "Select a league to analyze your lineup."
            : teamsLoading
              ? "Loading your teams..."
              : teams.length === 0
                ? "You need to own a team in this league to analyze its lineup."
                : "Select your team."}
        </p>
      )}

      <button
        type="button"
        onClick={handleSubmit}
        disabled={!teamId || loading}
        className="mt-5 inline-flex items-center gap-2 bg-gold-400 hover:bg-gold-300 text-surface-900 px-5 py-2.5 rounded-xl text-sm font-semibold transition-all disabled:opacity-50"
      >
        {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
        Analyze Lineup
      </button>

      {analysis && <AnalysisResult analysis={analysis} />}
      <HistoryList items={history} onSelect={setAnalysis} />
    </div>
  );
}

function TradeTab() {
  const [leagues, setLeagues] = useState<League[]>([]);
  const [trades, setTrades] = useState<TradeItem[]>([]);
  const [leagueId, setLeagueId] = useState("");
  const [tradeId, setTradeId] = useState("");
  const [analysis, setAnalysis] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [teamNames, setTeamNames] = useState<Record<string, string>>({});
  const [playerNames, setPlayerNames] = useState<Record<string, string>>({});

  const loadHistory = useCallback((lid: string) => {
    aiApi
      .history("trade", lid || undefined)
      .then((data) => setHistory((data as { history: HistoryItem[] }).history))
      .catch(() => {});
  }, []);

  useEffect(() => {
    leaguesApi
      .list({ mine: true })
      .then((data) => setLeagues(Array.isArray(data) ? (data as League[]) : []))
      .catch(() => {});
  }, []);

  const loadTrades = useCallback((lid: string) => {
    tradesApi
      .list(lid)
      .then((data) => {
        const all = Array.isArray(data) ? (data as TradeItem[]) : [];
        setTrades(all);
        setTradeId(all[0]?.id || "");
        // Names for the picker labels (one batched player lookup).
        const ids = [...new Set(all.flatMap((t) => [...(t.details?.offered_player_ids || []), ...(t.details?.requested_player_ids || [])]))];
        if (ids.length)
          playersApi
            .byIds(ids)
            .then((ps) => setPlayerNames(Object.fromEntries(ps.map((p) => [p.id, `${p.first_name ?? ""} ${p.last_name ?? ""}`.trim()]))))
            .catch(() => {});
      })
      .catch(() => {});
    teamsApi
      .getByLeague(lid)
      .then((data) => {
        const ts = Array.isArray(data) ? (data as { id: string; name: string }[]) : [];
        setTeamNames(Object.fromEntries(ts.map((t) => [t.id, t.name])));
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!leagueId) {
      setTrades([]);
      setTradeId("");
      return;
    }
    loadTrades(leagueId);
  }, [leagueId, loadTrades]);

  // Past trade evaluations -- scoped to whichever league is selected
  // (or this user's trade history across every league, before one is).
  useEffect(() => {
    loadHistory(leagueId);
  }, [leagueId, loadHistory]);

  const handleSubmit = async () => {
    if (!tradeId) return;
    setLoading(true);
    setError("");
    setAnalysis("");
    try {
      const res = (await aiApi.trade(tradeId)) as { analysis: string };
      setAnalysis(res.analysis);
      loadHistory(leagueId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to get analysis");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div className="space-y-4">
        <div>
          <label className="block text-xs text-surface-400 mb-1.5">League</label>
          <select
            value={leagueId}
            onChange={(e) => setLeagueId(e.target.value)}
            className="w-full px-3 py-2.5 bg-surface-800 border border-surface-700 rounded-xl text-sm text-white focus:outline-none focus:ring-1 focus:ring-gold-400"
          >
            <option value="">Select a league...</option>
            {leagues.map((l) => (
              <option key={l.id} value={l.id}>{leagueLabel(l, leagues)}</option>
            ))}
          </select>
        </div>
        {leagueId && (
          <div>
            <label className="block text-xs text-surface-400 mb-1.5">Trade</label>
            {trades.length === 0 ? (
              <p className="text-surface-500 text-sm">
                No trades in this league yet — propose one first from the league&apos;s Trades page.
              </p>
            ) : (
              <select
                value={tradeId}
                onChange={(e) => setTradeId(e.target.value)}
                className="w-full px-3 py-2.5 bg-surface-800 border border-surface-700 rounded-xl text-sm text-white focus:outline-none focus:ring-1 focus:ring-gold-400"
              >
                {trades.map((t) => (
                  <option key={t.id} value={t.id}>
                    {tradeOptionLabel(t, (id) => teamNames[id], (id) => playerNames[id])}
                  </option>
                ))}
              </select>
            )}
          </div>
        )}
      </div>

      {error && <p className="text-red-400 text-sm mt-3">{error}</p>}

      <button
        type="button"
        onClick={handleSubmit}
        disabled={!tradeId || loading}
        className="mt-5 inline-flex items-center gap-2 bg-gold-400 hover:bg-gold-300 text-surface-900 px-5 py-2.5 rounded-xl text-sm font-semibold transition-all disabled:opacity-50"
      >
        {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
        Evaluate Trade
      </button>

      {analysis && <AnalysisResult analysis={analysis} />}
      <HistoryList items={history} onSelect={setAnalysis} />
    </div>
  );
}

function CompareTeamsTab() {
  const [leagues, setLeagues] = useState<League[]>([]);
  const [teams, setTeams] = useState<RosterTeam[]>([]);
  const [leagueId, setLeagueId] = useState("");
  const [teamAId, setTeamAId] = useState("");
  const [teamBId, setTeamBId] = useState("");
  const [analysis, setAnalysis] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [history, setHistory] = useState<HistoryItem[]>([]);

  const loadHistory = useCallback((lid: string) => {
    aiApi
      .history("team_compare", lid || undefined)
      .then((data) => setHistory((data as { history: HistoryItem[] }).history))
      .catch(() => {});
  }, []);

  useEffect(() => {
    leaguesApi
      .list({ mine: true })
      .then((data) => setLeagues(Array.isArray(data) ? (data as League[]) : []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!leagueId) {
      setTeams([]);
      setTeamAId("");
      setTeamBId("");
      return;
    }
    teamsApi
      .getByLeague(leagueId)
      .then((data) => {
        const all = Array.isArray(data) ? (data as RosterTeam[]) : [];
        setTeams(all);
        // Team A = your team when you have one; Team B = a different team,
        // never the same one by default (QA 2026-10-19).
        const [a, b] = defaultComparePair(all, getCurrentUserId());
        setTeamAId(a);
        setTeamBId(b);
      })
      .catch(() => {});
  }, [leagueId]);

  useEffect(() => {
    loadHistory(leagueId);
  }, [leagueId, loadHistory]);

  const handleSubmit = async () => {
    if (!teamAId || !teamBId || teamAId === teamBId) return;
    setLoading(true);
    setError("");
    setAnalysis("");
    try {
      const res = (await aiApi.teamComparison(teamAId, teamBId)) as { analysis: string };
      setAnalysis(res.analysis);
      loadHistory(leagueId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to get comparison");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div className="space-y-4">
        <div>
          <label className="block text-xs text-surface-400 mb-1.5">League</label>
          <select
            value={leagueId}
            onChange={(e) => setLeagueId(e.target.value)}
            className="w-full px-3 py-2.5 bg-surface-800 border border-surface-700 rounded-xl text-sm text-white focus:outline-none focus:ring-1 focus:ring-gold-400"
          >
            <option value="">Select a league...</option>
            {leagues.map((l) => (
              <option key={l.id} value={l.id}>{leagueLabel(l, leagues)}</option>
            ))}
          </select>
        </div>
        {leagueId && teams.length >= 2 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-surface-400 mb-1.5">Team A</label>
              <select
                value={teamAId}
                onChange={(e) => setTeamAId(e.target.value)}
                className="w-full px-3 py-2.5 bg-surface-800 border border-surface-700 rounded-xl text-sm text-white focus:outline-none focus:ring-1 focus:ring-gold-400"
              >
                {teams.map((t) => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs text-surface-400 mb-1.5">Team B</label>
              <select
                value={teamBId}
                onChange={(e) => setTeamBId(e.target.value)}
                className="w-full px-3 py-2.5 bg-surface-800 border border-surface-700 rounded-xl text-sm text-white focus:outline-none focus:ring-1 focus:ring-gold-400"
              >
                {teams.map((t) => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
              </select>
            </div>
          </div>
        )}
        {leagueId && teams.length < 2 && (
          <p className="text-surface-500 text-sm">This league needs at least 2 teams to compare.</p>
        )}
      </div>

      {teamAId && teamBId && teamAId === teamBId && (
        <p className="text-red-400 text-sm mt-3">Pick two different teams.</p>
      )}
      {error && <p className="text-red-400 text-sm mt-3">{error}</p>}

      <button
        type="button"
        onClick={handleSubmit}
        disabled={!teamAId || !teamBId || teamAId === teamBId || loading}
        className="mt-5 inline-flex items-center gap-2 bg-gold-400 hover:bg-gold-300 text-surface-900 px-5 py-2.5 rounded-xl text-sm font-semibold transition-all disabled:opacity-50"
      >
        {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
        Compare Season Trends
      </button>

      {analysis && <AnalysisResult analysis={analysis} />}
      <HistoryList items={history} onSelect={setAnalysis} />
    </div>
  );
}

// Shared by ComparePlayersTab's two independent sides -- resolves a
// team's roster player IDs into real name/position data, same
// Promise.all-over-playersApi.get pattern the team detail page already
// uses for its own roster grid.
function usePlayersForTeam(teamId: string): RosterPlayerOption[] {
  const [players, setPlayers] = useState<RosterPlayerOption[]>([]);

  useEffect(() => {
    if (!teamId) {
      setPlayers([]);
      return;
    }
    let cancelled = false;
    teamsApi
      .get(teamId)
      .then(async (data) => {
        const roster = (data as RosterTeam).roster || [];
        const resolved = await Promise.all(
          roster.map((pid) =>
            playersApi
              .get(pid)
              .then((p) => p as RosterPlayerOption)
              .catch(() => null),
          ),
        );
        if (!cancelled) setPlayers(resolved.filter((p): p is RosterPlayerOption => p !== null));
      })
      .catch(() => {
        if (!cancelled) setPlayers([]);
      });
    return () => {
      cancelled = true;
    };
  }, [teamId]);

  return players;
}

function TeamPlayerPicker({
  label, teams, teamId, setTeamId, playerId, setPlayerId,
}: {
  label: string;
  teams: RosterTeam[];
  teamId: string;
  setTeamId: (id: string) => void;
  playerId: string;
  setPlayerId: (id: string) => void;
}) {
  const players = usePlayersForTeam(teamId);

  // Re-picks a default player whenever the team (or its resolved
  // roster) changes -- mirrors LineupTab's own "default to the first
  // option" behavior for its team dropdown.
  useEffect(() => {
    setPlayerId(players[0]?.id || "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [teamId, players.length]);

  return (
    <div className="space-y-3">
      <p className="text-xs font-semibold text-surface-400 uppercase tracking-wide">{label}</p>
      <div>
        <label className="block text-xs text-surface-400 mb-1.5">Team</label>
        <select
          value={teamId}
          onChange={(e) => setTeamId(e.target.value)}
          className="w-full px-3 py-2.5 bg-surface-800 border border-surface-700 rounded-xl text-sm text-white focus:outline-none focus:ring-1 focus:ring-gold-400"
        >
          <option value="">Select a team...</option>
          {teams.map((t) => (
            <option key={t.id} value={t.id}>{t.name}</option>
          ))}
        </select>
      </div>
      {teamId && (
        <div>
          <label className="block text-xs text-surface-400 mb-1.5">Player</label>
          {players.length === 0 ? (
            <p className="text-surface-500 text-sm">This team has no rostered players.</p>
          ) : (
            <select
              value={playerId}
              onChange={(e) => setPlayerId(e.target.value)}
              className="w-full px-3 py-2.5 bg-surface-800 border border-surface-700 rounded-xl text-sm text-white focus:outline-none focus:ring-1 focus:ring-gold-400"
            >
              {players.map((p) => (
                <option key={p.id} value={p.id}>{p.first_name} {p.last_name} ({p.position})</option>
              ))}
            </select>
          )}
        </div>
      )}
    </div>
  );
}

function ComparePlayersTab() {
  const [leagues, setLeagues] = useState<League[]>([]);
  const [teams, setTeams] = useState<RosterTeam[]>([]);
  const [leagueId, setLeagueId] = useState("");
  const [teamAId, setTeamAId] = useState("");
  const [playerAId, setPlayerAId] = useState("");
  const [teamBId, setTeamBId] = useState("");
  const [playerBId, setPlayerBId] = useState("");
  const [analysis, setAnalysis] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [history, setHistory] = useState<HistoryItem[]>([]);

  const loadHistory = useCallback((lid: string) => {
    aiApi
      .history("player_compare", lid || undefined)
      .then((data) => setHistory((data as { history: HistoryItem[] }).history))
      .catch(() => {});
  }, []);

  useEffect(() => {
    leaguesApi
      .list({ mine: true })
      .then((data) => setLeagues(Array.isArray(data) ? (data as League[]) : []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!leagueId) {
      setTeams([]);
      setTeamAId("");
      setTeamBId("");
      return;
    }
    teamsApi
      .getByLeague(leagueId)
      .then((data) => setTeams(Array.isArray(data) ? (data as RosterTeam[]) : []))
      .catch(() => {});
  }, [leagueId]);

  useEffect(() => {
    loadHistory(leagueId);
  }, [leagueId, loadHistory]);

  const handleSubmit = async () => {
    if (!playerAId || !playerBId || playerAId === playerBId) return;
    setLoading(true);
    setError("");
    setAnalysis("");
    try {
      const res = (await aiApi.playerComparison(playerAId, playerBId, leagueId)) as { analysis: string };
      setAnalysis(res.analysis);
      loadHistory(leagueId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to get comparison");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div className="space-y-4">
        <div>
          <label className="block text-xs text-surface-400 mb-1.5">League</label>
          <select
            value={leagueId}
            onChange={(e) => setLeagueId(e.target.value)}
            className="w-full px-3 py-2.5 bg-surface-800 border border-surface-700 rounded-xl text-sm text-white focus:outline-none focus:ring-1 focus:ring-gold-400"
          >
            <option value="">Select a league...</option>
            {leagues.map((l) => (
              <option key={l.id} value={l.id}>{leagueLabel(l, leagues)}</option>
            ))}
          </select>
        </div>

        {leagueId && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
            <TeamPlayerPicker
              label="Player A" teams={teams}
              teamId={teamAId} setTeamId={setTeamAId}
              playerId={playerAId} setPlayerId={setPlayerAId}
            />
            <TeamPlayerPicker
              label="Player B" teams={teams}
              teamId={teamBId} setTeamId={setTeamBId}
              playerId={playerBId} setPlayerId={setPlayerBId}
            />
          </div>
        )}
      </div>

      {playerAId && playerBId && playerAId === playerBId && (
        <p className="text-red-400 text-sm mt-3">Pick two different players.</p>
      )}
      {error && <p className="text-red-400 text-sm mt-3">{error}</p>}

      <button
        type="button"
        onClick={handleSubmit}
        disabled={!playerAId || !playerBId || playerAId === playerBId || loading}
        className="mt-5 inline-flex items-center gap-2 bg-gold-400 hover:bg-gold-300 text-surface-900 px-5 py-2.5 rounded-xl text-sm font-semibold transition-all disabled:opacity-50"
      >
        {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
        Get Start/Sit Verdict
      </button>

      {analysis && <AnalysisResult analysis={analysis} />}
      <HistoryList items={history} onSelect={setAnalysis} />
    </div>
  );
}

function BetTab() {
  const [prompt, setPrompt] = useState("");
  const [analysis, setAnalysis] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [history, setHistory] = useState<HistoryItem[]>([]);

  const loadHistory = useCallback(() => {
    aiApi
      .history("bet")
      .then((data) => setHistory((data as { history: HistoryItem[] }).history))
      .catch(() => {});
  }, []);

  // Bet analysis isn't scoped to a league, so history loads once,
  // up front, rather than re-keying off a league selector like the
  // other two tabs.
  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  const handleSubmit = async () => {
    if (!prompt.trim()) return;
    setLoading(true);
    setError("");
    setAnalysis("");
    try {
      const res = (await aiApi.bet(prompt)) as { analysis: string };
      setAnalysis(res.analysis);
      loadHistory();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to get analysis");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <label className="block text-xs text-surface-400 mb-1.5">Describe the matchup or line</label>
      <textarea
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        placeholder="e.g. Chiefs -3.5 at home against the Bills, should I take the spread or the over on total points?"
        rows={4}
        className="w-full px-3 py-2.5 bg-surface-800 border border-surface-700 rounded-xl text-sm text-white placeholder-surface-500 focus:outline-none focus:ring-1 focus:ring-gold-400 resize-none"
      />

      {error && <p className="text-red-400 text-sm mt-3">{error}</p>}

      <button
        type="button"
        onClick={handleSubmit}
        disabled={!prompt.trim() || loading}
        className="mt-5 inline-flex items-center gap-2 bg-gold-400 hover:bg-gold-300 text-surface-900 px-5 py-2.5 rounded-xl text-sm font-semibold transition-all disabled:opacity-50"
      >
        {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
        Get Analysis
      </button>

      {analysis && <AnalysisResult analysis={analysis} />}
      <HistoryList items={history} onSelect={setAnalysis} />
    </div>
  );
}
