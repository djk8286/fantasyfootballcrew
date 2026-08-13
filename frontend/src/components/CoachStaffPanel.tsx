"use client";

import { useState, useEffect, useCallback } from "react";
import { Plus, Save, Trash2, Users } from "lucide-react";
import { coachesApi } from "@/lib/api-client";

// Extracted from the commissioner-only CoachesPanel (Phase 2 Step 4,
// "Front-Office finish-out") so a team's own owner/co-owner can manage
// their coaching staff directly, rather than the commissioner tab being
// the only place coaches were ever visible or manageable in the app. The
// commissioner page still renders this (with its own team-selector above
// it, since oversight needs to pick which team) -- this component itself
// no longer owns "which team" at all, just "given a team, manage its
// staff."

interface Coach {
  id: string;
  name: string;
  position: string;
  team_id: string;
  bonus_type: string | null;
  bonus_value: number | null;
  is_active: boolean;
}

const COACH_POSITIONS = ["HC", "OC", "DC", "STC"];

export default function CoachStaffPanel({ teamId, canManage }: { teamId: string; canManage: boolean }) {
  const [coaches, setCoaches] = useState<Coach[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState("");

  const [name, setName] = useState("");
  const [position, setPosition] = useState("HC");
  const [bonusType, setBonusType] = useState("flat_weekly");
  const [bonusValue, setBonusValue] = useState("");

  const loadCoaches = useCallback(async () => {
    if (!teamId) {
      setCoaches([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const data = await coachesApi.listByTeam(teamId);
      setCoaches(Array.isArray(data) ? (data as Coach[]) : []);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, [teamId]);

  useEffect(() => {
    loadCoaches();
  }, [loadCoaches]);

  // Cap-aware UI (backend's 400 is still the real source of truth --
  // this is purely a nicer experience than showing a form that will just
  // fail). Recompute from the live coaches list, not local form state.
  const filledPositions = new Set(coaches.filter((c) => c.is_active).map((c) => c.position));
  const availablePositions = COACH_POSITIONS.filter((p) => !filledPositions.has(p));
  const staffFull = availablePositions.length === 0;

  useEffect(() => {
    // Keep the position select pointed at something still open, e.g.
    // right after a successful add fills the previously-selected slot.
    if (availablePositions.length > 0 && !availablePositions.includes(position)) {
      setPosition(availablePositions[0]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [coaches]);

  const handleAdd = async () => {
    if (!teamId || !name) return;
    setError("");
    try {
      await coachesApi.create(teamId, {
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
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl px-4 py-2 mb-4" role="alert">
          <p className="text-red-400 text-sm">{error}</p>
        </div>
      )}

      {canManage && (
        <div className="flex items-center gap-3 mb-4 flex-wrap">
          {staffFull ? (
            <span className="ml-auto text-xs text-surface-500 font-medium">Coaching staff full (4/4)</span>
          ) : (
            <button
              onClick={() => setShowForm(!showForm)}
              disabled={!teamId}
              className="ml-auto inline-flex items-center gap-1 bg-gold-400 hover:bg-gold-300 text-surface-900 px-3 py-1.5 rounded-lg text-xs font-bold transition-all disabled:opacity-50"
            >
              <Plus className="w-3 h-3" />
              {showForm ? "Cancel" : "Add Coach"}
            </button>
          )}
        </div>
      )}

      {canManage && showForm && !staffFull && (
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
                {availablePositions.map((p) => (
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
                <option value="win_bonus">Bonus for winning your matchup</option>
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
              <p className="text-[9px] text-surface-600 mt-0.5">
                {bonusType === "win_bonus"
                  ? "Added only in weeks this team wins its matchup"
                  : "Added to the team's score every week"}
              </p>
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
              {canManage && (
                <button
                  onClick={() => handleDelete(c.id)}
                  className="text-surface-500 hover:text-red-400 transition-colors shrink-0 ml-2"
                  title="Remove coach"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
