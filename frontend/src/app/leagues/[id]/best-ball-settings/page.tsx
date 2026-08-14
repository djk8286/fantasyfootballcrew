"use client";

import { useState, useEffect } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { leaguesApi } from "@/lib/api-client";
import { ArrowLeft, Save, Loader2, RefreshCw, Sparkles } from "lucide-react";

interface BestBallSettings {
  enabled: boolean;
  lock_weekday: number;
  lock_hour: number;
  reopen_weekday: number;
  reopen_hour: number;
}

interface ManagementWindow {
  enabled: boolean;
  is_open: boolean;
  next_transition_at: string | null;
  next_transition_type: "opens" | "closes" | null;
}

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const HOURS = Array.from({ length: 24 }, (_, h) => h);

function formatHour(h: number): string {
  const period = h < 12 ? "AM" : "PM";
  const display = h % 12 === 0 ? 12 : h % 12;
  return `${display}:00 ${period} UTC`;
}

export default function BestBallSettingsPage() {
  const params = useParams();
  const id = params.id as string;

  const [league, setLeague] = useState<{ name: string } | null>(null);
  const [settings, setSettings] = useState<BestBallSettings | null>(null);
  const [original, setOriginal] = useState<BestBallSettings | null>(null);
  const [windowStatus, setWindowStatus] = useState<ManagementWindow | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  const load = () => {
    if (!id) return;
    Promise.all([
      leaguesApi.get(id).catch(() => null),
      leaguesApi.getBestBallSettings(id).catch(() => null),
      leaguesApi.getManagementWindow(id).catch(() => null),
    ])
      .then(([leagueData, settingsData, windowData]) => {
        if (leagueData) setLeague(leagueData as { name: string });
        if (settingsData) {
          setSettings(settingsData as BestBallSettings);
          setOriginal(JSON.parse(JSON.stringify(settingsData)));
        } else {
          setError("Failed to load Best-Ball settings");
        }
        if (windowData) setWindowStatus(windowData as ManagementWindow);
      })
      .catch(() => setError("Failed to load Best-Ball settings"))
      .finally(() => setLoading(false));
  };

  useEffect(load, [id]);

  const update = <K extends keyof BestBallSettings>(key: K, value: BestBallSettings[K]) => {
    setSettings((prev) => (prev ? { ...prev, [key]: value } : prev));
    setSaved(false);
  };

  const handleSave = async () => {
    if (!settings || !id) return;
    setSaving(true);
    setError("");
    try {
      await leaguesApi.updateBestBallSettings(id, settings as unknown as Record<string, unknown>);
      setSaved(true);
      setOriginal(JSON.parse(JSON.stringify(settings)));
      setTimeout(() => setSaved(false), 3000);
      leaguesApi.getManagementWindow(id).then((w) => setWindowStatus(w as ManagementWindow)).catch(() => {});
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
          <span className="text-surface-400">Loading Best-Ball settings...</span>
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
                <Sparkles className="w-4 h-4 text-gold-400" />
                Best-Ball Settings
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
                  <h3 id="enable-bb-label" className="text-white font-bold text-sm">Enable Best-Ball</h3>
                  <p className="text-surface-400 text-xs mt-1">
                    Off by default. Once on, every team&apos;s highest-scoring eligible
                    starters are selected automatically each week from real per-week
                    results -- no manual lineup management. Trade approvals and waiver
                    processing are gated by the management window below.
                  </p>
                </div>
                <button
                  onClick={() => update("enabled", !settings.enabled)}
                  role="switch"
                  aria-checked={settings.enabled}
                  aria-labelledby="enable-bb-label"
                  className={`shrink-0 relative w-12 h-7 rounded-full transition-colors ${settings.enabled ? "bg-gold-400" : "bg-surface-700"}`}
                >
                  <span
                    className={`absolute top-1 w-5 h-5 rounded-full bg-white transition-transform ${settings.enabled ? "translate-x-6" : "translate-x-1"}`}
                  />
                </button>
              </div>
            </div>

            {settings.enabled && windowStatus && (
              <div className={`rounded-2xl p-4 border text-sm ${
                windowStatus.is_open
                  ? "bg-green-500/10 border-green-500/30 text-green-300"
                  : "bg-red-500/10 border-red-500/30 text-red-300"
              }`}>
                <span className="font-bold">Management window is currently {windowStatus.is_open ? "OPEN" : "CLOSED"}.</span>
                {windowStatus.next_transition_at && windowStatus.next_transition_type && (
                  <span className="ml-1 opacity-80">
                    It {windowStatus.next_transition_type} at{" "}
                    {new Date(windowStatus.next_transition_at + "Z").toLocaleString(undefined, {
                      weekday: "short", hour: "numeric", minute: "2-digit", timeZoneName: "short",
                    })}.
                  </span>
                )}
              </div>
            )}

            <div className={`space-y-6 transition-opacity ${settings.enabled ? "" : "opacity-40 pointer-events-none"}`}>
              <div className="bg-surface-800/60 border border-surface-700 rounded-2xl overflow-hidden">
                <div className="px-5 py-3.5 bg-surface-800 border-b border-surface-700">
                  <h3 className="text-white font-bold text-sm">Management Window</h3>
                </div>
                <div className="p-4">
                  <p className="text-surface-400 text-xs mb-4">
                    Trade approvals and waiver processing only take effect while the
                    window is open -- claims and trade proposals can still be submitted
                    any time, they just wait to be granted until the window reopens.
                    All times are UTC.
                  </p>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                      <label className="text-[10px] text-surface-500 uppercase tracking-wider block mb-1">Closes (locks)</label>
                      <div className="flex gap-2">
                        <select
                          value={settings.lock_weekday}
                          onChange={(e) => update("lock_weekday", parseInt(e.target.value, 10))}
                          className="flex-1 px-2.5 py-1.5 bg-surface-900 border border-surface-600 rounded-lg text-white text-sm focus:outline-none focus:ring-1 focus:ring-gold-400"
                        >
                          {WEEKDAYS.map((wd, i) => <option key={i} value={i}>{wd}</option>)}
                        </select>
                        <select
                          value={settings.lock_hour}
                          onChange={(e) => update("lock_hour", parseInt(e.target.value, 10))}
                          className="w-32 px-2.5 py-1.5 bg-surface-900 border border-surface-600 rounded-lg text-white text-sm focus:outline-none focus:ring-1 focus:ring-gold-400"
                        >
                          {HOURS.map((h) => <option key={h} value={h}>{formatHour(h)}</option>)}
                        </select>
                      </div>
                    </div>
                    <div>
                      <label className="text-[10px] text-surface-500 uppercase tracking-wider block mb-1">Reopens</label>
                      <div className="flex gap-2">
                        <select
                          value={settings.reopen_weekday}
                          onChange={(e) => update("reopen_weekday", parseInt(e.target.value, 10))}
                          className="flex-1 px-2.5 py-1.5 bg-surface-900 border border-surface-600 rounded-lg text-white text-sm focus:outline-none focus:ring-1 focus:ring-gold-400"
                        >
                          {WEEKDAYS.map((wd, i) => <option key={i} value={i}>{wd}</option>)}
                        </select>
                        <select
                          value={settings.reopen_hour}
                          onChange={(e) => update("reopen_hour", parseInt(e.target.value, 10))}
                          className="w-32 px-2.5 py-1.5 bg-surface-900 border border-surface-600 rounded-lg text-white text-sm focus:outline-none focus:ring-1 focus:ring-gold-400"
                        >
                          {HOURS.map((h) => <option key={h} value={h}>{formatHour(h)}</option>)}
                        </select>
                      </div>
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
