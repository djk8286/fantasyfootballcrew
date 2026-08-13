"use client";

import { useState, useEffect } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { leaguesApi } from "@/lib/api-client";
import { ArrowLeft, Save, Loader2, RefreshCw, DollarSign } from "lucide-react";

interface SalaryCapSettings {
  enabled: boolean;
  cap_total: number;
  max_roster_size: number;
  top_salary: number;
  bottom_salary: number;
  waiver_salary_pct: number;
  dead_money_pct: number;
  default_contract_years: number;
  waiver_contract_years: number;
}

export default function SalaryCapSettingsPage() {
  const params = useParams();
  const id = params.id as string;

  const [league, setLeague] = useState<{ name: string } | null>(null);
  const [settings, setSettings] = useState<SalaryCapSettings | null>(null);
  const [original, setOriginal] = useState<SalaryCapSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!id) return;
    Promise.all([
      leaguesApi.get(id).catch(() => null),
      leaguesApi.getSalaryCapSettings(id).catch(() => null),
    ])
      .then(([leagueData, settingsData]) => {
        if (leagueData) setLeague(leagueData as { name: string });
        if (settingsData) {
          setSettings(settingsData as SalaryCapSettings);
          setOriginal(JSON.parse(JSON.stringify(settingsData)));
        } else {
          setError("Failed to load salary cap settings");
        }
      })
      .catch(() => setError("Failed to load salary cap settings"))
      .finally(() => setLoading(false));
  }, [id]);

  const update = <K extends keyof SalaryCapSettings>(key: K, value: SalaryCapSettings[K]) => {
    setSettings((prev) => (prev ? { ...prev, [key]: value } : prev));
    setSaved(false);
  };

  const handleSave = async () => {
    if (!settings || !id) return;
    setSaving(true);
    setError("");
    try {
      await leaguesApi.updateSalaryCapSettings(id, settings as unknown as Record<string, unknown>);
      setSaved(true);
      setOriginal(JSON.parse(JSON.stringify(settings)));
      setTimeout(() => setSaved(false), 3000);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const hasChanges = JSON.stringify(settings) !== JSON.stringify(original);

  if (loading) {
    return (
      <div className="min-h-screen bg-surface-900 flex items-center justify-center">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 border-2 border-gold-400 border-t-transparent rounded-full animate-spin" />
          <span className="text-surface-400">Loading salary cap settings...</span>
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
              <Link href={`/leagues/${id}`} className="text-surface-400 hover:text-white transition-colors shrink-0">
                <ArrowLeft className="w-5 h-5" />
              </Link>
              <h1 className="text-lg font-bold text-white truncate flex items-center gap-2">
                <DollarSign className="w-4 h-4 text-gold-400" />
                Salary Cap Settings
              </h1>
              {league && <span className="text-surface-400 text-sm truncate hidden sm:inline">{league.name}</span>}
            </div>
            <button
              onClick={handleSave}
              disabled={saving || !hasChanges}
              className={`inline-flex items-center gap-1.5 px-5 py-2 rounded-lg text-xs font-bold transition-all shrink-0 ${
                saved ? "bg-green-500 text-white" : "bg-gold-400 hover:bg-gold-300 text-surface-900 disabled:opacity-40 disabled:cursor-not-allowed"
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
          <div className="mb-6 p-3 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400 text-sm" role="alert">{error}</div>
        )}

        {settings && (
          <div className="space-y-6">
            <div className="bg-surface-800/60 border border-surface-700 rounded-2xl p-5">
              <div className="flex items-center justify-between">
                <div>
                  <h3 id="enable-cap-label" className="text-white font-bold text-sm">Enable Salary Cap</h3>
                  <p className="text-surface-400 text-xs mt-1">
                    Off by default. Once on, every draft pick gets a salary from the
                    scale below, and trades/waiver claims are blocked if they&apos;d push a
                    team over the cap.
                  </p>
                </div>
                <button
                  onClick={() => update("enabled", !settings.enabled)}
                  role="switch"
                  aria-checked={settings.enabled}
                  aria-labelledby="enable-cap-label"
                  className={`shrink-0 relative w-12 h-7 rounded-full transition-colors ${settings.enabled ? "bg-gold-400" : "bg-surface-700"}`}
                >
                  <span
                    className={`absolute top-1 w-5 h-5 rounded-full bg-white transition-transform ${settings.enabled ? "translate-x-6" : "translate-x-1"}`}
                  />
                </button>
              </div>
            </div>

            <div className={`space-y-6 transition-opacity ${settings.enabled ? "" : "opacity-40 pointer-events-none"}`}>
              <div className="bg-surface-800/60 border border-surface-700 rounded-2xl overflow-hidden">
                <div className="px-5 py-3.5 bg-surface-800 border-b border-surface-700">
                  <h3 className="text-white font-bold text-sm">Cap &amp; Roster</h3>
                </div>
                <div className="divide-y divide-surface-700/50">
                  <div className="flex items-center justify-between px-5 py-3">
                    <div>
                      <label className="text-sm text-surface-300">Salary Cap Total</label>
                      <p className="text-xs text-surface-500">Total salary a team&apos;s active contracts can add up to.</p>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-surface-500">$</span>
                      <input
                        type="number"
                        min={1}
                        value={settings.cap_total}
                        onChange={(e) => update("cap_total", parseFloat(e.target.value) || 1)}
                        className="w-24 px-2.5 py-1.5 bg-surface-900 border border-surface-600 rounded-lg text-white text-sm text-right focus:outline-none focus:ring-1 focus:ring-gold-400 font-mono"
                      />
                    </div>
                  </div>
                  <div className="flex items-center justify-between px-5 py-3">
                    <div>
                      <label className="text-sm text-surface-300">Max Roster Size</label>
                      <p className="text-xs text-surface-500">Total players (bench + starters) a team can hold at once.</p>
                    </div>
                    <input
                      type="number"
                      min={1}
                      value={settings.max_roster_size}
                      onChange={(e) => update("max_roster_size", parseInt(e.target.value, 10) || 1)}
                      className="w-20 px-2.5 py-1.5 bg-surface-900 border border-surface-600 rounded-lg text-white text-sm text-right focus:outline-none focus:ring-1 focus:ring-gold-400 font-mono"
                    />
                  </div>
                </div>
              </div>

              <div className="bg-surface-800/60 border border-surface-700 rounded-2xl overflow-hidden">
                <div className="px-5 py-3.5 bg-surface-800 border-b border-surface-700">
                  <h3 className="text-white font-bold text-sm">Draft Salary Scale</h3>
                </div>
                <div className="p-4">
                  <p className="text-surface-400 text-xs mb-3">
                    Every pick&apos;s salary is a straight-line interpolation between these
                    two numbers -- the 1st overall pick costs the top figure, the last
                    pick costs the bottom figure, everything in between scales linearly.
                  </p>
                  <div className="flex items-center gap-4">
                    <div>
                      <label className="text-[10px] text-surface-500 uppercase tracking-wider block mb-1">1st Overall Pick</label>
                      <div className="flex items-center gap-1">
                        <span className="text-xs text-surface-500">$</span>
                        <input
                          type="number"
                          min={0}
                          value={settings.top_salary}
                          onChange={(e) => update("top_salary", parseFloat(e.target.value) || 0)}
                          className="w-24 px-2.5 py-1.5 bg-surface-900 border border-surface-600 rounded-lg text-white text-sm text-right focus:outline-none focus:ring-1 focus:ring-gold-400 font-mono"
                        />
                      </div>
                    </div>
                    <div>
                      <label className="text-[10px] text-surface-500 uppercase tracking-wider block mb-1">Last Pick</label>
                      <div className="flex items-center gap-1">
                        <span className="text-xs text-surface-500">$</span>
                        <input
                          type="number"
                          min={0}
                          value={settings.bottom_salary}
                          onChange={(e) => update("bottom_salary", parseFloat(e.target.value) || 0)}
                          className="w-24 px-2.5 py-1.5 bg-surface-900 border border-surface-600 rounded-lg text-white text-sm text-right focus:outline-none focus:ring-1 focus:ring-gold-400 font-mono"
                        />
                      </div>
                    </div>
                    <div>
                      <label className="text-[10px] text-surface-500 uppercase tracking-wider block mb-1">Contract Years</label>
                      <input
                        type="number"
                        min={1}
                        max={4}
                        value={settings.default_contract_years}
                        onChange={(e) => update("default_contract_years", parseInt(e.target.value, 10) || 1)}
                        className="w-16 px-2.5 py-1.5 bg-surface-900 border border-surface-600 rounded-lg text-white text-sm text-right focus:outline-none focus:ring-1 focus:ring-gold-400 font-mono"
                      />
                    </div>
                  </div>
                </div>
              </div>

              <div className="bg-surface-800/60 border border-surface-700 rounded-2xl overflow-hidden">
                <div className="px-5 py-3.5 bg-surface-800 border-b border-surface-700">
                  <h3 className="text-white font-bold text-sm">Waivers &amp; Free Agency</h3>
                </div>
                <div className="p-4">
                  <p className="text-surface-400 text-xs mb-3">
                    A free-agent signing&apos;s salary comes from the same scale above
                    (keyed off the player&apos;s rank instead of a draft slot), scaled
                    down by this percentage.
                  </p>
                  <div className="flex items-center gap-4">
                    <div>
                      <label className="text-[10px] text-surface-500 uppercase tracking-wider block mb-1">Waiver Salary %</label>
                      <div className="flex items-center gap-1">
                        <input
                          type="number"
                          min={0}
                          max={200}
                          step="1"
                          value={Math.round(settings.waiver_salary_pct * 100)}
                          onChange={(e) => update("waiver_salary_pct", (parseFloat(e.target.value) || 0) / 100)}
                          className="w-20 px-2.5 py-1.5 bg-surface-900 border border-surface-600 rounded-lg text-white text-sm text-right focus:outline-none focus:ring-1 focus:ring-gold-400 font-mono"
                        />
                        <span className="text-xs text-surface-500">%</span>
                      </div>
                    </div>
                    <div>
                      <label className="text-[10px] text-surface-500 uppercase tracking-wider block mb-1">Contract Years</label>
                      <input
                        type="number"
                        min={1}
                        max={4}
                        value={settings.waiver_contract_years}
                        onChange={(e) => update("waiver_contract_years", parseInt(e.target.value, 10) || 1)}
                        className="w-16 px-2.5 py-1.5 bg-surface-900 border border-surface-600 rounded-lg text-white text-sm text-right focus:outline-none focus:ring-1 focus:ring-gold-400 font-mono"
                      />
                    </div>
                  </div>
                </div>
              </div>

              <div className="bg-surface-800/60 border border-surface-700 rounded-2xl overflow-hidden">
                <div className="px-5 py-3.5 bg-surface-800 border-b border-surface-700">
                  <h3 className="text-white font-bold text-sm">Dead Money</h3>
                </div>
                <div className="p-4">
                  <p className="text-surface-400 text-xs mb-3">
                    Releasing a player with more than 1 contract year left charges this
                    percentage of their salary against your cap for the rest of the
                    season. A 1-year deal never charges dead money.
                  </p>
                  <div>
                    <label className="text-[10px] text-surface-500 uppercase tracking-wider block mb-1">Dead Money %</label>
                    <div className="flex items-center gap-1">
                      <input
                        type="number"
                        min={0}
                        max={100}
                        step="1"
                        value={Math.round(settings.dead_money_pct * 100)}
                        onChange={(e) => update("dead_money_pct", (parseFloat(e.target.value) || 0) / 100)}
                        className="w-20 px-2.5 py-1.5 bg-surface-900 border border-surface-600 rounded-lg text-white text-sm text-right focus:outline-none focus:ring-1 focus:ring-gold-400 font-mono"
                      />
                      <span className="text-xs text-surface-500">%</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
