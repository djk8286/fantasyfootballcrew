"use client";

import { useState, useEffect } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { leaguesApi } from "@/lib/api-client";
import { ArrowLeft, Save, Loader2, RefreshCw, Trophy, Swords } from "lucide-react";

interface PlayoffSettings {
  enabled: boolean;
  regular_season_weeks: number;
  num_teams: number;
  seeding_method: "wins" | "points";
  conference_bracket_mode: "combined" | "separate";
}

// Rivalry Week (Phase 3) -- backed by its own API resource
// (rivalry-week-settings), independent of playoff_settings above, so it
// gets its own local state and its own small save action rather than
// being folded into the page's single top-level Save button.
interface RivalryWeekSettings {
  enabled: boolean;
  week: number | null;
  bonus_value: number;
}

export default function PlayoffSettingsPage() {
  const params = useParams();
  const id = params.id as string;

  const [league, setLeague] = useState<{ name: string; league_type: string } | null>(null);
  const [settings, setSettings] = useState<PlayoffSettings | null>(null);
  const [original, setOriginal] = useState<PlayoffSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  const [rivalrySettings, setRivalrySettings] = useState<RivalryWeekSettings | null>(null);
  const [rivalryOriginal, setRivalryOriginal] = useState<RivalryWeekSettings | null>(null);
  const [rivalrySaving, setRivalrySaving] = useState(false);
  const [rivalrySaved, setRivalrySaved] = useState(false);
  const [rivalryError, setRivalryError] = useState("");

  useEffect(() => {
    if (!id) return;
    Promise.all([
      leaguesApi.get(id).catch(() => null),
      leaguesApi.getPlayoffSettings(id).catch(() => null),
      leaguesApi.getRivalryWeekSettings(id).catch(() => null),
    ])
      .then(([leagueData, settingsData, rivalryData]) => {
        if (leagueData) setLeague(leagueData as { name: string; league_type: string });
        if (settingsData) {
          setSettings(settingsData as PlayoffSettings);
          setOriginal(JSON.parse(JSON.stringify(settingsData)));
        } else {
          setError("Failed to load playoff settings");
        }
        if (rivalryData) {
          setRivalrySettings(rivalryData as RivalryWeekSettings);
          setRivalryOriginal(JSON.parse(JSON.stringify(rivalryData)));
        }
      })
      .catch(() => setError("Failed to load playoff settings"))
      .finally(() => setLoading(false));
  }, [id]);

  const update = <K extends keyof PlayoffSettings>(key: K, value: PlayoffSettings[K]) => {
    setSettings((prev) => (prev ? { ...prev, [key]: value } : prev));
    setSaved(false);
  };

  const handleSave = async () => {
    if (!settings || !id) return;
    setSaving(true);
    setError("");
    try {
      await leaguesApi.updatePlayoffSettings(id, settings as unknown as Record<string, unknown>);
      setSaved(true);
      setOriginal(JSON.parse(JSON.stringify(settings)));
      setTimeout(() => setSaved(false), 3000);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const updateRivalry = <K extends keyof RivalryWeekSettings>(key: K, value: RivalryWeekSettings[K]) => {
    setRivalrySettings((prev) => (prev ? { ...prev, [key]: value } : prev));
    setRivalrySaved(false);
  };

  const handleSaveRivalry = async () => {
    if (!rivalrySettings || !id) return;
    setRivalrySaving(true);
    setRivalryError("");
    try {
      await leaguesApi.updateRivalryWeekSettings(id, rivalrySettings as unknown as Record<string, unknown>);
      setRivalrySaved(true);
      setRivalryOriginal(JSON.parse(JSON.stringify(rivalrySettings)));
      setTimeout(() => setRivalrySaved(false), 3000);
    } catch (err: unknown) {
      setRivalryError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setRivalrySaving(false);
    }
  };

  const hasChanges = JSON.stringify(settings) !== JSON.stringify(original);
  const rivalryHasChanges = JSON.stringify(rivalrySettings) !== JSON.stringify(rivalryOriginal);
  const isConference = league?.league_type === "conference";

  if (loading) {
    return (
      <div className="min-h-screen bg-surface-900 flex items-center justify-center">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 border-2 border-gold-400 border-t-transparent rounded-full animate-spin" />
          <span className="text-surface-400">Loading playoff settings...</span>
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
                <Trophy className="w-4 h-4 text-gold-400" />
                Playoff Settings
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
                  <h3 id="enable-playoffs-label" className="text-white font-bold text-sm">Enable Playoffs</h3>
                  <p className="text-surface-400 text-xs mt-1">
                    Off by default. Once on, a bracket is generated and advanced automatically --
                    no manual step needed once the regular season ends.
                  </p>
                </div>
                <button
                  onClick={() => update("enabled", !settings.enabled)}
                  role="switch"
                  aria-checked={settings.enabled}
                  aria-labelledby="enable-playoffs-label"
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
                  <h3 className="text-white font-bold text-sm">Bracket Setup</h3>
                </div>
                <div className="divide-y divide-surface-700/50">
                  <div className="flex items-center justify-between px-5 py-3">
                    <div>
                      <label className="text-sm text-surface-300">Regular Season Length</label>
                      <p className="text-xs text-surface-500">Playoffs start the week after this one.</p>
                    </div>
                    <div className="flex items-center gap-2">
                      <input
                        type="number"
                        min={1}
                        max={17}
                        value={settings.regular_season_weeks}
                        onChange={(e) => update("regular_season_weeks", parseInt(e.target.value, 10) || 1)}
                        className="w-20 px-2.5 py-1.5 bg-surface-900 border border-surface-600 rounded-lg text-white text-sm text-right focus:outline-none focus:ring-1 focus:ring-gold-400 font-mono"
                      />
                      <span className="text-xs text-surface-500">weeks</span>
                    </div>
                  </div>
                  <div className="flex items-center justify-between px-5 py-3">
                    <div>
                      <label className="text-sm text-surface-300">
                        {isConference && settings.conference_bracket_mode === "separate" ? "Teams Per Conference" : "Teams In Bracket"}
                      </label>
                      <p className="text-xs text-surface-500">Byes go to the top seeds if this isn&apos;t a power of 2.</p>
                    </div>
                    <input
                      type="number"
                      min={2}
                      value={settings.num_teams}
                      onChange={(e) => update("num_teams", parseInt(e.target.value, 10) || 2)}
                      className="w-20 px-2.5 py-1.5 bg-surface-900 border border-surface-600 rounded-lg text-white text-sm text-right focus:outline-none focus:ring-1 focus:ring-gold-400 font-mono"
                    />
                  </div>
                </div>
              </div>

              <div className="bg-surface-800/60 border border-surface-700 rounded-2xl overflow-hidden">
                <div className="px-5 py-3.5 bg-surface-800 border-b border-surface-700">
                  <h3 className="text-white font-bold text-sm">Seeding Method</h3>
                </div>
                <div className="p-4 flex gap-3">
                  {(["wins", "points"] as const).map((method) => (
                    <button
                      key={method}
                      onClick={() => update("seeding_method", method)}
                      aria-pressed={settings.seeding_method === method}
                      className={`flex-1 text-left p-3 rounded-xl border transition-all ${
                        settings.seeding_method === method
                          ? "bg-gold-400/10 border-gold-400/40 text-gold-400"
                          : "bg-surface-900 border-surface-700 text-surface-300 hover:border-surface-600"
                      }`}
                    >
                      <p className="font-semibold text-sm">{method === "wins" ? "Most Wins" : "Top Scorers"}</p>
                      <p className="text-xs opacity-80 mt-0.5">
                        {method === "wins" ? "Standard win/loss record (points_for breaks ties)." : "Total points scored all season, regardless of record."}
                      </p>
                    </button>
                  ))}
                </div>
              </div>

              {isConference && (
                <div className="bg-surface-800/60 border border-surface-700 rounded-2xl overflow-hidden">
                  <div className="px-5 py-3.5 bg-surface-800 border-b border-surface-700">
                    <h3 className="text-white font-bold text-sm">Conference Bracket</h3>
                  </div>
                  <div className="p-4 flex gap-3">
                    {(["combined", "separate"] as const).map((mode) => (
                      <button
                        key={mode}
                        onClick={() => update("conference_bracket_mode", mode)}
                        aria-pressed={settings.conference_bracket_mode === mode}
                        className={`flex-1 text-left p-3 rounded-xl border transition-all ${
                          settings.conference_bracket_mode === mode
                            ? "bg-gold-400/10 border-gold-400/40 text-gold-400"
                            : "bg-surface-900 border-surface-700 text-surface-300 hover:border-surface-600"
                        }`}
                      >
                        <p className="font-semibold text-sm">{mode === "combined" ? "Combined" : "Separate"}</p>
                        <p className="text-xs opacity-80 mt-0.5">
                          {mode === "combined"
                            ? "One league-wide bracket, seeded across both conferences."
                            : "Two independent brackets, one per conference, each with its own champion."}
                        </p>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Rivalry Week -- deliberately OUTSIDE the opacity-gated
                block above: it's a regular-season scoring bonus, not a
                playoff feature, so it stays fully usable/visible whether
                or not playoffs are enabled at all. Own local state, own
                small save action, since it's backed by a separate API
                resource (rivalry-week-settings) from playoff_settings. */}
            {isConference && rivalrySettings && (
              <div className="bg-surface-800/60 border border-surface-700 rounded-2xl overflow-hidden">
                <div className="px-5 py-3.5 bg-surface-800 border-b border-surface-700 flex items-center justify-between">
                  <h3 className="text-white font-bold text-sm flex items-center gap-2">
                    <Swords className="w-4 h-4 text-gold-400" />
                    Rivalry Week
                  </h3>
                  <button
                    onClick={handleSaveRivalry}
                    disabled={rivalrySaving || !rivalryHasChanges}
                    className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                      rivalrySaved ? "bg-green-500 text-white" : "bg-gold-400 hover:bg-gold-300 text-surface-900 disabled:opacity-40 disabled:cursor-not-allowed"
                    }`}
                  >
                    {rivalrySaving ? (
                      <><Loader2 className="w-3 h-3 animate-spin" /> Saving...</>
                    ) : rivalrySaved ? (
                      <><RefreshCw className="w-3 h-3" /> Saved!</>
                    ) : (
                      <><Save className="w-3 h-3" /> Save</>
                    )}
                  </button>
                </div>
                <div className="p-4 space-y-3">
                  <p className="text-surface-400 text-xs">
                    Every team that wins its matchup in the designated week gets a
                    bonus, on top of any coach win bonus. Only affects the week you
                    pick -- no schedule changes.
                  </p>
                  {rivalryError && (
                    <div className="p-2 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-xs" role="alert">{rivalryError}</div>
                  )}
                  <div className="flex items-center justify-between">
                    <label id="enable-rivalry-label" className="text-sm text-surface-300">Enable Rivalry Week</label>
                    <button
                      onClick={() => updateRivalry("enabled", !rivalrySettings.enabled)}
                      role="switch"
                      aria-checked={rivalrySettings.enabled}
                      aria-labelledby="enable-rivalry-label"
                      className={`shrink-0 relative w-11 h-6 rounded-full transition-colors ${rivalrySettings.enabled ? "bg-gold-400" : "bg-surface-700"}`}
                    >
                      <span
                        className={`absolute top-1 w-4 h-4 rounded-full bg-white transition-transform ${rivalrySettings.enabled ? "translate-x-6" : "translate-x-1"}`}
                      />
                    </button>
                  </div>
                  <div className={`flex items-center gap-3 transition-opacity ${rivalrySettings.enabled ? "" : "opacity-40 pointer-events-none"}`}>
                    <div>
                      <label className="text-[10px] text-surface-500 uppercase tracking-wider block mb-1">Week</label>
                      <input
                        type="number"
                        min={1}
                        value={rivalrySettings.week ?? ""}
                        onChange={(e) => updateRivalry("week", e.target.value ? parseInt(e.target.value, 10) : null)}
                        className="w-20 px-2.5 py-1.5 bg-surface-900 border border-surface-600 rounded-lg text-white text-sm text-right focus:outline-none focus:ring-1 focus:ring-gold-400 font-mono"
                      />
                    </div>
                    <div>
                      <label className="text-[10px] text-surface-500 uppercase tracking-wider block mb-1">Bonus Points</label>
                      <input
                        type="number"
                        step="0.1"
                        min={0}
                        value={rivalrySettings.bonus_value}
                        onChange={(e) => updateRivalry("bonus_value", parseFloat(e.target.value) || 0)}
                        className="w-24 px-2.5 py-1.5 bg-surface-900 border border-surface-600 rounded-lg text-white text-sm text-right focus:outline-none focus:ring-1 focus:ring-gold-400 font-mono"
                      />
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
