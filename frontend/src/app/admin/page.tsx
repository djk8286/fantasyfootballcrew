"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { adminApi } from "@/lib/api-client";
import { ArrowLeft, Users, Trophy, Shield, ListChecks, Crown } from "lucide-react";

interface Stats {
  users: number;
  leagues: number;
  teams: number;
  drafts_in_progress: number;
  draft_picks_made: number;
}

interface AdminUser {
  id: string;
  username: string;
  email: string;
  provider: string;
  email_verified: boolean;
  is_admin: boolean;
  created_at: string;
}

interface AdminLeague {
  id: string;
  name: string;
  commissioner_username: string | null;
  commissioner_email: string | null;
  league_type: string;
  visibility: string;
  draft_status: string;
  team_count: number;
  is_mock: boolean;
  created_at: string;
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function StatTile({ icon, label, value }: { icon: React.ReactNode; label: string; value: number }) {
  return (
    <div className="bg-surface-800/60 border border-surface-700 rounded-xl p-4 flex items-center gap-3">
      <div className="w-9 h-9 rounded-lg bg-gold-400/10 text-gold-400 flex items-center justify-center shrink-0">
        {icon}
      </div>
      <div>
        <p className="text-white text-xl font-bold leading-none">{value.toLocaleString()}</p>
        <p className="text-surface-400 text-xs mt-1">{label}</p>
      </div>
    </div>
  );
}

export default function AdminPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [leagues, setLeagues] = useState<AdminLeague[]>([]);
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<"leagues" | "users">("leagues");

  useEffect(() => {
    Promise.all([adminApi.getStats(), adminApi.getUsers(), adminApi.getLeagues()])
      .then(([s, u, l]) => {
        setStats(s as Stats);
        setUsers(u as AdminUser[]);
        setLeagues(l as AdminLeague[]);
      })
      .catch((err: unknown) => {
        const message = err instanceof Error ? err.message : "Failed to load";
        if (message.includes("403") || message.includes("401")) {
          setForbidden(true);
        } else {
          setError(message);
        }
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen bg-surface-900 flex items-center justify-center">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 border-2 border-gold-400 border-t-transparent rounded-full animate-spin" />
          <span className="text-surface-400">Loading dashboard...</span>
        </div>
      </div>
    );
  }

  if (forbidden) {
    return (
      <div className="min-h-screen bg-surface-900 flex items-center justify-center px-4">
        <div className="text-center max-w-sm">
          <Shield className="w-10 h-10 text-surface-600 mx-auto mb-4" />
          <h1 className="text-white font-bold text-lg mb-2">Admin access required</h1>
          <p className="text-surface-400 text-sm mb-6">
            This dashboard is only visible to accounts with admin access.
          </p>
          <Link href="/dashboard" className="text-gold-400 hover:text-gold-300 font-medium text-sm">
            Back to dashboard
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-surface-900">
      <div className="sticky top-0 z-40 bg-surface-900/95 backdrop-blur-md border-b border-surface-700">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-3 flex items-center gap-3">
          <Link href="/dashboard" aria-label="Back to dashboard" className="text-surface-400 hover:text-white transition-colors shrink-0">
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <Shield className="w-5 h-5 text-gold-400" />
          <h1 className="text-lg font-bold text-white">Admin Dashboard</h1>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
        {error && (
          <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm" role="alert">
            {error}
          </div>
        )}

        {stats && (
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
            <StatTile icon={<Users className="w-4.5 h-4.5" />} label="Users" value={stats.users} />
            <StatTile icon={<Trophy className="w-4.5 h-4.5" />} label="Leagues" value={stats.leagues} />
            <StatTile icon={<Crown className="w-4.5 h-4.5" />} label="Teams" value={stats.teams} />
            <StatTile icon={<ListChecks className="w-4.5 h-4.5" />} label="Drafts In Progress" value={stats.drafts_in_progress} />
            <StatTile icon={<ListChecks className="w-4.5 h-4.5" />} label="Draft Picks Made" value={stats.draft_picks_made} />
          </div>
        )}

        <div className="flex items-center gap-1 p-1 bg-surface-800 border border-surface-700 rounded-lg w-fit">
          <button
            onClick={() => setTab("leagues")}
            className={`px-3.5 py-1.5 rounded-md text-xs font-bold transition-colors ${
              tab === "leagues" ? "bg-gold-400 text-surface-900" : "text-surface-400 hover:text-white"
            }`}
          >
            Leagues ({leagues.length})
          </button>
          <button
            onClick={() => setTab("users")}
            className={`px-3.5 py-1.5 rounded-md text-xs font-bold transition-colors ${
              tab === "users" ? "bg-gold-400 text-surface-900" : "text-surface-400 hover:text-white"
            }`}
          >
            Users ({users.length})
          </button>
        </div>

        {tab === "leagues" ? (
          <div className="bg-surface-800/60 border border-surface-700 rounded-2xl overflow-hidden overflow-x-auto">
            <table className="w-full text-sm min-w-[720px]">
              <thead>
                <tr className="border-b border-surface-700 text-left text-surface-400 text-xs uppercase tracking-wider">
                  <th className="px-4 py-3 font-medium">League</th>
                  <th className="px-4 py-3 font-medium">Commissioner</th>
                  <th className="px-4 py-3 font-medium">Type</th>
                  <th className="px-4 py-3 font-medium">Visibility</th>
                  <th className="px-4 py-3 font-medium">Draft</th>
                  <th className="px-4 py-3 font-medium text-right">Teams</th>
                  <th className="px-4 py-3 font-medium">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-700/60">
                {leagues.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-6 text-center text-surface-500">No leagues.</td>
                  </tr>
                ) : (
                  leagues.map((l) => (
                    <tr key={l.id} className="hover:bg-surface-900/40 transition-colors">
                      <td className="px-4 py-3 text-white font-medium">
                        {l.name}
                        {l.is_mock && (
                          <span className="ml-2 text-[9px] text-surface-500 uppercase tracking-wider bg-surface-700 px-1.5 py-0.5 rounded">Mock</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-surface-300">
                        {l.commissioner_username || "—"}
                        {l.commissioner_email && (
                          <span className="block text-surface-500 text-xs">{l.commissioner_email}</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-surface-400">{l.league_type}</td>
                      <td className="px-4 py-3 text-surface-400">{l.visibility}</td>
                      <td className="px-4 py-3 text-surface-400">{l.draft_status.replace("_", " ")}</td>
                      <td className="px-4 py-3 text-surface-300 text-right">{l.team_count}</td>
                      <td className="px-4 py-3 text-surface-500 text-xs">{fmtDate(l.created_at)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="bg-surface-800/60 border border-surface-700 rounded-2xl overflow-hidden overflow-x-auto">
            <table className="w-full text-sm min-w-[640px]">
              <thead>
                <tr className="border-b border-surface-700 text-left text-surface-400 text-xs uppercase tracking-wider">
                  <th className="px-4 py-3 font-medium">Username</th>
                  <th className="px-4 py-3 font-medium">Email</th>
                  <th className="px-4 py-3 font-medium">Provider</th>
                  <th className="px-4 py-3 font-medium">Verified</th>
                  <th className="px-4 py-3 font-medium">Admin</th>
                  <th className="px-4 py-3 font-medium">Joined</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-700/60">
                {users.map((u) => (
                  <tr key={u.id} className="hover:bg-surface-900/40 transition-colors">
                    <td className="px-4 py-3 text-white font-medium">{u.username}</td>
                    <td className="px-4 py-3 text-surface-300">{u.email}</td>
                    <td className="px-4 py-3 text-surface-400">{u.provider}</td>
                    <td className="px-4 py-3">
                      {u.email_verified ? (
                        <span className="text-green-400 text-xs">Yes</span>
                      ) : (
                        <span className="text-surface-500 text-xs">No</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {u.is_admin && (
                        <span className="inline-flex items-center gap-1 text-gold-400 text-xs font-semibold">
                          <Shield className="w-3 h-3" /> Admin
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-surface-500 text-xs">{fmtDate(u.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
