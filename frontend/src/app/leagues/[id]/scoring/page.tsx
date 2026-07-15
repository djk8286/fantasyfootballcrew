"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { leaguesApi, scoringApi } from "@/lib/api-client";
import {
  ArrowLeft,
  Save,
  Loader2,
  RotateCcw,
  RefreshCw,
} from "lucide-react";

interface ScoringConfig {
  passing: Record<string, number>;
  rushing: Record<string, number>;
  receiving: Record<string, number>;
  defense: Record<string, number>;
  kicking: Record<string, number>;
  bonus: Record<string, number>;
  [key: string]: unknown;
}

const PRESETS = [
  {
    label: "Standard (non-PPR)",
    desc: "Classic scoring, 4pt passing TDs",
    build: (): ScoringConfig => ({
      passing: { pass_yds: 0.04, pass_td: 4, int: -2, pass_2pt: 2 },
      rushing: { rush_yds: 0.1, rush_td: 6, rush_2pt: 2 },
      receiving: { rec: 0, rec_yds: 0.1, rec_td: 6, rec_2pt: 2 },
      defense: { def_sack: 1, def_int: 2, def_fum_rec: 2, def_safety: 2, def_td: 6, st_fum_rec: 2, st_td: 6, def_ret_yds: 0.02 },
      kicking: { fg_0_39: 3, fg_40_49: 4, fg_50_plus: 5, xp: 1 },
      bonus: { pass_300_yds: 0, rush_100_yds: 0, rec_100_yds: 0 },
    }),
  },
  {
    label: "Half-PPR",
    desc: "0.5 PPR, 4pt passing TDs",
    build: (): ScoringConfig => ({
      passing: { pass_yds: 0.04, pass_td: 4, int: -2, pass_2pt: 2 },
      rushing: { rush_yds: 0.1, rush_td: 6, rush_2pt: 2 },
      receiving: { rec: 0.5, rec_yds: 0.1, rec_td: 6, rec_2pt: 2 },
      defense: { def_sack: 1, def_int: 2, def_fum_rec: 2, def_safety: 2, def_td: 6, st_fum_rec: 2, st_td: 6, def_ret_yds: 0.02 },
      kicking: { fg_0_39: 3, fg_40_49: 4, fg_50_plus: 5, xp: 1 },
      bonus: { pass_300_yds: 0, rush_100_yds: 0, rec_100_yds: 0 },
    }),
  },
  {
    label: "Full PPR",
    desc: "1.0 PPR, 6pt passing TDs (popular)",
    build: (): ScoringConfig => ({
      passing: { pass_yds: 0.04, pass_td: 6, int: -2, pass_2pt: 2 },
      rushing: { rush_yds: 0.1, rush_td: 6, rush_2pt: 2 },
      receiving: { rec: 1.0, rec_yds: 0.1, rec_td: 6, rec_2pt: 2 },
      defense: { def_sack: 1, def_int: 2, def_fum_rec: 2, def_safety: 2, def_td: 6, st_fum_rec: 2, st_td: 6, def_ret_yds: 0.02 },
      kicking: { fg_0_39: 3, fg_40_49: 4, fg_50_plus: 5, xp: 1 },
      bonus: { pass_300_yds: 3, rush_100_yds: 3, rec_100_yds: 3 },
    }),
  },
];

const LABELS: Record<string, Record<string, string>> = {
  passing: {
    pass_yds: "Passing Yards (per yard)",
    pass_td: "Passing TD",
    int: "Interception",
    pass_2pt: "2-Pt Conversion (Pass)",
  },
  rushing: {
    rush_yds: "Rushing Yards (per yard)",
    rush_td: "Rushing TD",
    rush_2pt: "2-Pt Conversion (Rush)",
  },
  receiving: {
    rec: "Per Reception (PPR)",
    rec_yds: "Receiving Yards (per yard)",
    rec_td: "Receiving TD",
    rec_2pt: "2-Pt Conversion (Rec)",
  },
  defense: {
    def_sack: "Sack",
    def_int: "Interception",
    def_fum_rec: "Fumble Recovery",
    def_safety: "Safety",
    def_td: "Defensive TD",
    st_fum_rec: "ST Fumble Recovery",
    st_td: "Special Teams TD",
    def_ret_yds: "Return Yards (per yard)",
  },
  kicking: {
    fg_0_39: "FG 0-39 yards",
    fg_40_49: "FG 40-49 yards",
    fg_50_plus: "FG 50+ yards",
    xp: "Extra Point",
  },
  bonus: {
    pass_300_yds: "300-Yard Passing Bonus",
    rush_100_yds: "100-Yard Rushing Bonus",
    rec_100_yds: "100-Yard Receiving Bonus",
  },
};

const CATEGORY_ICONS: Record<string, string> = {
  passing: "🏈",
  rushing: "💨",
  receiving: "✋",
  defense: "🛡️",
  kicking: "🦵",
  bonus: "🎯",
};

const CATEGORY_ORDER = ["passing", "rushing", "receiving", "defense", "kicking", "bonus"];

export default function ScoringPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;

  const [league, setLeague] = useState<{ name: string } | null>(null);
  const [config, setConfig] = useState<ScoringConfig | null>(null);
  const [originalConfig, setOriginalConfig] = useState<ScoringConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!id) return;
    Promise.all([
      leaguesApi.get(id).catch(() => null),
      scoringApi.getByLeagueV2(id).catch(() => ({} as ScoringConfig)),
    ])
      .then(([leagueData, scoringData]) => {
        if (leagueData) setLeague(leagueData as { name: string });
        const sc = (scoringData || {}) as ScoringConfig;
        setConfig(sc);
        setOriginalConfig(JSON.parse(JSON.stringify(sc)));
      })
      .catch(() => setError("Failed to load scoring settings"))
      .finally(() => setLoading(false));
  }, [id]);

  const updateStat = (category: string, stat: string, value: number) => {
    if (!config) return;
    setConfig((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        [category]: {
          ...(prev[category] as Record<string, number>),
          [stat]: value,
        },
      };
    });
  };

  const applyPreset = (presetIndex: number) => {
    const newConfig = PRESETS[presetIndex].build();
    setConfig(newConfig);
  };

  const resetToDefaults = async () => {
    try {
      const defaults = await scoringApi.getDefaults();
      setConfig(defaults as ScoringConfig);
    } catch {
      setError("Failed to load defaults");
    }
  };

  const handleSave = async () => {
    if (!config || !id) return;
    setSaving(true);
    setSaved(false);
    setError("");
    try {
      await scoringApi.updateByLeague(id, config as Record<string, unknown>);
      setSaved(true);
      setOriginalConfig(JSON.parse(JSON.stringify(config)));
      setTimeout(() => setSaved(false), 3000);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const hasChanges = JSON.stringify(config) !== JSON.stringify(originalConfig);

  if (loading) {
    return (
      <div className="min-h-screen bg-surface-900 flex items-center justify-center">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 border-2 border-gold-400 border-t-transparent rounded-full animate-spin" />
          <span className="text-surface-400">Loading scoring settings...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-surface-900">
      {/* Header */}
      <div className="sticky top-0 z-40 bg-surface-900/95 backdrop-blur-md border-b border-surface-700">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3 min-w-0">
              <Link
                href={`/leagues/${id}`}
                className="text-surface-400 hover:text-white transition-colors shrink-0"
              >
                <ArrowLeft className="w-5 h-5" />
              </Link>
              <h1 className="text-lg font-bold text-white truncate">
                Scoring Settings
              </h1>
              {league && (
                <span className="text-surface-400 text-sm truncate hidden sm:inline">
                  {league.name}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {hasChanges && (
                <button
                  onClick={resetToDefaults}
                  className="inline-flex items-center gap-1.5 border border-surface-600 text-surface-300 hover:text-white px-3 py-1.5 rounded-lg text-xs font-semibold transition-all"
                >
                  <RotateCcw className="w-3 h-3" />
                  Reset
                </button>
              )}
              <button
                onClick={handleSave}
                disabled={saving || !hasChanges}
                className={`inline-flex items-center gap-1.5 px-5 py-2 rounded-lg text-xs font-bold transition-all ${
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
      </div>

      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Error */}
        {error && (
          <div className="mb-6 p-3 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400 text-sm">
            {error}
          </div>
        )}

        {/* Presets */}
        <section className="mb-10">
          <h2 className="text-sm font-semibold text-surface-400 uppercase tracking-wider mb-3">
            Quick Presets
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {PRESETS.map((preset, idx) => (
              <button
                key={idx}
                onClick={() => applyPreset(idx)}
                className="text-left p-4 bg-surface-800 border border-surface-700 rounded-xl hover:border-gold-400/40 hover:bg-surface-750 transition-all"
              >
                <p className="text-white font-semibold text-sm">{preset.label}</p>
                <p className="text-surface-400 text-xs mt-1">{preset.desc}</p>
              </button>
            ))}
          </div>
        </section>

        {/* Detailed settings */}
        {config && (
          <div className="space-y-6">
            {CATEGORY_ORDER.map((category) => {
              const rules = config[category] as Record<string, number> | undefined;
              if (!rules || Object.keys(rules).length === 0) return null;
              const labels = LABELS[category] || {};

              return (
                <div
                  key={category}
                  className="bg-surface-800/60 border border-surface-700 rounded-2xl overflow-hidden"
                >
                  <div className="px-5 py-3.5 bg-surface-800 border-b border-surface-700 flex items-center gap-2">
                    <span className="text-lg">{CATEGORY_ICONS[category] || "📋"}</span>
                    <h3 className="text-white font-bold text-sm capitalize">
                      {category}
                    </h3>
                  </div>
                  <div className="divide-y divide-surface-700/50">
                    {Object.entries(rules).map(([stat, value]) => {
                      const label = labels[stat] || stat;
                      return (
                        <div
                          key={stat}
                          className="flex items-center justify-between px-5 py-3"
                        >
                          <label
                            htmlFor={`${category}-${stat}`}
                            className="text-sm text-surface-300 truncate mr-4"
                          >
                            {label}
                          </label>
                          <div className="flex items-center gap-2 shrink-0">
                            {value < 0 && (
                              <span className="text-xs text-surface-500">−</span>
                            )}
                            <input
                              id={`${category}-${stat}`}
                              type="number"
                              step="any"
                              value={Math.abs(value)}
                              onChange={(e) => {
                                const raw = parseFloat(e.target.value) || 0;
                                const signed = value < 0 ? -raw : raw;
                                updateStat(category, stat, signed);
                              }}
                              className="w-20 px-2.5 py-1.5 bg-surface-900 border border-surface-600 rounded-lg text-white text-sm text-right focus:outline-none focus:ring-1 focus:ring-gold-400 font-mono"
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                  {/* Quick toggles for common settings */}
                  {category === "passing" && (
                    <div className="px-5 py-3 bg-surface-900/50 border-t border-surface-700/50">
                      <p className="text-xs text-surface-500 mb-2">Quick Toggles</p>
                      <div className="flex gap-2">
                        <button
                          onClick={() => {
                            updateStat("passing", "pass_td", 4);
                            updateStat("bonus", "pass_300_yds", 0);
                          }}
                          className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                            rules["pass_td"] === 4
                              ? "bg-gold-400/20 text-gold-400 border border-gold-400/30"
                              : "bg-surface-900 text-surface-400 border border-surface-700"
                          }`}
                        >
                          4pt Passing TD
                        </button>
                        <button
                          onClick={() => {
                            updateStat("passing", "pass_td", 6);
                            updateStat("bonus", "pass_300_yds", 3);
                          }}
                          className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                            rules["pass_td"] === 6
                              ? "bg-gold-400/20 text-gold-400 border border-gold-400/30"
                              : "bg-surface-900 text-surface-400 border border-surface-700"
                          }`}
                        >
                          6pt Passing TD
                        </button>
                      </div>
                    </div>
                  )}
                  {category === "receiving" && (
                    <div className="px-5 py-3 bg-surface-900/50 border-t border-surface-700/50">
                      <p className="text-xs text-surface-500 mb-2">Quick Toggles</p>
                      <div className="flex gap-2">
                        {[
                          { label: "Standard (0)", val: 0 },
                          { label: "Half-PPR (0.5)", val: 0.5 },
                          { label: "Full PPR (1.0)", val: 1.0 },
                        ].map((opt) => (
                          <button
                            key={opt.val}
                            onClick={() => updateStat("receiving", "rec", opt.val)}
                            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                              rules["rec"] === opt.val
                                ? "bg-gold-400/20 text-gold-400 border border-gold-400/30"
                                : "bg-surface-900 text-surface-400 border border-surface-700"
                            }`}
                          >
                            {opt.label}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                  {category === "bonus" && (
                    <div className="px-5 py-3 bg-surface-900/50 border-t border-surface-700/50">
                      <p className="text-xs text-surface-500 mb-2">Quick Toggles</p>
                      <div className="flex flex-wrap gap-2">
                        {[
                          { label: "No Bonuses", build: () => ({ pass_300_yds: 0, rush_100_yds: 0, rec_100_yds: 0 }) },
                          { label: "+3 Bonuses", build: () => ({ pass_300_yds: 3, rush_100_yds: 3, rec_100_yds: 3 }) },
                          { label: "+5 Bonuses", build: () => ({ pass_300_yds: 5, rush_100_yds: 5, rec_100_yds: 5 }) },
                        ].map((opt) => (
                          <button
                            key={opt.label}
                            onClick={() => {
                              const newBonuses = opt.build();
                              Object.entries(newBonuses).forEach(([k, v]) =>
                                updateStat("bonus", k, v)
                              );
                            }}
                            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                              (rules["rush_100_yds"] === opt.build().rush_100_yds)
                                ? "bg-gold-400/20 text-gold-400 border border-gold-400/30"
                                : "bg-surface-900 text-surface-400 border border-surface-700"
                            }`}
                          >
                            {opt.label}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}

            {/* Summary */}
            <div className="bg-surface-800/40 border border-surface-700 rounded-2xl p-5">
              <h3 className="text-sm font-semibold text-white mb-2">How scoring works</h3>
              <ul className="text-xs text-surface-400 space-y-1.5">
                <li>• All point values are <strong className="text-surface-300">per unit</strong> (e.g., 0.04 per passing yard = 1pt per 25 yards)</li>
                <li>• Negative values mean <strong className="text-surface-300">penalties</strong> (e.g., -2 for interceptions)</li>
                <li>• Bonuses trigger when a player <strong className="text-surface-300">reaches the threshold</strong> in a single game</li>
                <li>• Defense scores are applied to team defense/special teams units</li>
              </ul>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
