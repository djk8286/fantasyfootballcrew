"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Sparkles } from "lucide-react";
import { draftsApi, isLoggedIn } from "@/lib/api-client";

export default function MockDraftPage() {
  const router = useRouter();
  const [loggedIn, setLoggedIn] = useState<boolean | null>(null);
  const [numTeams, setNumTeams] = useState(10);
  const [totalRounds, setTotalRounds] = useState(15);
  const [draftPosition, setDraftPosition] = useState<string>("random");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoggedIn(isLoggedIn());
  }, []);

  // Clamp a chosen slot down if the team count shrinks below it.
  useEffect(() => {
    if (draftPosition !== "random" && parseInt(draftPosition) > numTeams) {
      setDraftPosition("random");
    }
  }, [numTeams, draftPosition]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const position = draftPosition === "random" ? undefined : parseInt(draftPosition);
      const result = (await draftsApi.quickstartMock(numTeams, totalRounds, position)) as {
        draft_id: string;
      };
      router.push(`/draft/${result.draft_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start mock draft");
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-surface-900">
      <section className="relative overflow-hidden border-b border-surface-700">
        <div className="absolute inset-0 bg-gradient-to-b from-surface-850 via-surface-900 to-surface-900" />
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[700px] h-[400px] bg-gold-400/5 rounded-full blur-3xl" />
        <div className="relative max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-1 text-surface-400 hover:text-gold-400 transition-colors text-sm mb-6"
          >
            ← Back to Dashboard
          </Link>
          <h1 className="text-3xl md:text-4xl font-bold text-white tracking-tight flex items-center gap-3">
            <Sparkles className="w-8 h-8 text-gold-400" />
            Mock Draft
          </h1>
          <p className="text-surface-400 mt-2">
            Practice against AI-controlled teams — no league to set up, nobody to invite. Pick your
            slot, hit start, and you&apos;re on the clock.
          </p>
        </div>
      </section>

      <section className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
        <div className="bg-surface-800 border border-surface-700 rounded-2xl p-8">
          {loggedIn === false ? (
            <div className="text-center py-6">
              <p className="text-surface-300 text-sm mb-4">Log in to start a mock draft.</p>
              <Link
                href="/login"
                className="inline-flex items-center gap-2 bg-gold-400 hover:bg-gold-300 text-surface-900 px-6 py-2.5 rounded-xl font-bold text-sm transition-all"
              >
                Log In
              </Link>
            </div>
          ) : (
            <>
              {error && (
                <div className="mb-6 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm">
                  {error}
                </div>
              )}

              <form onSubmit={handleSubmit} className="space-y-8">
                {/* Number of Teams */}
                <div>
                  <label className="block text-sm font-medium text-surface-300 mb-3">
                    Number of Teams
                  </label>
                  <input
                    type="range"
                    min={4}
                    max={20}
                    step={1}
                    value={numTeams}
                    onChange={(e) => setNumTeams(parseInt(e.target.value))}
                    className="w-full accent-gold-400"
                  />
                  <div className="flex justify-between text-xs text-surface-500 mt-1">
                    <span>4</span>
                    <span>20</span>
                  </div>
                  <p className="text-center text-gold-400 font-semibold mt-2 text-lg">
                    {numTeams} teams
                  </p>
                </div>

                {/* Rounds */}
                <div>
                  <label className="block text-sm font-medium text-surface-300 mb-3">Rounds</label>
                  <input
                    type="range"
                    min={1}
                    max={20}
                    step={1}
                    value={totalRounds}
                    onChange={(e) => setTotalRounds(parseInt(e.target.value))}
                    className="w-full accent-gold-400"
                  />
                  <div className="flex justify-between text-xs text-surface-500 mt-1">
                    <span>1</span>
                    <span>20</span>
                  </div>
                  <p className="text-center text-gold-400 font-semibold mt-2 text-lg">
                    {totalRounds} rounds
                  </p>
                </div>

                {/* Draft Position */}
                <div>
                  <label htmlFor="position" className="block text-sm font-medium text-surface-300 mb-1.5">
                    Your Draft Slot
                  </label>
                  <select
                    id="position"
                    value={draftPosition}
                    onChange={(e) => setDraftPosition(e.target.value)}
                    className="w-full px-4 py-2.5 bg-surface-900 border border-surface-600 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-gold-400 focus:border-transparent transition-all"
                  >
                    <option value="random">Random</option>
                    {Array.from({ length: numTeams }, (_, i) => i + 1).map((slot) => (
                      <option key={slot} value={slot}>
                        Pick {slot}
                      </option>
                    ))}
                  </select>
                </div>

                <button
                  type="submit"
                  disabled={loading || loggedIn === null}
                  className="w-full bg-gold-400 hover:bg-gold-300 text-surface-900 font-bold py-3 rounded-lg transition-all hover:shadow-xl hover:shadow-gold-400/30 disabled:opacity-50 disabled:cursor-not-allowed text-sm"
                >
                  {loading ? "Setting Up Draft Room..." : "Start Mock Draft"}
                </button>
              </form>
            </>
          )}
        </div>
      </section>
    </div>
  );
}
