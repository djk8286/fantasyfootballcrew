"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  ChevronLeft,
  Crown,
  Scale,
  ArrowUpDown,
  Plus,
  X,
  CheckCircle2,
  XCircle,
  Shuffle,
  Save,
  Trash2,
  AlertTriangle,
  Shield,
  Ban,
  Users,
  Mail,
  Send,
  Clock,
  UserPlus,
  Bot,
  Loader2,
  HeartPulse,
  BarChart3,
  CalendarClock,
  MessageSquare,
  MessageCircle,
} from "lucide-react";
import { commissionerApi, leaguesApi, teamsApi, invitesApi, joinRequestsApi } from "@/lib/api-client";
import CoachStaffPanel from "@/components/CoachStaffPanel";

// ─── Types ───
interface League {
  id: string;
  name: string;
  commissioner_id: string;
  draft_status: string;
  draft_type: string;
  max_teams: number;
  description?: string;
}

interface Team {
  id: string;
  name: string;
  owner_id: string | null;
}

interface Adjustment {
  id: string;
  team_id: string;
  week: number;
  year: number;
  amount: number;
  reason: string;
  created_at: string;
}

interface TradeItem {
  id: string;
  team_id: string;
  type: string;
  status: string;
  details?: Record<string, unknown>;
  reviewed_by?: string;
  processed_at: string;
}

interface DraftOrderInfo {
  draft_status: string;
  current_order: { id: string; name: string }[];
  all_teams: { id: string; name: string }[];
  is_locked: boolean;
}

type Tab = "adjustments" | "trades" | "draft-order" | "coaches" | "invites" | "digest" | "health" | "insights" | "schedule-insights" | "messages" | "chat";

interface ChatMessageItem {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

const MESSAGE_TYPES = [
  { value: "trade_deadline", label: "Trade Deadline Reminder" },
  { value: "playoff_explanation", label: "Playoff Explanation" },
  { value: "inactivity_warning", label: "Inactivity Warning" },
  { value: "general", label: "General Announcement" },
] as const;

interface TeamSOS {
  team_id: string;
  team_name: string;
  sos_score: number | null;
  next_stretch_average?: number;
  flag?: "hard_stretch" | "easy_stretch" | null;
  summary: string;
}

interface ScheduleInsights {
  available: boolean;
  reason?: string;
  finale?: boolean;
  summary?: string;
  remaining_weeks?: number[];
  teams?: TeamSOS[];
}

interface CategoryVarianceObservation {
  category: string;
  coefficient_of_variation: number;
  average_points: number;
  summary: string;
}

interface CoachBonusObservation {
  bonus_type: string;
  average_bonus_points: number;
  share_of_average_score: number;
  summary: string;
}

interface PositionalBalanceObservation {
  highest_position: string;
  highest_average: number;
  lowest_position: string;
  lowest_average: number;
  summary: string;
}

interface ScoringInsights {
  available: boolean;
  weeks_available: number;
  weeks_required?: number;
  category_variance?: CategoryVarianceObservation[];
  coach_bonus_impact?: CoachBonusObservation[];
  positional_balance?: PositionalBalanceObservation[];
}

interface TeamHealth {
  team_id: string;
  team_name: string;
  is_co_owned: boolean;
  lineup_rate: number | null;
  transaction_count: number;
  at_risk: boolean;
  reason: string;
}

interface LeagueHealth {
  teams: TeamHealth[];
  parity_spread: number;
  at_risk_count: number;
  total_teams: number;
  is_best_ball: boolean;
}

interface Invite {
  id: string;
  invited_email: string;
  status: string;
  created_at: string;
  expires_at: string;
  accepted_at: string | null;
}

interface JoinRequest {
  id: string;
  requested_by_user_id: string;
  requester_username: string;
  message: string | null;
  status: string;
  created_at: string;
  decided_at: string | null;
}

// Every other page that needs "this season's year" computes it (standings,
// schedule, teams) -- this was the one spot still hardcoded, which would've
// silently tagged every point adjustment "2026" forever, starting with the
// first commissioner to use this panel after the calendar rolls over.
const CURRENT_YEAR = new Date().getFullYear();

export default function CommissionerPage() {
  const params = useParams();
  const router = useRouter();
  const leagueId = params.id as string;

  const [league, setLeague] = useState<League | null>(null);
  const [teams, setTeams] = useState<Team[]>([]);
  const [activeTab, setActiveTab] = useState<Tab>("adjustments");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // ── Load league data ──
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
  }, [leagueId]);

  const teamMap = Object.fromEntries(teams.map((t) => [t.id, t.name]));

  if (loading) {
    return (
      <div className="min-h-screen bg-surface-900 flex items-center justify-center">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 border-2 border-gold-400 border-t-transparent rounded-full animate-spin" />
          <span className="text-surface-400">Loading commissioner panel...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-surface-900">
      {/* Header */}
      <div className="sticky top-0 z-40 bg-surface-900/95 backdrop-blur-md border-b border-surface-700">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-3">
          <div className="flex items-center gap-3">
            <Link
              href={`/leagues/${leagueId}`}
              className="text-surface-400 hover:text-white transition-colors"
            >
              <ChevronLeft className="w-5 h-5" />
            </Link>
            <Crown className="w-5 h-5 text-gold-400" />
            <h1 className="text-lg font-bold text-white">Commissioner Settings</h1>
            {league && <span className="text-surface-400 text-sm">{league.name}</span>}
          </div>
        </div>
      </div>

      {error && (
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-4">
          <div className="bg-red-500/10 border border-red-500/20 rounded-xl px-4 py-3" role="alert">
            <p className="text-red-400 text-sm">{error}</p>
          </div>
        </div>
      )}

      {/* Tab bar */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-6">
        <div role="tablist" aria-label="Commissioner sections" className="flex gap-1 bg-surface-800 rounded-xl p-1 border border-surface-700">
          {[
            { id: "adjustments" as Tab, label: "Points Adjustments", icon: Scale },
            { id: "trades" as Tab, label: "Trades", icon: Ban },
            { id: "draft-order" as Tab, label: "Draft Order", icon: ArrowUpDown },
            { id: "coaches" as Tab, label: "Coaches", icon: Users },
            { id: "invites" as Tab, label: "Invites", icon: Mail },
            { id: "digest" as Tab, label: "AI Digest", icon: Bot },
            { id: "health" as Tab, label: "League Health", icon: HeartPulse },
            { id: "insights" as Tab, label: "Scoring Insights", icon: BarChart3 },
            { id: "schedule-insights" as Tab, label: "Schedule Insights", icon: CalendarClock },
            { id: "messages" as Tab, label: "Messages", icon: MessageSquare },
            { id: "chat" as Tab, label: "AI Chat", icon: MessageCircle },
          ].map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setActiveTab(id)}
              role="tab"
              aria-selected={activeTab === id}
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
      </div>

      {/* Tab content */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {activeTab === "adjustments" && (
          <PointsAdjustments leagueId={leagueId} teams={teams} teamMap={teamMap} />
        )}
        {activeTab === "trades" && (
          <TradesPanel leagueId={leagueId} teamMap={teamMap} />
        )}
        {activeTab === "draft-order" && league && (
          <DraftOrderPanel leagueId={leagueId} teams={teams} league={league} />
        )}
        {activeTab === "coaches" && (
          <CoachesPanel teams={teams} />
        )}
        {activeTab === "invites" && (
          <InvitesPanel leagueId={leagueId} />
        )}
        {activeTab === "digest" && (
          <DigestPanel leagueId={leagueId} />
        )}
        {activeTab === "health" && (
          <HealthPanel leagueId={leagueId} />
        )}
        {activeTab === "insights" && (
          <InsightsPanel leagueId={leagueId} />
        )}
        {activeTab === "schedule-insights" && (
          <ScheduleInsightsPanel leagueId={leagueId} />
        )}
        {activeTab === "messages" && (
          <MessagesPanel leagueId={leagueId} />
        )}
        {activeTab === "chat" && (
          <ChatPanel leagueId={leagueId} />
        )}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════
//  TAB 1: POINTS ADJUSTMENTS
// ═══════════════════════════════════════════

function PointsAdjustments({
  leagueId,
  teams,
  teamMap,
}: {
  leagueId: string;
  teams: Team[];
  teamMap: Record<string, string>;
}) {
  const [adjustments, setAdjustments] = useState<Adjustment[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);

  // Form state
  const [selTeam, setSelTeam] = useState("");
  const [week, setWeek] = useState(1);
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");

  const [filterWeek, setFilterWeek] = useState<number | undefined>();
  const [filterTeam, setFilterTeam] = useState("");

  const loadAdjustments = useCallback(async () => {
    try {
      const data = await commissionerApi.listAdjustments(leagueId, filterWeek, filterTeam || undefined);
      setAdjustments(data as Adjustment[]);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, [leagueId, filterWeek, filterTeam]);

  useEffect(() => {
    loadAdjustments();
  }, [loadAdjustments]);

  const handleAdd = async () => {
    if (!selTeam || !amount || !reason) return;
    const amt = parseFloat(amount);
    if (isNaN(amt)) return;
    try {
      await commissionerApi.addAdjustment(leagueId, {
        team_id: selTeam,
        week,
        year: CURRENT_YEAR,
        amount: amt,
        reason,
      });
      setShowForm(false);
      setSelTeam("");
      setAmount("");
      setReason("");
      await loadAdjustments();
    } catch {
      setError("Failed to add adjustment");
    }
  };

  const handleDelete = async (adjId: string) => {
    try {
      await commissionerApi.deleteAdjustment(leagueId, adjId);
      await loadAdjustments();
    } catch {
      setError("Failed to delete adjustment");
    }
  };

  const [error, setError] = useState("");

  const totalByTeam: Record<string, number> = {};
  adjustments.forEach((a) => {
    totalByTeam[a.team_id] = (totalByTeam[a.team_id] || 0) + a.amount;
  });

  return (
    <div>
      {error && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl px-4 py-2 mb-4" role="alert">
          <p className="text-red-400 text-sm">{error}</p>
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <div className="flex items-center gap-2">
          <span className="text-xs text-surface-500">Week:</span>
          <input
            type="number"
            min={1}
            max={22}
            value={filterWeek ?? ""}
            onChange={(e) => setFilterWeek(e.target.value ? parseInt(e.target.value) : undefined)}
            className="w-16 px-2 py-1.5 bg-surface-800 border border-surface-700 rounded-lg text-xs text-white text-center"
            placeholder="All"
          />
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-surface-500">Team:</span>
          <select
            value={filterTeam}
            onChange={(e) => setFilterTeam(e.target.value)}
            className="px-2 py-1.5 bg-surface-800 border border-surface-700 rounded-lg text-xs text-white"
          >
            <option value="">All Teams</option>
            {teams.map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className="ml-auto inline-flex items-center gap-1 bg-gold-400 hover:bg-gold-300 text-surface-900 px-3 py-1.5 rounded-lg text-xs font-bold transition-all"
        >
          <Plus className="w-3 h-3" />
          {showForm ? "Cancel" : "Add Adjustment"}
        </button>
      </div>

      {/* Add form */}
      {showForm && (
        <div className="bg-surface-800 border border-surface-700 rounded-xl p-4 mb-4">
          <h3 className="text-sm font-semibold text-white mb-3">New Points Adjustment</h3>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-3">
            <div>
              <label className="text-[10px] text-surface-500 uppercase tracking-wider">Team</label>
              <select
                value={selTeam}
                onChange={(e) => setSelTeam(e.target.value)}
                className="w-full mt-1 px-3 py-2 bg-surface-900 border border-surface-700 rounded-lg text-sm text-white"
              >
                <option value="">Select team...</option>
                {teams.map((t) => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-[10px] text-surface-500 uppercase tracking-wider">Week</label>
              <input
                type="number"
                min={1}
                max={22}
                value={week}
                onChange={(e) => setWeek(parseInt(e.target.value) || 1)}
                className="w-full mt-1 px-3 py-2 bg-surface-900 border border-surface-700 rounded-lg text-sm text-white"
              />
            </div>
            <div>
              <label className="text-[10px] text-surface-500 uppercase tracking-wider">Amount</label>
              <input
                type="number"
                step="0.1"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="e.g. 2.5 or -1"
                className="w-full mt-1 px-3 py-2 bg-surface-900 border border-surface-700 rounded-lg text-sm text-white placeholder-surface-500"
              />
              <p className="text-[9px] text-surface-600 mt-0.5">Positive=add, Negative=deduct</p>
            </div>
            <div>
              <label className="text-[10px] text-surface-500 uppercase tracking-wider">Reason</label>
              <input
                type="text"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Stat correction, error..."
                className="w-full mt-1 px-3 py-2 bg-surface-900 border border-surface-700 rounded-lg text-sm text-white placeholder-surface-500"
              />
            </div>
          </div>
          <button
            onClick={handleAdd}
            disabled={!selTeam || !amount || !reason}
            className="inline-flex items-center gap-1 bg-gold-400 hover:bg-gold-300 text-surface-900 px-4 py-2 rounded-lg text-sm font-bold transition-all disabled:opacity-50"
          >
            <Save className="w-4 h-4" />
            Apply Adjustment
          </button>
        </div>
      )}

      {/* Summary */}
      {adjustments.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-4">
          {Object.entries(totalByTeam)
            .filter(([, total]) => total !== 0)
            .map(([tid, total]) => (
              <div
                key={tid}
                className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-semibold ${
                  total > 0
                    ? "bg-green-500/10 text-green-400 border border-green-500/20"
                    : "bg-red-500/10 text-red-400 border border-red-500/20"
                }`}
              >
                {teamMap[tid] || tid}: {total > 0 ? "+" : ""}{total.toFixed(1)}
              </div>
            ))}
        </div>
      )}

      {/* Adjustments list */}
      {loading ? (
        <div className="text-center text-surface-500 py-8 text-sm">Loading adjustments...</div>
      ) : adjustments.length === 0 ? (
        <div className="text-center text-surface-500 py-12">
          <Scale className="w-10 h-10 mx-auto mb-3 opacity-30" />
          <p className="text-sm">No adjustments yet</p>
          <p className="text-xs text-surface-600 mt-1">Add a points adjustment for stat corrections or errors</p>
        </div>
      ) : (
        <div className="space-y-2">
          {adjustments.map((adj) => (
            <div
              key={adj.id}
              className="flex items-center justify-between bg-surface-800/50 border border-surface-700 rounded-xl px-4 py-3"
            >
              <div className="flex items-center gap-3 min-w-0">
                <div className={`w-8 h-8 rounded-lg flex items-center justify-center text-sm font-bold ${
                  adj.amount > 0
                    ? "bg-green-500/15 text-green-400"
                    : "bg-red-500/15 text-red-400"
                }`}>
                  {adj.amount > 0 ? "+" : ""}{adj.amount}
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-white">{teamMap[adj.team_id] || adj.team_id}</span>
                    <span className="text-[10px] text-surface-500 bg-surface-900 px-1.5 py-0.5 rounded">W{adj.week}</span>
                  </div>
                  <p className="text-xs text-surface-400 truncate">{adj.reason}</p>
                </div>
              </div>
              <button
                onClick={() => handleDelete(adj.id)}
                className="text-surface-500 hover:text-red-400 transition-colors shrink-0 ml-2"
                title="Remove adjustment"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════
//  TAB 2: TRADES
// ═══════════════════════════════════════════

function TradesPanel({
  leagueId,
  teamMap,
}: {
  leagueId: string;
  teamMap: Record<string, string>;
}) {
  const [trades, setTrades] = useState<TradeItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState("pending");
  const [processing, setProcessing] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState<string | null>(null);

  const loadTrades = useCallback(async () => {
    try {
      const data = await commissionerApi.listTrades(leagueId, statusFilter);
      setTrades(data as TradeItem[]);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, [leagueId, statusFilter]);

  useEffect(() => {
    loadTrades();
  }, [loadTrades]);

  const handleReview = async (tradeId: string, action: "approve" | "deny") => {
    setProcessing(tradeId);
    setError("");
    try {
      await commissionerApi.reviewTrade(leagueId, tradeId, action);
      await loadTrades();
    } catch (err) {
      // A 409 here means another trade touching one of the same two teams
      // was approved a moment earlier -- expected under concurrent review,
      // not a real failure. Surface the backend's actual message (it says
      // "please retry") instead of a generic string with no next step.
      setError(err instanceof Error ? err.message : "Failed to review trade");
    }
    setProcessing(null);
  };

  const [error, setError] = useState("");

  const handleAnalyze = async (tradeId: string) => {
    setAnalyzing(tradeId);
    setError("");
    try {
      await commissionerApi.analyzeTradeForReview(leagueId, tradeId);
      await loadTrades();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to analyze trade");
    }
    setAnalyzing(null);
  };

  const recommendationColors: Record<string, string> = {
    APPROVE: "bg-green-500/10 text-green-400 border-green-500/20",
    "REVIEW CLOSELY": "bg-yellow-500/10 text-yellow-400 border-yellow-500/20",
    VETO: "bg-red-500/10 text-red-400 border-red-500/20",
  };

  const statusColors: Record<string, string> = {
    pending: "bg-yellow-500/10 text-yellow-400 border-yellow-500/20",
    approved: "bg-green-500/10 text-green-400 border-green-500/20",
    denied: "bg-red-500/10 text-red-400 border-red-500/20",
  };

  return (
    <div>
      {error && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl px-4 py-2 mb-4" role="alert">
          <p className="text-red-400 text-sm">{error}</p>
        </div>
      )}

      {/* Filter */}
      <div className="flex items-center gap-2 mb-4">
        {["pending", "approved", "denied"].map((s) => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition-all ${
              statusFilter === s
                ? (statusColors[s] || "bg-surface-700 text-white border-surface-600")
                : "bg-surface-800 text-surface-400 border-surface-700 hover:text-white"
            }`}
          >
            {s.charAt(0).toUpperCase() + s.slice(1)}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="text-center text-surface-500 py-8 text-sm">Loading trades...</div>
      ) : trades.length === 0 ? (
        <div className="text-center text-surface-500 py-12">
          <Ban className="w-10 h-10 mx-auto mb-3 opacity-30" />
          <p className="text-sm">No {statusFilter} trades</p>
          <p className="text-xs text-surface-600 mt-1">Trades will appear here when teams propose them</p>
        </div>
      ) : (
        <div className="space-y-2">
          {trades.map((trade) => (
            <div
              key={trade.id}
              className="bg-surface-800/50 border border-surface-700 rounded-xl px-4 py-3"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <Shield className="w-4 h-4 text-surface-500" />
                  <div>
                    <span className="text-sm font-semibold text-white">
                      {teamMap[trade.team_id] || trade.team_id}
                    </span>
                    <span className={`ml-2 inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold border ${statusColors[trade.status] || ""}`}>
                      {trade.status}
                    </span>
                  </div>
                </div>
                {trade.status === "pending" && (
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => handleAnalyze(trade.id)}
                      disabled={analyzing === trade.id}
                      className="inline-flex items-center gap-1 bg-purple-500/20 hover:bg-purple-500/30 text-purple-300 border border-purple-500/30 px-3 py-1.5 rounded-lg text-xs font-bold transition-all disabled:opacity-50"
                    >
                      {analyzing === trade.id ? (
                        <div className="w-3 h-3 border border-purple-300 border-t-transparent rounded-full animate-spin" />
                      ) : (
                        <Bot className="w-3 h-3" />
                      )}
                      {trade.details?.ai_review ? "Re-analyze" : "Analyze with AI"}
                    </button>
                    <button
                      onClick={() => handleReview(trade.id, "approve")}
                      disabled={processing === trade.id}
                      className="inline-flex items-center gap-1 bg-green-500 hover:bg-green-400 text-white px-3 py-1.5 rounded-lg text-xs font-bold transition-all disabled:opacity-50"
                    >
                      {processing === trade.id ? (
                        <div className="w-3 h-3 border border-white border-t-transparent rounded-full animate-spin" />
                      ) : (
                        <CheckCircle2 className="w-3 h-3" />
                      )}
                      Approve
                    </button>
                    <button
                      onClick={() => handleReview(trade.id, "deny")}
                      disabled={processing === trade.id}
                      className="inline-flex items-center gap-1 bg-red-500 hover:bg-red-400 text-white px-3 py-1.5 rounded-lg text-xs font-bold transition-all disabled:opacity-50"
                    >
                      <XCircle className="w-3 h-3" />
                      Deny
                    </button>
                  </div>
                )}
                {trade.reviewed_by && (
                  <span className="text-[10px] text-surface-500">by {trade.reviewed_by}</span>
                )}
              </div>
              {trade.details && (
                <p className="text-xs text-surface-500 mt-2">{JSON.stringify(trade.details)}</p>
              )}
              {(() => {
                const aiReview = trade.details?.ai_review as
                  | { content: string; recommendation: string | null; analyzed_at: string }
                  | undefined;
                if (!aiReview) return null;
                return (
                  <div className="mt-3 pt-3 border-t border-surface-700">
                    <div className="flex items-center gap-2 mb-2">
                      <Bot className="w-3.5 h-3.5 text-purple-400" />
                      <span className="text-xs font-semibold text-purple-300">AI Trade Review</span>
                      {aiReview.recommendation && (
                        <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold border ${
                          recommendationColors[aiReview.recommendation] || "bg-surface-700 text-surface-400 border-surface-600"
                        }`}>
                          {aiReview.recommendation}
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-surface-300 whitespace-pre-wrap leading-relaxed bg-surface-900/50 rounded-lg p-3">
                      {aiReview.content}
                    </div>
                  </div>
                );
              })()}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════
//  TAB 3: DRAFT ORDER
// ═══════════════════════════════════════════

function DraftOrderPanel({
  leagueId,
  teams,
  league,
}: {
  leagueId: string;
  teams: Team[];
  league: League;
}) {
  const [orderData, setOrderData] = useState<DraftOrderInfo | null>(null);
  const [order, setOrder] = useState<{ id: string; name: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  useEffect(() => {
    commissionerApi
      .getDraftOrder(leagueId)
      .then((data) => {
        const info = data as DraftOrderInfo;
        setOrderData(info);
        setOrder(info.current_order);
      })
      .catch(() => setError("Failed to load draft order"))
      .finally(() => setLoading(false));
  }, [leagueId]);

  const isLocked = orderData?.is_locked ?? league.draft_status !== "not_started";

  const moveTeam = (index: number, direction: -1 | 1) => {
    const newOrder = [...order];
    const swapIdx = index + direction;
    if (swapIdx < 0 || swapIdx >= newOrder.length) return;
    [newOrder[index], newOrder[swapIdx]] = [newOrder[swapIdx], newOrder[index]];
    setOrder(newOrder);
  };

  const handleRandomize = async () => {
    try {
      const data = await commissionerApi.randomizeDraftOrder(leagueId);
      const result = data as { draft_order: string[] };
      const teamMap = Object.fromEntries(teams.map((t) => [t.id, t.name]));
      setOrder(result.draft_order.map((id) => ({ id, name: teamMap[id] || "Unknown" })));
      setSuccess("Draft order randomized!");
      setTimeout(() => setSuccess(""), 3000);
    } catch {
      setError("Failed to randomize");
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      await commissionerApi.setDraftOrder(leagueId, order.map((t) => t.id));
      setSuccess("Draft order saved!");
      setTimeout(() => setSuccess(""), 3000);
    } catch {
      setError("Failed to save draft order");
    }
    setSaving(false);
  };

  if (loading) {
    return <div className="text-center text-surface-500 py-8 text-sm">Loading draft order...</div>;
  }

  return (
    <div>
      {error && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl px-4 py-2 mb-4" role="alert">
          <p className="text-red-400 text-sm">{error}</p>
        </div>
      )}
      {success && (
        <div className="bg-green-500/10 border border-green-500/20 rounded-xl px-4 py-2 mb-4">
          <p className="text-green-400 text-sm">{success}</p>
        </div>
      )}

      {isLocked && (
        <div className="bg-yellow-500/10 border border-yellow-500/20 rounded-xl px-4 py-3 mb-4 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-yellow-400 shrink-0" />
          <p className="text-yellow-300 text-sm">
            Draft order is locked because the draft has already started. Start a new league or reset the draft to change it.
          </p>
        </div>
      )}

      <div className="bg-surface-800 border border-surface-700 rounded-xl p-4">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-white">
            Pick Order
            <span className="text-surface-500 text-xs ml-2 font-normal">
              ({teams.length} teams, {league.draft_type})
            </span>
          </h3>
          {!isLocked && (
            <button
              onClick={handleRandomize}
              className="inline-flex items-center gap-1 bg-surface-700 hover:bg-surface-600 text-surface-300 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all"
            >
              <Shuffle className="w-3 h-3" />
              Randomize
            </button>
          )}
        </div>

        <div className="space-y-1.5">
          {order.map((team, idx) => (
            <div
              key={team.id}
              className="flex items-center gap-3 bg-surface-900 border border-surface-700 rounded-lg px-3 py-2.5"
            >
              <span className="w-6 text-center text-xs font-bold text-gold-400">
                #{idx + 1}
              </span>
              <div className="w-7 h-7 rounded-full bg-surface-700 flex items-center justify-center text-[10px] font-bold text-surface-300">
                {team.name.charAt(0)}
              </div>
              <span className="flex-1 text-sm font-medium text-white">{team.name}</span>
              {!isLocked && (
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => moveTeam(idx, -1)}
                    disabled={idx === 0}
                    title="Move up in draft order"
                    aria-label="Move up in draft order"
                    className="p-1 text-surface-500 hover:text-white disabled:opacity-20 disabled:cursor-not-allowed transition-colors"
                  >
                    <ChevronLeft className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => moveTeam(idx, 1)}
                    disabled={idx === order.length - 1}
                    title="Move down in draft order"
                    aria-label="Move down in draft order"
                    className="p-1 text-surface-500 hover:text-white disabled:opacity-20 disabled:cursor-not-allowed transition-colors"
                  >
                    <ChevronLeft className="w-3.5 h-3.5 rotate-180" />
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>

        {!isLocked && (
          <div className="mt-4 flex justify-end">
            <button
              onClick={handleSave}
              disabled={saving}
              className="inline-flex items-center gap-1.5 bg-gold-400 hover:bg-gold-300 text-surface-900 px-5 py-2.5 rounded-lg text-sm font-bold transition-all disabled:opacity-50"
            >
              {saving ? (
                <div className="w-4 h-4 border-2 border-surface-900 border-t-transparent rounded-full animate-spin" />
              ) : (
                <Save className="w-4 h-4" />
              )}
              Save Order
            </button>
          </div>
        )}
      </div>

      {/* Current draft status */}
      <div className="mt-4 bg-surface-800/50 border border-surface-700 rounded-xl px-4 py-3">
        <div className="flex items-center justify-between text-xs">
          <span className="text-surface-400">
            Draft Status: <span className="text-white font-semibold">{orderData?.draft_status || league.draft_status}</span>
          </span>
          <span className="text-surface-500">
            {teams.length} teams · {league.draft_type}
          </span>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════
//  TAB 4: COACHES & COORDINATORS
// ═══════════════════════════════════════════
// Form/list JSX now lives in the shared CoachStaffPanel component (Phase
// 2 Step 4, "Front-Office finish-out") so a team's own owner/co-owner can
// manage their staff from their team page too, not just here. This tab
// keeps its own team-selector (oversight needs to pick which team) and
// delegates everything else, with canManage=true preserving the
// commissioner's existing override capability unchanged.

function CoachesPanel({ teams }: { teams: Team[] }) {
  const [selTeam, setSelTeam] = useState(teams[0]?.id || "");

  return (
    <div>
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <div className="flex items-center gap-2">
          <span className="text-xs text-surface-500">Team:</span>
          <select
            value={selTeam}
            onChange={(e) => setSelTeam(e.target.value)}
            className="px-2 py-1.5 bg-surface-800 border border-surface-700 rounded-lg text-xs text-white"
          >
            {teams.map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
        </div>
      </div>
      {selTeam && <CoachStaffPanel teamId={selTeam} canManage={true} />}
    </div>
  );
}

// ═══════════════════════════════════════════
//  TAB 5: INVITES
// ═══════════════════════════════════════════

const INVITE_STATUS_COLORS: Record<string, string> = {
  pending: "bg-yellow-500/10 text-yellow-400 border-yellow-500/20",
  accepted: "bg-green-500/10 text-green-400 border-green-500/20",
  revoked: "bg-surface-700 text-surface-400 border-surface-600",
  expired: "bg-red-500/10 text-red-400 border-red-500/20",
};

function InvitesPanel({ leagueId }: { leagueId: string }) {
  const [invites, setInvites] = useState<Invite[]>([]);
  const [loading, setLoading] = useState(true);
  const [emailsInput, setEmailsInput] = useState("");
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const loadInvites = useCallback(async () => {
    try {
      const data = await invitesApi.list(leagueId);
      setInvites(data as Invite[]);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, [leagueId]);

  useEffect(() => {
    loadInvites();
  }, [loadInvites]);

  const handleSend = async () => {
    const emails = emailsInput
      .split(/[\n,]/)
      .map((e) => e.trim())
      .filter(Boolean);
    if (emails.length === 0) return;
    setSending(true);
    setError("");
    setSuccess("");
    try {
      await invitesApi.send(leagueId, emails, message || undefined);
      setSuccess(`Sent ${emails.length} invite${emails.length === 1 ? "" : "s"}!`);
      setEmailsInput("");
      setMessage("");
      await loadInvites();
      setTimeout(() => setSuccess(""), 4000);
    } catch (err) {
      // Rate-limited (10/hour) or a bad address in the batch -- surface the
      // backend's actual message rather than a generic string.
      setError(err instanceof Error ? err.message : "Failed to send invites");
    }
    setSending(false);
  };

  const handleRevoke = async (inviteId: string) => {
    setError("");
    try {
      await invitesApi.revoke(leagueId, inviteId);
      await loadInvites();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to revoke invite");
    }
  };

  return (
    <div>
      {error && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl px-4 py-2 mb-4" role="alert">
          <p className="text-red-400 text-sm">{error}</p>
        </div>
      )}
      {success && (
        <div className="bg-green-500/10 border border-green-500/20 rounded-xl px-4 py-2 mb-4">
          <p className="text-green-400 text-sm">{success}</p>
        </div>
      )}

      <div className="bg-surface-800 border border-surface-700 rounded-xl p-4 mb-4">
        <h3 className="text-sm font-semibold text-white mb-3">Invite Managers by Email</h3>
        <div className="grid gap-3">
          <div>
            <label className="text-[10px] text-surface-500 uppercase tracking-wider">
              Email addresses
            </label>
            <textarea
              value={emailsInput}
              onChange={(e) => setEmailsInput(e.target.value)}
              placeholder="One per line, or comma-separated&#10;e.g. alex@example.com, jamie@example.com"
              rows={3}
              className="w-full mt-1 px-3 py-2 bg-surface-900 border border-surface-700 rounded-lg text-sm text-white placeholder-surface-500 resize-none"
            />
            <p className="text-[9px] text-surface-600 mt-0.5">Up to 20 at a time. Each gets a 14-day invite link.</p>
          </div>
          <div>
            <label className="text-[10px] text-surface-500 uppercase tracking-wider">
              Personal message (optional)
            </label>
            <input
              type="text"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="We've got a spot for you this season..."
              className="w-full mt-1 px-3 py-2 bg-surface-900 border border-surface-700 rounded-lg text-sm text-white placeholder-surface-500"
            />
          </div>
        </div>
        <button
          onClick={handleSend}
          disabled={sending || !emailsInput.trim()}
          className="mt-3 inline-flex items-center gap-1.5 bg-gold-400 hover:bg-gold-300 text-surface-900 px-4 py-2 rounded-lg text-sm font-bold transition-all disabled:opacity-50"
        >
          {sending ? (
            <div className="w-4 h-4 border-2 border-surface-900 border-t-transparent rounded-full animate-spin" />
          ) : (
            <Send className="w-4 h-4" />
          )}
          Send Invites
        </button>
      </div>

      {loading ? (
        <div className="text-center text-surface-500 py-8 text-sm">Loading invites...</div>
      ) : invites.length === 0 ? (
        <div className="text-center text-surface-500 py-12">
          <Mail className="w-10 h-10 mx-auto mb-3 opacity-30" />
          <p className="text-sm">No invites sent yet</p>
          <p className="text-xs text-surface-600 mt-1">Invite friends to fill open spots in this league</p>
        </div>
      ) : (
        <div className="space-y-2">
          {invites.map((inv) => (
            <div
              key={inv.id}
              className="flex items-center justify-between bg-surface-800/50 border border-surface-700 rounded-xl px-4 py-3"
            >
              <div className="flex items-center gap-3 min-w-0">
                <div className="w-8 h-8 rounded-lg bg-surface-700 flex items-center justify-center shrink-0">
                  <Mail className="w-4 h-4 text-surface-400" />
                </div>
                <div className="min-w-0">
                  <span className="text-sm font-semibold text-white truncate block">{inv.invited_email}</span>
                  <span className="text-[10px] text-surface-500 flex items-center gap-1">
                    <Clock className="w-3 h-3" />
                    {inv.status === "pending" ? `Expires ${new Date(inv.expires_at).toLocaleDateString()}` : new Date(inv.created_at).toLocaleDateString()}
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold border ${INVITE_STATUS_COLORS[inv.status] || ""}`}>
                  {inv.status}
                </span>
                {inv.status === "pending" && (
                  <button
                    onClick={() => handleRevoke(inv.id)}
                    className="text-surface-500 hover:text-red-400 transition-colors"
                    title="Revoke invite"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      <JoinRequestsSection leagueId={leagueId} />
    </div>
  );
}

// ─── Join requests sub-section ───────────────────────────────────────
// The "or approval" half of Invite-only: someone found the league via
// discovery and asked to join, rather than the commissioner reaching out
// first (the invites above). Same tab -- both are "who's trying to get
// into this league" concerns.

function JoinRequestsSection({ leagueId }: { leagueId: string }) {
  const [requests, setRequests] = useState<JoinRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [deciding, setDeciding] = useState<string | null>(null);

  const loadRequests = useCallback(async () => {
    try {
      const data = await joinRequestsApi.list(leagueId);
      setRequests(data as JoinRequest[]);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, [leagueId]);

  useEffect(() => {
    loadRequests();
  }, [loadRequests]);

  const handleDecide = async (requestId: string, action: "approve" | "deny") => {
    setDeciding(requestId);
    setError("");
    try {
      await joinRequestsApi.decide(leagueId, requestId, action);
      await loadRequests();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to decide request");
    }
    setDeciding(null);
  };

  const pending = requests.filter((r) => r.status === "pending");
  const decided = requests.filter((r) => r.status !== "pending");

  if (loading) return null;
  // Nothing to show for OPEN/PRIVATE leagues or an invite-only league
  // with no requests yet -- no point taking up space with an empty
  // section every time.
  if (requests.length === 0) return null;

  return (
    <div className="mt-6">
      <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
        <UserPlus className="w-4 h-4 text-gold-400" />
        Join Requests
        {pending.length > 0 && (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold bg-yellow-500/10 text-yellow-400 border border-yellow-500/20">
            {pending.length} pending
          </span>
        )}
      </h3>

      {error && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl px-4 py-2 mb-4" role="alert">
          <p className="text-red-400 text-sm">{error}</p>
        </div>
      )}

      <div className="space-y-2">
        {[...pending, ...decided].map((req) => (
          <div
            key={req.id}
            className="flex items-center justify-between bg-surface-800/50 border border-surface-700 rounded-xl px-4 py-3"
          >
            <div className="flex items-center gap-3 min-w-0">
              <div className="w-8 h-8 rounded-lg bg-surface-700 flex items-center justify-center shrink-0 text-[10px] font-bold text-surface-300">
                {req.requester_username.charAt(0).toUpperCase()}
              </div>
              <div className="min-w-0">
                <span className="text-sm font-semibold text-white">{req.requester_username}</span>
                {req.message && (
                  <p className="text-xs text-surface-400 truncate">&ldquo;{req.message}&rdquo;</p>
                )}
              </div>
            </div>
            {req.status === "pending" ? (
              <div className="flex items-center gap-2 shrink-0">
                <button
                  onClick={() => handleDecide(req.id, "approve")}
                  disabled={deciding === req.id}
                  className="inline-flex items-center gap-1 bg-green-500 hover:bg-green-400 text-white px-3 py-1.5 rounded-lg text-xs font-bold transition-all disabled:opacity-50"
                >
                  {deciding === req.id ? (
                    <div className="w-3 h-3 border border-white border-t-transparent rounded-full animate-spin" />
                  ) : (
                    <CheckCircle2 className="w-3 h-3" />
                  )}
                  Approve
                </button>
                <button
                  onClick={() => handleDecide(req.id, "deny")}
                  disabled={deciding === req.id}
                  className="inline-flex items-center gap-1 bg-red-500 hover:bg-red-400 text-white px-3 py-1.5 rounded-lg text-xs font-bold transition-all disabled:opacity-50"
                >
                  <XCircle className="w-3 h-3" />
                  Deny
                </button>
              </div>
            ) : (
              <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold border shrink-0 ${
                req.status === "approved"
                  ? "bg-green-500/10 text-green-400 border-green-500/20"
                  : "bg-surface-700 text-surface-400 border-surface-600"
              }`}>
                {req.status}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════
//  TAB 6: AI COMMISSIONER DIGEST (Phase 8)
// ═══════════════════════════════════════════
// Commissioner-triggered on demand only -- no auto-generation. Mirrors
// ai-analysis/page.tsx's AnalysisResult rendering convention exactly
// (whitespace-pre-wrap plain text, no markdown parser anywhere in this
// codebase) and its "not configured" fallback-string detection.

const DIGEST_TONES = [
  { value: "professional", label: "Professional" },
  { value: "casual", label: "Casual" },
  { value: "hype", label: "Hype" },
  { value: "sarcastic", label: "Sarcastic" },
  { value: "dry", label: "Dry" },
] as const;

const DIGEST_LENGTHS = [
  { value: "full", label: "Full" },
  { value: "short", label: "Short" },
] as const;

function DigestPanel({ leagueId }: { leagueId: string }) {
  const [week, setWeek] = useState(1);
  const [tone, setTone] = useState("professional");
  const [length, setLength] = useState("full");
  const [digest, setDigest] = useState<{ content: string; created_at: string; tone?: string; length?: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    commissionerApi
      .getDigest(leagueId, week, CURRENT_YEAR)
      .then((data) => setDigest(data as { content: string; created_at: string; tone?: string; length?: string }))
      .catch(() => setDigest(null)) // 404 just means "nothing generated yet" -- not an error banner
      .finally(() => setLoading(false));
  }, [leagueId, week]);

  useEffect(() => {
    load();
  }, [load]);

  const handleGenerate = async () => {
    setGenerating(true);
    setError("");
    try {
      const result = await commissionerApi.generateDigest(leagueId, week, CURRENT_YEAR, tone, length);
      setDigest(result as { content: string; created_at: string; tone?: string; length?: string });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to generate digest");
    }
    setGenerating(false);
  };

  const notConfigured = digest?.content.startsWith("AI Analysis: LLM API not configured");

  return (
    <div>
      <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <span className="text-xs text-surface-500">Week:</span>
            <select
              value={week}
              onChange={(e) => setWeek(parseInt(e.target.value, 10))}
              className="px-2 py-1.5 bg-surface-800 border border-surface-700 rounded-lg text-xs text-white"
            >
              {Array.from({ length: 18 }, (_, i) => i + 1).map((w) => (
                <option key={w} value={w}>Week {w}</option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-surface-500">Tone:</span>
            <select
              value={tone}
              onChange={(e) => setTone(e.target.value)}
              className="px-2 py-1.5 bg-surface-800 border border-surface-700 rounded-lg text-xs text-white"
            >
              {DIGEST_TONES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-surface-500">Length:</span>
            <select
              value={length}
              onChange={(e) => setLength(e.target.value)}
              className="px-2 py-1.5 bg-surface-800 border border-surface-700 rounded-lg text-xs text-white"
            >
              {DIGEST_LENGTHS.map((l) => (
                <option key={l.value} value={l.value}>{l.label}</option>
              ))}
            </select>
          </div>
        </div>
        <button
          onClick={handleGenerate}
          disabled={generating}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-bold bg-gold-400 hover:bg-gold-300 text-surface-900 disabled:opacity-50 transition-all"
        >
          {generating ? (
            <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Generating...</>
          ) : digest ? (
            <><Bot className="w-3.5 h-3.5" /> Regenerate Digest</>
          ) : (
            <><Bot className="w-3.5 h-3.5" /> Generate This Week's Digest</>
          )}
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400 text-sm" role="alert">
          {error}
        </div>
      )}

      {loading ? (
        <div className="p-6 text-center text-surface-500 text-sm">Loading...</div>
      ) : digest ? (
        <div>
          {(digest.tone || digest.length) && (
            <p className="text-[10px] text-surface-500 mb-2">
              Generated with {DIGEST_TONES.find((t) => t.value === digest.tone)?.label || digest.tone} tone,{" "}
              {DIGEST_LENGTHS.find((l) => l.value === digest.length)?.label || digest.length} length.
            </p>
          )}
          <div
            className={`p-5 rounded-2xl border whitespace-pre-wrap text-sm leading-relaxed ${
              notConfigured
                ? "bg-surface-800/50 border-surface-700 text-surface-400"
                : "bg-purple-400/5 border-purple-400/20 text-surface-200"
            }`}
          >
            {digest.content}
          </div>
        </div>
      ) : (
        <div className="p-6 text-center text-surface-500 text-sm bg-surface-800/50 border border-surface-700 rounded-2xl">
          No digest generated for Week {week} yet -- click &quot;Generate This Week&apos;s Digest&quot; above.
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════
//  TAB 7: LEAGUE HEALTH DASHBOARD (AI Co-Commissioner v1)
// ═══════════════════════════════════════════
// Computed data, not AI-generated text -- no LLM call anywhere in this
// panel, just real arithmetic over existing rows (see
// league_health_service.py). Recomputed fresh on every load, so a plain
// "Refresh" button is enough -- no generate/regenerate distinction like
// the digest above.

function HealthPanel({ leagueId }: { leagueId: string }) {
  const [health, setHealth] = useState<LeagueHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    commissionerApi
      .getLeagueHealth(leagueId)
      .then((data) => setHealth(data as LeagueHealth))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Failed to load league health"))
      .finally(() => setLoading(false));
  }, [leagueId]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    return <div className="p-6 text-center text-surface-500 text-sm">Loading...</div>;
  }

  if (error) {
    return (
      <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400 text-sm" role="alert">
        {error}
      </div>
    );
  }

  if (!health || health.total_teams === 0) {
    return (
      <div className="p-6 text-center text-surface-500 text-sm bg-surface-800/50 border border-surface-700 rounded-2xl">
        No teams yet -- health metrics will appear once the league has teams and at least one scored week.
      </div>
    );
  }

  const hasCoOwnedTeam = health.teams.some((t) => t.is_co_owned);

  return (
    <div>
      <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
        <div className="flex items-center gap-4 flex-wrap">
          <div className="px-4 py-2 bg-surface-800 border border-surface-700 rounded-xl">
            <p className="text-[10px] text-surface-500 uppercase tracking-wider">At-Risk Teams</p>
            <p className={`text-lg font-bold ${health.at_risk_count > 0 ? "text-red-400" : "text-green-400"}`}>
              {health.at_risk_count} / {health.total_teams}
            </p>
          </div>
          <div className="px-4 py-2 bg-surface-800 border border-surface-700 rounded-xl">
            <p className="text-[10px] text-surface-500 uppercase tracking-wider">Parity Spread</p>
            <p className="text-lg font-bold text-white">{health.parity_spread}</p>
          </div>
        </div>
        <button
          onClick={load}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-bold bg-surface-800 hover:bg-surface-700 text-surface-300 border border-surface-700 transition-all"
        >
          <HeartPulse className="w-3.5 h-3.5" /> Refresh
        </button>
      </div>

      {health.is_best_ball && (
        <p className="text-xs text-surface-500 mb-3">
          This is a Best-Ball league -- lineups are set automatically, so lineup-setting rate isn&apos;t a meaningful engagement signal here.
        </p>
      )}
      {hasCoOwnedTeam && (
        <p className="text-xs text-surface-500 mb-3">
          Co-owned team activity shown below is combined for both managers -- this can flag a team&apos;s overall engagement, but not which specific co-owner is inactive.
        </p>
      )}

      <div className="overflow-x-auto rounded-2xl border border-surface-700">
        <table className="w-full text-sm">
          <thead className="bg-surface-800 text-surface-400 text-xs uppercase tracking-wider">
            <tr>
              <th className="text-left px-4 py-3">Team</th>
              <th className="text-left px-4 py-3">Lineup Rate</th>
              <th className="text-left px-4 py-3">Transactions</th>
              <th className="text-left px-4 py-3">Status</th>
            </tr>
          </thead>
          <tbody>
            {health.teams.map((t) => (
              <tr key={t.team_id} className="border-t border-surface-800">
                <td className="px-4 py-3 text-white font-medium">
                  {t.team_name}
                  {t.is_co_owned && (
                    <span className="ml-2 px-1.5 py-0.5 rounded bg-surface-700 text-[10px] text-surface-300 align-middle">
                      Co-Owned
                    </span>
                  )}
                </td>
                <td className="px-4 py-3 text-surface-300">
                  {t.lineup_rate === null ? "N/A (Best-Ball)" : `${Math.round(t.lineup_rate * 100)}%`}
                </td>
                <td className="px-4 py-3 text-surface-300">{t.transaction_count}</td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-1.5">
                    {t.at_risk ? (
                      <AlertTriangle className="w-3.5 h-3.5 text-red-400 shrink-0" />
                    ) : (
                      <CheckCircle2 className="w-3.5 h-3.5 text-green-400 shrink-0" />
                    )}
                    <span className="text-xs text-surface-400">{t.reason}</span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════
//  TAB 8: SCORING & RULE INSIGHTS (AI Co-Commissioner v1, Phase 2)
// ═══════════════════════════════════════════
// Computed data, not AI-generated text -- same "zero LLM calls, real
// arithmetic, plain-English explanations" pattern as HealthPanel
// above. Presented as suggestions with supporting data, never phrased
// as an instruction -- the commissioner decides what (if anything) is
// worth acting on.

function InsightsPanel({ leagueId }: { leagueId: string }) {
  const [insights, setInsights] = useState<ScoringInsights | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    commissionerApi
      .getScoringInsights(leagueId)
      .then((data) => setInsights(data as ScoringInsights))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Failed to load scoring insights"))
      .finally(() => setLoading(false));
  }, [leagueId]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    return <div className="p-6 text-center text-surface-500 text-sm">Loading...</div>;
  }

  if (error) {
    return (
      <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400 text-sm" role="alert">
        {error}
      </div>
    );
  }

  if (!insights || !insights.available) {
    const need = insights?.weeks_required ?? 3;
    const have = insights?.weeks_available ?? 0;
    return (
      <div className="p-6 text-center text-surface-500 text-sm bg-surface-800/50 border border-surface-700 rounded-2xl">
        Not enough data yet -- scoring insights need at least {need} scored weeks (this league has {have} so far).
      </div>
    );
  }

  const sections: { title: string; items: { summary: string }[] | undefined; emptyText: string }[] = [
    { title: "Category Variance", items: insights.category_variance, emptyText: "No scoring categories stand out as unusually swingy right now." },
    { title: "Coach Bonus Impact", items: insights.coach_bonus_impact, emptyText: "No coach bonuses stand out as over- or under-powered right now." },
    { title: "Positional Balance", items: insights.positional_balance, emptyText: "No large scoring gap between positions right now." },
  ];

  return (
    <div className="space-y-4">
      <p className="text-xs text-surface-500">
        Based on {insights.weeks_available} scored week{insights.weeks_available === 1 ? "" : "s"} so far. Suggestions only -- you decide what&apos;s worth changing.
      </p>
      {sections.map(({ title, items, emptyText }) => (
        <div key={title} className="bg-surface-800/50 border border-surface-700 rounded-2xl p-4">
          <h3 className="text-sm font-semibold text-white mb-3">{title}</h3>
          {items && items.length > 0 ? (
            <ul className="space-y-2">
              {items.map((item, i) => (
                <li key={i} className="flex items-start gap-2 text-sm text-surface-300">
                  <BarChart3 className="w-3.5 h-3.5 text-purple-400 shrink-0 mt-0.5" />
                  <span>{item.summary}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-surface-500">{emptyText}</p>
          )}
        </div>
      ))}
    </div>
  );
}

// ═══════════════════════════════════════════
//  TAB 9: SCHEDULE INSIGHTS (AI Co-Commissioner v1, Phase 2)
// ═══════════════════════════════════════════
// Same zero-LLM, computed-data pattern as InsightsPanel/HealthPanel.
// Never suggests actually changing the schedule -- no such mechanism
// exists in this app -- just flags which teams have a notably easier
// or harder run of remaining opponents.

const SOS_FLAG_STYLES: Record<string, string> = {
  hard_stretch: "text-red-400",
  easy_stretch: "text-green-400",
};

function ScheduleInsightsPanel({ leagueId }: { leagueId: string }) {
  const [sos, setSos] = useState<ScheduleInsights | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    commissionerApi
      .getScheduleInsights(leagueId)
      .then((data) => setSos(data as ScheduleInsights))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Failed to load schedule insights"))
      .finally(() => setLoading(false));
  }, [leagueId]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    return <div className="p-6 text-center text-surface-500 text-sm">Loading...</div>;
  }

  if (error) {
    return (
      <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400 text-sm" role="alert">
        {error}
      </div>
    );
  }

  if (!sos || !sos.available) {
    return (
      <div className="p-6 text-center text-surface-500 text-sm bg-surface-800/50 border border-surface-700 rounded-2xl">
        {sos?.reason || "No schedule data available yet."}
      </div>
    );
  }

  if (sos.finale) {
    return (
      <div className="p-6 text-center text-surface-300 text-sm bg-purple-400/5 border border-purple-400/20 rounded-2xl">
        {sos.summary}
      </div>
    );
  }

  return (
    <div>
      <p className="text-xs text-surface-500 mb-4">
        Remaining opponent strength for the rest of the season. Suggestions only -- nothing here changes the actual schedule.
      </p>
      <div className="overflow-x-auto rounded-2xl border border-surface-700">
        <table className="w-full text-sm">
          <thead className="bg-surface-800 text-surface-400 text-xs uppercase tracking-wider">
            <tr>
              <th className="text-left px-4 py-3">Team</th>
              <th className="text-left px-4 py-3">Remaining SOS (avg opp pts/game)</th>
              <th className="text-left px-4 py-3">Outlook</th>
            </tr>
          </thead>
          <tbody>
            {(sos.teams || []).map((t) => (
              <tr key={t.team_id} className="border-t border-surface-800">
                <td className="px-4 py-3 text-white font-medium">{t.team_name}</td>
                <td className="px-4 py-3 text-surface-300">{t.sos_score === null ? "N/A" : t.sos_score}</td>
                <td className={`px-4 py-3 text-xs ${t.flag ? SOS_FLAG_STYLES[t.flag] : "text-surface-400"}`}>
                  {t.summary}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════
//  TAB 10: COMMUNICATION HELPERS (AI Co-Commissioner v1, Phase 2)
// ═══════════════════════════════════════════
// Generate -> review/edit -> send. Unlike DigestPanel/InsightsPanel,
// the draft renders in an EDITABLE textarea (not a read-only div) --
// the spec explicitly requires the commissioner can edit before
// sending. Sending fans out via the existing per-user notification
// system (no league feed exists) -- there's no "undo" once sent, so a
// confirmation is shown but there's no draft history/persistence.

function MessagesPanel({ leagueId }: { leagueId: string }) {
  const [messageType, setMessageType] = useState<string>(MESSAGE_TYPES[0].value);
  const [tone, setTone] = useState("professional");
  const [customContext, setCustomContext] = useState("");
  const [content, setContent] = useState("");
  const [drafting, setDrafting] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [sentCount, setSentCount] = useState<number | null>(null);

  const handleDraft = async () => {
    setDrafting(true);
    setError("");
    setSentCount(null);
    try {
      const result = (await commissionerApi.draftMessage(leagueId, messageType, tone, customContext)) as { content: string };
      setContent(result.content);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to draft message");
    }
    setDrafting(false);
  };

  const handleSend = async () => {
    if (!content.trim()) return;
    setSending(true);
    setError("");
    try {
      const result = (await commissionerApi.sendMessage(leagueId, messageType, content)) as { recipients: number };
      setSentCount(result.recipients);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to send message");
    }
    setSending(false);
  };

  return (
    <div>
      <div className="flex items-center gap-3 flex-wrap mb-4">
        <div className="flex items-center gap-2">
          <span className="text-xs text-surface-500">Type:</span>
          <select
            value={messageType}
            onChange={(e) => { setMessageType(e.target.value); setSentCount(null); }}
            className="px-2 py-1.5 bg-surface-800 border border-surface-700 rounded-lg text-xs text-white"
          >
            {MESSAGE_TYPES.map((m) => (
              <option key={m.value} value={m.value}>{m.label}</option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-surface-500">Tone:</span>
          <select
            value={tone}
            onChange={(e) => setTone(e.target.value)}
            className="px-2 py-1.5 bg-surface-800 border border-surface-700 rounded-lg text-xs text-white"
          >
            {DIGEST_TONES.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
        </div>
      </div>

      <textarea
        value={customContext}
        onChange={(e) => setCustomContext(e.target.value)}
        placeholder="Optional -- anything specific you want mentioned (e.g. exact deadline date, extra context)..."
        rows={2}
        className="w-full mb-3 px-3 py-2 bg-surface-800 border border-surface-700 rounded-lg text-sm text-white placeholder-surface-500"
      />

      <button
        onClick={handleDraft}
        disabled={drafting}
        className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-bold bg-gold-400 hover:bg-gold-300 text-surface-900 disabled:opacity-50 transition-all mb-4"
      >
        {drafting ? (
          <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Drafting...</>
        ) : (
          <><Bot className="w-3.5 h-3.5" /> Draft with AI</>
        )}
      </button>

      {error && (
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400 text-sm" role="alert">
          {error}
        </div>
      )}

      {sentCount !== null && (
        <div className="mb-4 p-3 bg-green-500/10 border border-green-500/30 rounded-xl text-green-400 text-sm">
          Sent to {sentCount} recipient{sentCount === 1 ? "" : "s"}.
        </div>
      )}

      <label className="text-[10px] text-surface-500 uppercase tracking-wider">Message (editable before sending)</label>
      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        rows={8}
        placeholder="Draft a message above, or write your own here..."
        className="w-full mt-1 mb-4 px-3 py-2 bg-surface-800 border border-surface-700 rounded-lg text-sm text-surface-200 placeholder-surface-500 whitespace-pre-wrap"
      />

      <button
        onClick={handleSend}
        disabled={sending || !content.trim()}
        className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-bold bg-purple-500 hover:bg-purple-400 text-white disabled:opacity-50 transition-all"
      >
        {sending ? (
          <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Sending...</>
        ) : (
          <><Send className="w-3.5 h-3.5" /> Send to League</>
        )}
      </button>
    </div>
  );
}

// ═══════════════════════════════════════════
//  TAB 11: AI CO-COMMISSIONER CHAT (deferred item 7)
// ═══════════════════════════════════════════
// The first genuinely new UI pattern this initiative has needed --
// every other tab is generate-once-and-display, not a real
// back-and-forth. Grounded in a fresh league-data snapshot every
// turn (see chat_service.py) -- not a generic chatbot.

function ChatPanel({ leagueId }: { leagueId: string }) {
  const [messages, setMessages] = useState<ChatMessageItem[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    commissionerApi
      .getChatHistory(leagueId)
      .then((data) => setMessages((data as { messages: ChatMessageItem[] }).messages))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Failed to load chat"))
      .finally(() => setLoading(false));
  }, [leagueId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, sending]);

  const handleSend = async () => {
    const text = input.trim();
    if (!text || sending) return;
    setSending(true);
    setError("");
    const optimisticUser: ChatMessageItem = {
      id: `optimistic-${Date.now()}`, role: "user", content: text, created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, optimisticUser]);
    setInput("");
    try {
      const reply = (await commissionerApi.sendChatMessage(leagueId, text)) as ChatMessageItem;
      setMessages((prev) => [...prev, reply]);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to send message");
    }
    setSending(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleClear = async () => {
    try {
      await commissionerApi.clearChatHistory(leagueId);
      setMessages([]);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to clear conversation");
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs text-surface-500">
          Ask about league health, recent activity, trades, and more -- grounded in this league&apos;s actual data.
        </p>
        <button
          onClick={handleClear}
          className="inline-flex items-center gap-1 text-xs text-surface-500 hover:text-red-400 transition-colors"
        >
          <Trash2 className="w-3.5 h-3.5" /> Clear Conversation
        </button>
      </div>

      {error && (
        <div className="mb-3 p-3 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400 text-sm" role="alert">
          {error}
        </div>
      )}

      <div
        ref={scrollRef}
        className="h-96 overflow-y-auto bg-surface-800/50 border border-surface-700 rounded-2xl p-4 space-y-3 mb-3"
      >
        {loading ? (
          <div className="text-center text-surface-500 text-sm">Loading...</div>
        ) : messages.length === 0 ? (
          <div className="text-center text-surface-500 text-sm">
            No messages yet -- ask something like &quot;How healthy is the league?&quot;
          </div>
        ) : (
          messages.map((m) => (
            <div key={m.id} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[80%] px-3 py-2 rounded-2xl text-sm whitespace-pre-wrap leading-relaxed ${
                  m.role === "user"
                    ? "bg-gold-400 text-surface-900"
                    : "bg-purple-400/10 border border-purple-400/20 text-surface-200"
                }`}
              >
                {m.content}
              </div>
            </div>
          ))
        )}
        {sending && (
          <div className="flex justify-start">
            <div className="px-3 py-2 rounded-2xl bg-purple-400/10 border border-purple-400/20 text-surface-400 text-sm inline-flex items-center gap-1.5">
              <Loader2 className="w-3.5 h-3.5 animate-spin" /> Thinking...
            </div>
          </div>
        )}
      </div>

      <div className="flex items-end gap-2">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask the AI Co-Commissioner..."
          rows={2}
          className="flex-1 px-3 py-2 bg-surface-800 border border-surface-700 rounded-lg text-sm text-white placeholder-surface-500 resize-none"
        />
        <button
          onClick={handleSend}
          disabled={sending || !input.trim()}
          className="inline-flex items-center gap-1.5 px-4 py-2.5 rounded-lg text-xs font-bold bg-purple-500 hover:bg-purple-400 text-white disabled:opacity-50 transition-all"
        >
          {sending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
        </button>
      </div>
    </div>
  );
}
