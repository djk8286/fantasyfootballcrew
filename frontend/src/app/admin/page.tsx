"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { adminApi } from "@/lib/api-client";
import { ArrowLeft, Users, Trophy, Shield, ListChecks, Crown, Bot, Mail, AlertTriangle } from "lucide-react";

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

interface AiUsage {
  total: number;
  last_24h: number;
  by_endpoint: { endpoint: string; count: number }[];
  by_league: { league_id: string; league_name: string; count: number }[];
  // Per-user breakdown (2026-09-09) -- lineup/trade/bet analysis calls
  // previously made real LLM calls with NO usage record at all, and
  // aren't tied to a league the way by_league needs (bet analysis is
  // freeform, not league-scoped) -- this is what actually surfaces them.
  by_user: { user_id: string; username: string; count: number }[];
}

interface LeagueHealthRow {
  id: string;
  name: string;
  commissioner_username: string | null;
  commissioner_email: string | null;
  draft_status: string;
  team_count: number;
  created_at: string;
  flags: string[];
}

interface EmailLogRow {
  id: string;
  to_email: string;
  email_type: string;
  subject: string;
  status: string;
  error_detail: string | null;
  created_at: string;
}

type Tab = "leagues" | "users" | "ai-usage" | "health" | "email-log";

const FLAG_LABELS: Record<string, string> = {
  no_teams: "No teams",
  never_started: "Never started",
  stuck_draft: "Stuck draft",
};

const STATUS_COLOR: Record<string, string> = {
  sent: "text-green-400",
  failed: "text-red-400",
  stubbed: "text-surface-500",
};

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function fmtDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
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
  const [aiUsage, setAiUsage] = useState<AiUsage | null>(null);
  const [leagueHealth, setLeagueHealth] = useState<LeagueHealthRow[]>([]);
  const [emailLog, setEmailLog] = useState<EmailLogRow[]>([]);
  const [emailStatusFilter, setEmailStatusFilter] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("leagues");

  useEffect(() => {
    Promise.all([
      adminApi.getStats(), adminApi.getUsers(), adminApi.getLeagues(),
      adminApi.getAiUsage(), adminApi.getLeagueHealth(), adminApi.getEmailLog(),
    ])
      .then(([s, u, l, ai, health, emails]) => {
        setStats(s as Stats);
        setUsers(u as AdminUser[]);
        setLeagues(l as AdminLeague[]);
        setAiUsage(ai as AiUsage);
        setLeagueHealth(health as LeagueHealthRow[]);
        setEmailLog(emails as EmailLogRow[]);
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

  const loadEmailLog = useCallback((status: string) => {
    adminApi.getEmailLog(status || undefined)
      .then((data) => setEmailLog(data as EmailLogRow[]))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!loading) loadEmailLog(emailStatusFilter);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [emailStatusFilter]);

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

        <div className="flex items-center gap-1 p-1 bg-surface-800 border border-surface-700 rounded-lg w-fit overflow-x-auto">
          {([
            ["leagues", `Leagues (${leagues.length})`],
            ["users", `Users (${users.length})`],
            ["ai-usage", "AI Usage"],
            ["health", `League Health${leagueHealth.length ? ` (${leagueHealth.length})` : ""}`],
            ["email-log", "Email Log"],
          ] as [Tab, string][]).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`shrink-0 px-3.5 py-1.5 rounded-md text-xs font-bold transition-colors ${
                tab === key ? "bg-gold-400 text-surface-900" : "text-surface-400 hover:text-white"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {tab === "leagues" && (
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
        )}

        {tab === "users" && (
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

        {tab === "ai-usage" && (
          <div className="space-y-4">
            {aiUsage && (
              <div className="grid grid-cols-2 gap-3">
                <StatTile icon={<Bot className="w-4.5 h-4.5" />} label="Total AI Calls" value={aiUsage.total} />
                <StatTile icon={<Bot className="w-4.5 h-4.5" />} label="Last 24h" value={aiUsage.last_24h} />
              </div>
            )}
            <p className="text-surface-500 text-xs">
              Call counts only -- not dollars. Every real LLM call logs one row here -- AI Co-Commissioner features (digest, trade review, chat, message drafts, recaps) as well as the personal tools (lineup analysis, trade analysis, bet analysis).
            </p>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="bg-surface-800/60 border border-surface-700 rounded-2xl overflow-hidden">
                <div className="px-4 py-3 bg-surface-800 border-b border-surface-700">
                  <h3 className="text-white font-bold text-sm">By Feature</h3>
                </div>
                <table className="w-full text-sm">
                  <tbody className="divide-y divide-surface-700/60">
                    {(aiUsage?.by_endpoint.length ?? 0) === 0 ? (
                      <tr><td className="px-4 py-4 text-surface-500 text-center">No AI usage yet.</td></tr>
                    ) : (
                      aiUsage!.by_endpoint.map((row) => (
                        <tr key={row.endpoint}>
                          <td className="px-4 py-2.5 text-surface-300">{row.endpoint.replace(/_/g, " ")}</td>
                          <td className="px-4 py-2.5 text-white font-medium text-right">{row.count.toLocaleString()}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
              <div className="bg-surface-800/60 border border-surface-700 rounded-2xl overflow-hidden">
                <div className="px-4 py-3 bg-surface-800 border-b border-surface-700">
                  <h3 className="text-white font-bold text-sm">Top Leagues</h3>
                </div>
                <table className="w-full text-sm">
                  <tbody className="divide-y divide-surface-700/60">
                    {(aiUsage?.by_league.length ?? 0) === 0 ? (
                      <tr><td className="px-4 py-4 text-surface-500 text-center">No AI usage yet.</td></tr>
                    ) : (
                      aiUsage!.by_league.map((row) => (
                        <tr key={row.league_id}>
                          <td className="px-4 py-2.5 text-surface-300">{row.league_name}</td>
                          <td className="px-4 py-2.5 text-white font-medium text-right">{row.count.toLocaleString()}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
              <div className="bg-surface-800/60 border border-surface-700 rounded-2xl overflow-hidden">
                <div className="px-4 py-3 bg-surface-800 border-b border-surface-700">
                  <h3 className="text-white font-bold text-sm">Top Users</h3>
                </div>
                <table className="w-full text-sm">
                  <tbody className="divide-y divide-surface-700/60">
                    {(aiUsage?.by_user.length ?? 0) === 0 ? (
                      <tr><td className="px-4 py-4 text-surface-500 text-center">No AI usage yet.</td></tr>
                    ) : (
                      aiUsage!.by_user.map((row) => (
                        <tr key={row.user_id}>
                          <td className="px-4 py-2.5 text-surface-300">{row.username}</td>
                          <td className="px-4 py-2.5 text-white font-medium text-right">{row.count.toLocaleString()}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {tab === "health" && (
          <div className="bg-surface-800/60 border border-surface-700 rounded-2xl overflow-hidden overflow-x-auto">
            <table className="w-full text-sm min-w-[640px]">
              <thead>
                <tr className="border-b border-surface-700 text-left text-surface-400 text-xs uppercase tracking-wider">
                  <th className="px-4 py-3 font-medium">League</th>
                  <th className="px-4 py-3 font-medium">Commissioner</th>
                  <th className="px-4 py-3 font-medium">Draft</th>
                  <th className="px-4 py-3 font-medium text-right">Teams</th>
                  <th className="px-4 py-3 font-medium">Flags</th>
                  <th className="px-4 py-3 font-medium">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-700/60">
                {leagueHealth.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-6 text-center text-surface-500">
                      Nothing flagged -- every real league looks healthy.
                    </td>
                  </tr>
                ) : (
                  leagueHealth.map((l) => (
                    <tr key={l.id} className="hover:bg-surface-900/40 transition-colors">
                      <td className="px-4 py-3 text-white font-medium">{l.name}</td>
                      <td className="px-4 py-3 text-surface-300">
                        {l.commissioner_username || "—"}
                        {l.commissioner_email && (
                          <span className="block text-surface-500 text-xs">{l.commissioner_email}</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-surface-400">{l.draft_status.replace("_", " ")}</td>
                      <td className="px-4 py-3 text-surface-300 text-right">{l.team_count}</td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-1">
                          {l.flags.map((f) => (
                            <span key={f} className="inline-flex items-center gap-1 text-[10px] font-semibold text-amber-400 bg-amber-500/10 border border-amber-500/30 px-1.5 py-0.5 rounded">
                              <AlertTriangle className="w-2.5 h-2.5" /> {FLAG_LABELS[f] || f}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-surface-500 text-xs">{fmtDate(l.created_at)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}

        {tab === "email-log" && (
          <div className="space-y-3">
            <div className="flex items-center gap-1.5">
              {["", "sent", "failed", "stubbed"].map((s) => (
                <button
                  key={s || "all"}
                  onClick={() => setEmailStatusFilter(s)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                    emailStatusFilter === s
                      ? "bg-gold-400 text-surface-900"
                      : "bg-surface-900 border border-surface-700 text-surface-400 hover:text-white"
                  }`}
                >
                  {s ? s[0].toUpperCase() + s.slice(1) : "All"}
                </button>
              ))}
            </div>
            <div className="bg-surface-800/60 border border-surface-700 rounded-2xl overflow-hidden overflow-x-auto">
              <table className="w-full text-sm min-w-[720px]">
                <thead>
                  <tr className="border-b border-surface-700 text-left text-surface-400 text-xs uppercase tracking-wider">
                    <th className="px-4 py-3 font-medium">To</th>
                    <th className="px-4 py-3 font-medium">Type</th>
                    <th className="px-4 py-3 font-medium">Subject</th>
                    <th className="px-4 py-3 font-medium">Status</th>
                    <th className="px-4 py-3 font-medium">Sent</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-700/60">
                  {emailLog.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="px-4 py-6 text-center text-surface-500">
                        <Mail className="w-5 h-5 mx-auto mb-2 opacity-40" /> No emails logged.
                      </td>
                    </tr>
                  ) : (
                    emailLog.map((e) => (
                      <tr key={e.id} className="hover:bg-surface-900/40 transition-colors align-top">
                        <td className="px-4 py-3 text-surface-300">{e.to_email}</td>
                        <td className="px-4 py-3 text-surface-400">{e.email_type.replace(/_/g, " ")}</td>
                        <td className="px-4 py-3 text-surface-300">
                          {e.subject}
                          {e.error_detail && (
                            <span className="block text-red-400/80 text-xs mt-0.5 max-w-md truncate" title={e.error_detail}>
                              {e.error_detail}
                            </span>
                          )}
                        </td>
                        <td className={`px-4 py-3 font-semibold text-xs ${STATUS_COLOR[e.status] || "text-surface-400"}`}>
                          {e.status}
                        </td>
                        <td className="px-4 py-3 text-surface-500 text-xs whitespace-nowrap">{fmtDateTime(e.created_at)}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
