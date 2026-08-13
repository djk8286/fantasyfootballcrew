"use client";

import { useState, useEffect } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { leaguesApi } from "@/lib/api-client";
import { ArrowLeft, Save, Loader2, RefreshCw } from "lucide-react";

interface RosterSlots {
  QB: number;
  RB: number;
  WR: number;
  TE: number;
  FLEX: number;
  SUPERFLEX: number;
  K: number;
  DEF: number;
  DL: number;
  LB: number;
  DB: number;
  IDP_FLEX: number;
  [key: string]: number;
}

// Grouped so the standard offense/kicking slots (what every league already
// has) read as the "normal" part of the page, and IDP slots -- all 0 by
// default, opt-in -- read as a distinct, clearly-labeled section rather
// than blending in as just more rows.
const STANDARD_SLOTS: { key: keyof RosterSlots; label: string; hint: string }[] = [
  { key: "QB", label: "Quarterback", hint: "QB" },
  { key: "RB", label: "Running Back", hint: "RB" },
  { key: "WR", label: "Wide Receiver", hint: "WR" },
  { key: "TE", label: "Tight End", hint: "TE" },
  { key: "FLEX", label: "FLEX", hint: "RB/WR/TE" },
  { key: "SUPERFLEX", label: "Superflex", hint: "QB/RB/WR/TE" },
  { key: "K", label: "Kicker", hint: "K" },
  { key: "DEF", label: "Team Defense", hint: "DEF" },
];

const IDP_SLOTS: { key: keyof RosterSlots; label: string; hint: string }[] = [
  { key: "DL", label: "Defensive Line", hint: "DL" },
  { key: "LB", label: "Linebacker", hint: "LB" },
  { key: "DB", label: "Defensive Back", hint: "DB" },
  { key: "IDP_FLEX", label: "IDP FLEX", hint: "DL/LB/DB" },
];

export default function RosterSlotsPage() {
  const params = useParams();
  const id = params.id as string;

  const [league, setLeague] = useState<{ name: string } | null>(null);
  const [slots, setSlots] = useState<RosterSlots | null>(null);
  const [originalSlots, setOriginalSlots] = useState<RosterSlots | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!id) return;
    Promise.all([
      leaguesApi.get(id).catch(() => null),
      leaguesApi.getRosterSlots(id).catch(() => null),
    ])
      .then(([leagueData, slotsData]) => {
        if (leagueData) setLeague(leagueData as { name: string });
        if (slotsData) {
          setSlots(slotsData as RosterSlots);
          setOriginalSlots(JSON.parse(JSON.stringify(slotsData)));
        } else {
          setError("Failed to load roster slot settings");
        }
      })
      .catch(() => setError("Failed to load roster slot settings"))
      .finally(() => setLoading(false));
  }, [id]);

  const updateSlot = (key: keyof RosterSlots, value: number) => {
    setSlots((prev) => (prev ? { ...prev, [key]: Math.max(0, value) } : prev));
  };

  const handleSave = async () => {
    if (!slots || !id) return;
    setSaving(true);
    setSaved(false);
    setError("");
    try {
      await leaguesApi.updateRosterSlots(id, slots);
      setSaved(true);
      setOriginalSlots(JSON.parse(JSON.stringify(slots)));
      setTimeout(() => setSaved(false), 3000);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const hasChanges = JSON.stringify(slots) !== JSON.stringify(originalSlots);
  const totalSlots = slots ? Object.values(slots).reduce((a, b) => a + b, 0) : 0;
  const idpEnabled = slots ? (slots.DL || slots.LB || slots.DB || slots.IDP_FLEX) > 0 : false;

  if (loading) {
    return (
      <div className="min-h-screen bg-surface-900 flex items-center justify-center">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 border-2 border-gold-400 border-t-transparent rounded-full animate-spin" />
          <span className="text-surface-400">Loading roster settings...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-surface-900">
      <div className="sticky top-0 z-40 bg-surface-900/95 backdrop-blur-md border-b border-surface-700">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3 min-w-0">
              <Link
                href={`/leagues/${id}`}
                className="text-surface-400 hover:text-white transition-colors shrink-0"
              >
                <ArrowLeft className="w-5 h-5" />
              </Link>
              <h1 className="text-lg font-bold text-white truncate">
                Roster &amp; Starting Lineup Slots
              </h1>
              {league && (
                <span className="text-surface-400 text-sm truncate hidden sm:inline">
                  {league.name}
                </span>
              )}
            </div>
            <button
              onClick={handleSave}
              disabled={saving || !hasChanges}
              className={`inline-flex items-center gap-1.5 px-5 py-2 rounded-lg text-xs font-bold transition-all shrink-0 ${
                saved
                  ? "bg-green-500 text-white"
                  : "bg-gold-400 hover:bg-gold-300 text-surface-900 disabled:opacity-40 disabled:cursor-not-allowed"
              }`}
            >
              {saving ? (
                <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Saving...</>
              ) : saved ? (
                <><RefreshCw className="w-3.5 h-3.5" /> Saved!</>
              ) : (
                <><Save className="w-3.5 h-3.5" /> Save</>
              )}
            </button>
          </div>
        </div>
      </div>

      <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {error && (
          <div className="mb-6 p-3 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400 text-sm" role="alert">
            {error}
          </div>
        )}

        <p className="text-surface-400 text-sm mb-6">
          How many starters at each position. Everyone on a team&apos;s roster
          beyond these counts is bench -- roster players still count toward
          nothing until a lineup names them a starter for that week, except
          for teams that never set a lineup at all, which still score their
          whole roster (nothing changes for anyone who doesn&apos;t use this).
        </p>

        {slots && (
          <div className="space-y-6">
            <div className="bg-surface-800/60 border border-surface-700 rounded-2xl overflow-hidden">
              <div className="px-5 py-3.5 bg-surface-800 border-b border-surface-700 flex items-center justify-between">
                <h3 className="text-white font-bold text-sm">Standard Slots</h3>
                <span className="text-xs text-surface-500">Eligible positions</span>
              </div>
              <div className="divide-y divide-surface-700/50">
                {STANDARD_SLOTS.map(({ key, label, hint }) => (
                  <div key={key} className="flex items-center justify-between px-5 py-3">
                    <div>
                      <label htmlFor={`slot-${key}`} className="text-sm text-surface-300">
                        {label}
                      </label>
                      <span className="text-xs text-surface-500 ml-2">{hint}</span>
                    </div>
                    <input
                      id={`slot-${key}`}
                      type="number"
                      min={0}
                      step={1}
                      value={slots[key]}
                      onChange={(e) => updateSlot(key, parseInt(e.target.value, 10) || 0)}
                      className="w-20 px-2.5 py-1.5 bg-surface-900 border border-surface-600 rounded-lg text-white text-sm text-right focus:outline-none focus:ring-1 focus:ring-gold-400 font-mono"
                    />
                  </div>
                ))}
              </div>
            </div>

            <div className="bg-surface-800/60 border border-surface-700 rounded-2xl overflow-hidden">
              <div className="px-5 py-3.5 bg-surface-800 border-b border-surface-700 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <h3 className="text-white font-bold text-sm">IDP Slots</h3>
                  {idpEnabled && (
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-gold-400/20 text-gold-400">
                      ENABLED
                    </span>
                  )}
                </div>
                <span className="text-xs text-surface-500">Individual defensive players -- 0 by default</span>
              </div>
              <div className="divide-y divide-surface-700/50">
                {IDP_SLOTS.map(({ key, label, hint }) => (
                  <div key={key} className="flex items-center justify-between px-5 py-3">
                    <div>
                      <label htmlFor={`slot-${key}`} className="text-sm text-surface-300">
                        {label}
                      </label>
                      <span className="text-xs text-surface-500 ml-2">{hint}</span>
                    </div>
                    <input
                      id={`slot-${key}`}
                      type="number"
                      min={0}
                      step={1}
                      value={slots[key]}
                      onChange={(e) => updateSlot(key, parseInt(e.target.value, 10) || 0)}
                      className="w-20 px-2.5 py-1.5 bg-surface-900 border border-surface-600 rounded-lg text-white text-sm text-right focus:outline-none focus:ring-1 focus:ring-gold-400 font-mono"
                    />
                  </div>
                ))}
              </div>
            </div>

            <div className="flex items-center justify-between px-5 py-3 bg-surface-800/40 border border-surface-700/60 rounded-xl">
              <span className="text-sm text-surface-400">Total starting slots</span>
              <span className="text-lg font-bold text-gold-400">{totalSlots}</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
