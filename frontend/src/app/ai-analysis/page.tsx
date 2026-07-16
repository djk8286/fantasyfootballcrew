"use client";

import { useState, useEffect, useCallback } from "react";
import { Bot, Sparkles, ArrowLeftRight, TrendingUp, Send, Loader2 } from "lucide-react";
import { leaguesApi, teamsApi, tradesApi, aiApi, getCurrentUserId, isLoggedIn } from "@/lib/api-client";

interface League {
  id: string;
  name: string;
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

type Tab = "lineup" | "trade" | "bet";

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
            <div className="flex gap-1 bg-surface-800 rounded-xl p-1 border border-surface-700 mb-8">
              {[
                { id: "lineup" as Tab, label: "Lineup", icon: Sparkles },
                { id: "trade" as Tab, label: "Trade", icon: ArrowLeftRight },
                { id: "bet" as Tab, label: "Bet", icon: TrendingUp },
              ].map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => setActiveTab(id)}
                  className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold transition-all ${
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
      className={`mt-6 p-5 rounded-2xl border whitespace-pre-wrap text-sm leading-relaxed ${
        notConfigured
          ? "bg-surface-800/50 border-surface-700 text-surface-400"
          : "bg-purple-400/5 border-purple-400/20 text-surface-200"
      }`}
    >
      {analysis}
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

  const userId = getCurrentUserId();

  useEffect(() => {
    leaguesApi
      .list(true)
      .then((data) => setLeagues(Array.isArray(data) ? (data as League[]) : []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!leagueId) {
      setTeams([]);
      setTeamId("");
      return;
    }
    teamsApi
      .getByLeague(leagueId)
      .then((data) => {
        const all = Array.isArray(data) ? (data as Team[]) : [];
        const mine = all.filter((t) => t.owner_id === userId || t.co_owner_id === userId);
        setTeams(mine);
        setTeamId(mine[0]?.id || "");
      })
      .catch(() => {});
  }, [leagueId, userId]);

  const handleSubmit = async () => {
    if (!teamId) return;
    setLoading(true);
    setError("");
    setAnalysis("");
    try {
      const res = (await aiApi.lineup(teamId)) as { analysis: string };
      setAnalysis(res.analysis);
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
              <option key={l.id} value={l.id}>{l.name}</option>
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

  useEffect(() => {
    leaguesApi
      .list(true)
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

  const handleSubmit = async () => {
    if (!tradeId) return;
    setLoading(true);
    setError("");
    setAnalysis("");
    try {
      const res = (await aiApi.trade(tradeId)) as { analysis: string };
      setAnalysis(res.analysis);
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
              <option key={l.id} value={l.id}>{l.name}</option>
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
                    {t.status} trade ({(t.details?.offered_player_ids || []).length} for{" "}
                    {(t.details?.requested_player_ids || []).length})
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
    </div>
  );
}

function BetTab() {
  const [prompt, setPrompt] = useState("");
  const [analysis, setAnalysis] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async () => {
    if (!prompt.trim()) return;
    setLoading(true);
    setError("");
    setAnalysis("");
    try {
      const res = (await aiApi.bet(prompt)) as { analysis: string };
      setAnalysis(res.analysis);
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
    </div>
  );
}
