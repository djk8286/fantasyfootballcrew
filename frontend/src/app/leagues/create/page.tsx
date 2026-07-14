"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { leaguesApi, teamsApi, playersApi } from "@/lib/api-client";

const leagueTypes = [
  { value: "standard", label: "Standard", desc: "Classic 1-vs-1 head-to-head" },
  { value: "two_man", label: "2-Man Teams", desc: "Co-managed franchises" },
  { value: "conference", label: "Conference", desc: "6v6 conference battle" },
] as const;

const draftTypes = [
  { value: "snake", label: "Snake Draft", desc: "Standard serpentine order" },
  { value: "auction", label: "Auction Draft", desc: "Budget-based bidding" },
] as const;

export default function CreateLeaguePage() {
  const router = useRouter();
  const [form, setForm] = useState({
    name: "",
    description: "",
    league_type: "standard",
    max_teams: 12,
    draft_type: "snake",
    team_name: "",
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleChange = (
    e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>
  ) => {
    const { name, value } = e.target;
    setForm((prev) => ({
      ...prev,
      [name]: name === "max_teams" ? parseInt(value) || 12 : value,
    }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const league = await leaguesApi.create({
        name: form.name,
        description: form.description || undefined,
        league_type: form.league_type,
        max_teams: form.max_teams,
        draft_type: form.draft_type,
        scoring_config: {},
      }) as { id: string; name: string };

      // Create the commissioner's team
      const teamName = form.team_name.trim() || `${form.name} Team`;
      const team = await teamsApi.create({
        name: teamName,
        league_id: league.id,
      }) as { id: string };

      // Save team ID so draft page knows which team is yours
      if (typeof window !== "undefined") {
        const userTeams = JSON.parse(localStorage.getItem("ffc_user_teams") || "{}");
        userTeams[league.id] = team.id;
        localStorage.setItem("ffc_user_teams", JSON.stringify(userTeams));
      }

      // Auto-fill remaining slots with CPU teams (ready to draft immediately)
      if (form.max_teams > 1) {
        try {
          await teamsApi.bulkAddCpu(league.id, form.max_teams - 1, `${form.name} Team`);
        } catch {
          // Non-fatal — user can add teams manually from the league page
        }
      }

      router.push(`/leagues/${league.id}`);
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Failed to create league";
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-surface-900">
      {/* Header */}
      <section className="relative overflow-hidden border-b border-surface-700">
        <div className="absolute inset-0 bg-gradient-to-b from-surface-850 via-surface-900 to-surface-900" />
        <div className="relative max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-1 text-surface-400 hover:text-gold-400 transition-colors text-sm mb-6"
          >
            ← Back to Dashboard
          </Link>
          <h1 className="text-3xl md:text-4xl font-bold text-white tracking-tight">
            Create League
          </h1>
          <p className="text-surface-400 mt-2">
            Set up your league&apos;s rules, teams, and draft format.
          </p>
        </div>
      </section>

      {/* Form */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
        <div className="bg-surface-800 border border-surface-700 rounded-2xl p-8">
          {error && (
            <div className="mb-6 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-8">
            {/* League Name */}
            <div>
              <label htmlFor="name" className="block text-sm font-medium text-surface-300 mb-1.5">
                League Name <span className="text-red-400">*</span>
              </label>
              <input
                id="name"
                name="name"
                type="text"
                required
                placeholder="e.g. Champions League"
                value={form.name}
                onChange={handleChange}
                maxLength={60}
                className="w-full px-4 py-2.5 bg-surface-900 border border-surface-600 rounded-lg text-white placeholder-surface-500 focus:outline-none focus:ring-2 focus:ring-gold-400 focus:border-transparent transition-all"
              />
            </div>

            {/* Description */}
            <div>
              <label htmlFor="description" className="block text-sm font-medium text-surface-300 mb-1.5">
                Description
              </label>
              <textarea
                id="description"
                name="description"
                rows={3}
                placeholder="Tell your league-mates what this league is all about..."
                value={form.description}
                onChange={handleChange}
                maxLength={500}
                className="w-full px-4 py-2.5 bg-surface-900 border border-surface-600 rounded-lg text-white placeholder-surface-500 focus:outline-none focus:ring-2 focus:ring-gold-400 focus:border-transparent transition-all resize-none"
              />
              <p className="text-surface-500 text-xs mt-1 text-right">
                {form.description.length}/500
              </p>
            </div>

            {/* Team Name */}
            <div>
              <label htmlFor="team_name" className="block text-sm font-medium text-surface-300 mb-1.5">
                Your Team Name <span className="text-surface-500">(optional)</span>
              </label>
              <input
                id="team_name"
                name="team_name"
                type="text"
                placeholder={`${form.name || "My League"} Team`}
                value={form.team_name}
                onChange={handleChange}
                maxLength={60}
                className="w-full px-4 py-2.5 bg-surface-900 border border-surface-600 rounded-lg text-white placeholder-surface-500 focus:outline-none focus:ring-2 focus:ring-gold-400 focus:border-transparent transition-all"
              />
              <p className="text-surface-500 text-xs mt-1">
                Your first team will be created automatically.
              </p>
            </div>

            {/* League Type */}
            <div>
              <label className="block text-sm font-medium text-surface-300 mb-3">
                League Type <span className="text-red-400">*</span>
              </label>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                {leagueTypes.map((lt) => (
                  <button
                    key={lt.value}
                    type="button"
                    onClick={() => setForm((prev) => ({ ...prev, league_type: lt.value }))}
                    className={`text-left p-4 rounded-xl border transition-all ${
                      form.league_type === lt.value
                        ? "bg-gold-400/10 border-gold-400/40 ring-1 ring-gold-400/30"
                        : "bg-surface-900 border-surface-600 hover:border-surface-500"
                    }`}
                  >
                    <p className={`font-semibold text-sm ${
                      form.league_type === lt.value ? "text-gold-400" : "text-white"
                    }`}>
                      {lt.label}
                    </p>
                    <p className="text-surface-400 text-xs mt-1">{lt.desc}</p>
                  </button>
                ))}
              </div>
            </div>

            {/* Team Count */}
            <div>
              <label className="block text-sm font-medium text-surface-300 mb-3">
                Number of Teams <span className="text-red-400">*</span>
              </label>
              <input
                type="range"
                name="max_teams"
                min={4}
                max={32}
                step={2}
                value={form.max_teams}
                onChange={handleChange}
                className="w-full accent-gold-400"
              />
              <div className="flex justify-between text-xs text-surface-500 mt-1">
                <span>4</span>
                <span>32</span>
              </div>
              <p className="text-center text-gold-400 font-semibold mt-2 text-lg">
                {form.max_teams} teams
              </p>
            </div>

            {/* Draft Type */}
            <div>
              <label className="block text-sm font-medium text-surface-300 mb-3">
                Draft Type <span className="text-red-400">*</span>
              </label>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {draftTypes.map((dt) => (
                  <button
                    key={dt.value}
                    type="button"
                    onClick={() => setForm((prev) => ({ ...prev, draft_type: dt.value }))}
                    className={`text-left p-4 rounded-xl border transition-all ${
                      form.draft_type === dt.value
                        ? "bg-gold-400/10 border-gold-400/40 ring-1 ring-gold-400/30"
                        : "bg-surface-900 border-surface-600 hover:border-surface-500"
                    }`}
                  >
                    <p className={`font-semibold text-sm ${
                      form.draft_type === dt.value ? "text-gold-400" : "text-white"
                    }`}>
                      {dt.label}
                    </p>
                    <p className="text-surface-400 text-xs mt-1">{dt.desc}</p>
                  </button>
                ))}
              </div>
            </div>

            {/* Submit */}
            <div className="flex items-center gap-4 pt-2">
              <Link
                href="/dashboard"
                className="px-6 py-2.5 border border-surface-600 rounded-lg text-surface-300 hover:text-white hover:border-surface-500 transition-all text-sm font-medium"
              >
                Cancel
              </Link>
              <button
                type="submit"
                disabled={loading || !form.name.trim()}
                className="flex-1 bg-gold-400 hover:bg-gold-300 text-surface-900 font-bold py-2.5 rounded-lg transition-all hover:shadow-xl hover:shadow-gold-400/30 disabled:opacity-50 disabled:cursor-not-allowed text-sm"
              >
                {loading ? "Creating League..." : "Create League"}
              </button>
            </div>
          </form>
        </div>
      </section>
    </div>
  );
}
