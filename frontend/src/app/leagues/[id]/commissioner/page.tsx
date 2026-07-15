"use client";

import { useState, useEffect, useCallback } from "react";
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
} from "lucide-react";
import { commissionerApi, leaguesApi, teamsApi, coachesApi } from "@/lib/api-client";

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
  owner_id: string;
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

interface Coach {
  id: string;
  name: string;
  position: string;
  team_id: string;
  bonus_type: string | null;
  bonus_value: number | null;
  is_active: boolean;
}

type Tab = "adjustments" | "trades" | "draft-order" | "coaches";

const CURRENT_YEAR = 2026;

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
          <div className="bg-red-500/10 border border-red-500/20 rounded-xl px-4 py-3">
            <p className="text-red-400 text-sm">{error}</p>
          </div>
        </div>
      )}

      {/* Tab bar */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-6">
        <div className="flex gap-1 bg-surface-800 rounded-xl p-1 border border-surface-700">
          {[
            { id: "adjustments" as Tab, label: "Points Adjustments", icon: Scale },
            { id: "trades" as Tab, label: "Trades", icon: Ban },
            { id: "draft-order" as Tab, label: "Draft Order", icon: ArrowUpDown },
            { id: "coaches" as Tab, label: "Coaches", icon: Users },
          ].map(({ id, label, icon: Icon }) => (
            <button
              key={id}
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
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl px-4 py-2 mb-4">
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
    try {
      await commissionerApi.reviewTrade(leagueId, tradeId, action);
      await loadTrades();
    } catch {
      setError("Failed to review trade");
    }
    setProcessing(null);
  };

  const [error, setError] = useState("");

  const statusColors: Record<string, string> = {
    pending: "bg-yellow-500/10 text-yellow-400 border-yellow-500/20",
    approved: "bg-green-500/10 text-green-400 border-green-500/20",
    denied: "bg-red-500/10 text-red-400 border-red-500/20",
  };

  return (
    <div>
      {error && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl px-4 py-2 mb-4">
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
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl px-4 py-2 mb-4">
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
                    className="p-1 text-surface-500 hover:text-white disabled:opacity-20 disabled:cursor-not-allowed transition-colors"
                  >
                    <ChevronLeft className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => moveTeam(idx, 1)}
                    disabled={idx === order.length - 1}
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

const COACH_POSITIONS = ["HC", "OC", "DC", "STC"];

function CoachesPanel({ teams }: { teams: Team[] }) {
  const [selTeam, setSelTeam] = useState(teams[0]?.id || "");
  const [coaches, setCoaches] = useState<Coach[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState("");

  const [name, setName] = useState("");
  const [position, setPosition] = useState("HC");
  const [bonusType, setBonusType] = useState("flat_weekly");
  const [bonusValue, setBonusValue] = useState("");

  const loadCoaches = useCallback(async () => {
    if (!selTeam) {
      setCoaches([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const data = await coachesApi.listByTeam(selTeam);
      setCoaches(Array.isArray(data) ? (data as Coach[]) : []);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, [selTeam]);

  useEffect(() => {
    loadCoaches();
  }, [loadCoaches]);

  const handleAdd = async () => {
    if (!selTeam || !name) return;
    setError("");
    try {
      await coachesApi.create(selTeam, {
        name,
        position,
        bonus_type: bonusType || undefined,
        bonus_value: bonusValue ? parseFloat(bonusValue) : undefined,
      });
      setShowForm(false);
      setName("");
      setBonusValue("");
      await loadCoaches();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add coach");
    }
  };

  const handleDelete = async (coachId: string) => {
    setError("");
    try {
      await coachesApi.delete(coachId);
      await loadCoaches();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove coach");
    }
  };

  return (
    <div>
      {error && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl px-4 py-2 mb-4">
          <p className="text-red-400 text-sm">{error}</p>
        </div>
      )}

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
        <button
          onClick={() => setShowForm(!showForm)}
          disabled={!selTeam}
          className="ml-auto inline-flex items-center gap-1 bg-gold-400 hover:bg-gold-300 text-surface-900 px-3 py-1.5 rounded-lg text-xs font-bold transition-all disabled:opacity-50"
        >
          <Plus className="w-3 h-3" />
          {showForm ? "Cancel" : "Add Coach"}
        </button>
      </div>

      {showForm && (
        <div className="bg-surface-800 border border-surface-700 rounded-xl p-4 mb-4">
          <h3 className="text-sm font-semibold text-white mb-3">New Coach / Coordinator</h3>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-3">
            <div>
              <label className="text-[10px] text-surface-500 uppercase tracking-wider">Name</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Coach name"
                className="w-full mt-1 px-3 py-2 bg-surface-900 border border-surface-700 rounded-lg text-sm text-white placeholder-surface-500"
              />
            </div>
            <div>
              <label className="text-[10px] text-surface-500 uppercase tracking-wider">Position</label>
              <select
                value={position}
                onChange={(e) => setPosition(e.target.value)}
                className="w-full mt-1 px-3 py-2 bg-surface-900 border border-surface-700 rounded-lg text-sm text-white"
              >
                {COACH_POSITIONS.map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-[10px] text-surface-500 uppercase tracking-wider">Bonus Type</label>
              <select
                value={bonusType}
                onChange={(e) => setBonusType(e.target.value)}
                className="w-full mt-1 px-3 py-2 bg-surface-900 border border-surface-700 rounded-lg text-sm text-white"
              >
                <option value="flat_weekly">Flat weekly bonus</option>
              </select>
            </div>
            <div>
              <label className="text-[10px] text-surface-500 uppercase tracking-wider">Bonus Points</label>
              <input
                type="number"
                step="0.1"
                value={bonusValue}
                onChange={(e) => setBonusValue(e.target.value)}
                placeholder="e.g. 2.5"
                className="w-full mt-1 px-3 py-2 bg-surface-900 border border-surface-700 rounded-lg text-sm text-white placeholder-surface-500"
              />
              <p className="text-[9px] text-surface-600 mt-0.5">Added to the team&apos;s score every week</p>
            </div>
          </div>
          <button
            onClick={handleAdd}
            disabled={!name}
            className="inline-flex items-center gap-1 bg-gold-400 hover:bg-gold-300 text-surface-900 px-4 py-2 rounded-lg text-sm font-bold transition-all disabled:opacity-50"
          >
            <Save className="w-4 h-4" />
            Add Coach
          </button>
        </div>
      )}

      {loading ? (
        <div className="text-center text-surface-500 py-8 text-sm">Loading coaching staff...</div>
      ) : coaches.length === 0 ? (
        <div className="text-center text-surface-500 py-12">
          <Users className="w-10 h-10 mx-auto mb-3 opacity-30" />
          <p className="text-sm">No coaches yet</p>
          <p className="text-xs text-surface-600 mt-1">Add HC/OC/DC/STC coaches with performance bonuses</p>
        </div>
      ) : (
        <div className="space-y-2">
          {coaches.map((c) => (
            <div
              key={c.id}
              className="flex items-center justify-between bg-surface-800/50 border border-surface-700 rounded-xl px-4 py-3"
            >
              <div className="flex items-center gap-3 min-w-0">
                <div className="w-8 h-8 rounded-lg bg-gold-400/10 border border-gold-400/20 flex items-center justify-center text-[10px] font-bold text-gold-400">
                  {c.position}
                </div>
                <div className="min-w-0">
                  <span className="text-sm font-semibold text-white">{c.name}</span>
                  {c.bonus_type && c.bonus_value != null && (
                    <p className="text-xs text-surface-400">
                      +{c.bonus_value} pts/week ({c.bonus_type.replace(/_/g, " ")})
                    </p>
                  )}
                </div>
              </div>
              <button
                onClick={() => handleDelete(c.id)}
                className="text-surface-500 hover:text-red-400 transition-colors shrink-0 ml-2"
                title="Remove coach"
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
