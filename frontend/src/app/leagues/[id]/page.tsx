"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { leaguesApi, teamsApi, draftsApi, isLoggedIn } from "@/lib/api-client";
import { TEAM_AVATARS, AVATAR_URL_PREFIX, getAvatarStyle } from "@/lib/team-avatars";
import {
  Trophy,
  Users,
  Calendar,
  ArrowRight,
  ChevronRight,
  TrendingUp,
  Swords,
  Shield,
  Plus,
  Bot,
  Settings,
  Trash2,
  Crown,
  UserPlus,
  UserMinus,
  UserCheck,
  Pencil,
  X,
  Check,
  RefreshCw,
  ArrowLeftRight,
  ListOrdered,
} from "lucide-react";

// ─── Interfaces ───────────────────────────────────────────────

interface Team {
  id: string;
  name: string;
  owner_id: string | null;
  league_id: string;
  avatar_url: string | null;
  is_cpu: boolean;
  wins: number;
  losses: number;
  ties: number;
  points_for: number;
  points_against: number;
  roster: string[] | null;
}

interface LeagueData {
  id: string;
  name: string;
  description: string | null;
  commissioner_id: string;
  league_type: string;
  max_teams: number;
  team_count: number | null;
  draft_status: string;
  draft_type: string;
  co_commissioner_ids: string[] | null;
  created_at: string;
}

// ─── Avatar Options ──────────────────────────────────────────
// (shared with other pages via @/lib/team-avatars)

// ─── League type helpers ─────────────────────────────────────

const leagueTypeLabels: Record<string, string> = {
  standard: "Standard",
  two_man: "2-Man",
  conference: "Conference",
};

const draftStatusConfig: Record<
  string,
  { label: string; color: string; icon: typeof Calendar }
> = {
  not_started: {
    label: "Not Started",
    color: "bg-yellow-500/15 text-yellow-400 border-yellow-500/25",
    icon: Calendar,
  },
  in_progress: {
    label: "In Progress",
    color: "bg-blue-500/15 text-blue-400 border-blue-500/25",
    icon: TrendingUp,
  },
  completed: {
    label: "Completed",
    color: "bg-green-500/15 text-green-400 border-green-500/25",
    icon: Trophy,
  },
};

const typeIcons: Record<string, typeof Users> = {
  standard: Users,
  two_man: Users,
  conference: Swords,
};

// ─── Component ────────────────────────────────────────────────

export default function LeagueDetailPage() {
  const params = useParams();
  const id = params.id as string;

  const [league, setLeague] = useState<LeagueData | null>(null);
  const [teams, setTeams] = useState<Team[]>([]);
  const [draftId, setDraftId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Avatar picker state
  const [editingAvatarTeam, setEditingAvatarTeam] = useState<string | null>(null);

  // Commissioner panel state
  const [showComPanel, setShowComPanel] = useState(false);

  // League edit state
  const [editingLeague, setEditingLeague] = useState(false);
  const [leagueEditForm, setLeagueEditForm] = useState({ name: "", description: "" });

  // Co-commissioner input
  const [coCommishUserId, setCoCommishUserId] = useState("");

  // Claim team state
  const [claimingTeamId, setClaimingTeamId] = useState<string | null>(null);

  // Delete confirmation
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);

  // Get current "user" from localStorage
  const getCurrentUserId = useCallback(() => {
    if (typeof window === "undefined") return "placeholder";
    // Try to read from a stored user id
    return localStorage.getItem("ffc_user_id") || "placeholder";
  }, []);

  const getMyTeams = useCallback(() => {
    if (typeof window === "undefined") return [] as string[];
    try {
      const stored = JSON.parse(localStorage.getItem("ffc_user_teams") || "{}");
      return stored[id] ? [stored[id]] : [];
    } catch {
      return [];
    }
  }, [id]);

  const isCommissioner = league && getCurrentUserId() === league.commissioner_id;
  const isCoCommissioner = league && league.co_commissioner_ids?.includes(getCurrentUserId());
  const isLeagueManager = isCommissioner || isCoCommissioner;

  // ─── Data fetching ─────────────────────────────────────

  useEffect(() => {
    if (!id) return;

    Promise.all([
      leaguesApi.get(id).catch(() => null),
      teamsApi.getByLeague(id).catch(() => [] as Team[]),
    ])
      .then(([leagueData, teamData]) => {
        if (!leagueData) {
          setError("League not found");
          return;
        }
        const l = leagueData as LeagueData;
        setLeague(l);
        setTeams(Array.isArray(teamData) ? (teamData as Team[]) : []);

        if (l.draft_status !== "not_started") {
          fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001"}/api/v1/drafts/find?league_id=${id}`)
            .then((res) => res.json())
            .then((data) => setDraftId(data.id))
            .catch(() => {});
        }
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Failed to load league");
      })
      .finally(() => setLoading(false));
  }, [id]);

  const refreshTeams = async () => {
    try {
      const data = await teamsApi.getByLeague(id);
      setTeams(Array.isArray(data) ? (data as Team[]) : []);
    } catch {
      // silent
    }
  };

  const refreshLeague = async () => {
    try {
      const data = await leaguesApi.get(id);
      if (data) setLeague(data as LeagueData);
    } catch {
      // silent
    }
  };

  // ─── Actions ─────────────────────────────────────────────

  const handleSetAvatar = async (teamId: string, avatarId: string) => {
    try {
      const url = `${AVATAR_URL_PREFIX}${avatarId}`;
      await teamsApi.update(teamId, { avatar_url: url });
      await refreshTeams();
      setEditingAvatarTeam(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update avatar");
    }
  };

  const handleClaimTeam = async (teamId: string) => {
    setClaimingTeamId(teamId);
    try {
      await teamsApi.claim(teamId);
      // Update localStorage
      const stored = JSON.parse(localStorage.getItem("ffc_user_teams") || "{}");
      stored[id] = teamId;
      localStorage.setItem("ffc_user_teams", JSON.stringify(stored));
      await refreshTeams();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to claim team");
    }
    setClaimingTeamId(null);
  };

  const handleDeleteTeam = async (teamId: string) => {
    try {
      await teamsApi.delete(teamId);
      setDeleteConfirmId(null);
      await refreshTeams();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete team");
    }
  };

  const handleFillCpuAll = async () => {
    if (!league) return;
    setLoading(true);
    try {
      const slotsLeft = league.max_teams - teams.length;
      await teamsApi.bulkAddCpu(league.id, slotsLeft);
      await refreshTeams();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add CPU teams");
    }
    setLoading(false);
  };

  const handleAddOneCpu = async () => {
    if (!league) return;
    setLoading(true);
    try {
      await teamsApi.bulkAddCpu(league.id, 1, league.name + " Team");
      await refreshTeams();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add team");
    }
    setLoading(false);
  };

  const handleSaveLeagueSettings = async () => {
    if (!league) return;
    try {
      await leaguesApi.update(league.id, {
        name: leagueEditForm.name,
        description: leagueEditForm.description || null,
      });
      await refreshLeague();
      setEditingLeague(false);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update league");
    }
  };

  const handleAddCoCommish = async () => {
    if (!league || !coCommishUserId.trim()) return;
    try {
      await leaguesApi.manageCommissioner(league.id, "add_co_commish", coCommishUserId.trim());
      await refreshLeague();
      setCoCommishUserId("");
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add co-commissioner");
    }
  };

  const handleRemoveCoCommish = async (userId: string) => {
    if (!league) return;
    try {
      await leaguesApi.manageCommissioner(league.id, "remove_co_commish", userId);
      await refreshLeague();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove co-commissioner");
    }
  };

  const handleTransferCommissioner = async (userId: string) => {
    if (!league) return;
    try {
      await leaguesApi.manageCommissioner(league.id, "transfer", userId);
      await refreshLeague();
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to transfer commissioner");
    }
  };

  // ─── Avatar Picker Modal ────────────────────────────────

  function AvatarPicker({ teamId, currentUrl, onClose }: { teamId: string; currentUrl: string | null; onClose: () => void }) {
    const currentId = currentUrl?.replace(AVATAR_URL_PREFIX, "") || "";

    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
        <div className="bg-surface-800 border border-surface-700 rounded-2xl p-6 max-w-lg w-full mx-4 shadow-2xl">
          <div className="flex items-center justify-between mb-5">
            <h3 className="text-lg font-semibold text-white">Choose Team Avatar</h3>
            <button onClick={onClose} className="text-surface-400 hover:text-white transition-colors">
              <X className="w-5 h-5" />
            </button>
          </div>
          <div className="grid grid-cols-5 gap-3">
            {TEAM_AVATARS.map((av) => (
              <button
                key={av.id}
                onClick={() => handleSetAvatar(teamId, av.id)}
                className={`w-full aspect-square rounded-xl flex items-center justify-center text-2xl transition-all hover:scale-110 hover:shadow-lg ${
                  currentId === av.id
                    ? "ring-2 ring-gold-400 ring-offset-2 ring-offset-surface-800 scale-110"
                    : "border border-surface-600 hover:border-gold-400/50"
                }`}
                style={{ backgroundColor: av.bg }}
                title={av.label}
              >
                {av.icon}
              </button>
            ))}
          </div>
          {currentUrl && (
            <button
              onClick={() => handleSetAvatar(teamId, "")}
              className="mt-4 w-full text-sm text-surface-400 hover:text-red-400 transition-colors"
            >
              Remove avatar
            </button>
          )}
        </div>
      </div>
    );
  }

  // ─── Helper: team owner display ─────────────────────────

  function getOwnerDisplay(team: Team): { label: string; isHuman: boolean; isMe: boolean; isCommish: boolean } {
    const currentUserId = getCurrentUserId();
    const isCpu = team.is_cpu || team.owner_id === "cpu";
    const isMe = team.owner_id === currentUserId || (team.owner_id === "placeholder" && getMyTeams().includes(team.id));
    const isCommishFlag = isCommissioner && team.owner_id === league?.commissioner_id;

    if (isCpu) return { label: "CPU", isHuman: false, isMe: false, isCommish: false };
    if (team.owner_id === "placeholder") return { label: "Unclaimed", isHuman: false, isMe: false, isCommish: false };
    if (isMe) return { label: "You", isHuman: true, isMe: true, isCommish: false };
    if (isCommishFlag) return { label: "Commish", isHuman: true, isMe: false, isCommish: true };
    return { label: "Joined", isHuman: true, isMe: false, isCommish: false };
  }

  // ─── Render ──────────────────────────────────────────────

  if (loading) {
    return (
      <div className="min-h-screen bg-surface-900 flex items-center justify-center">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 border-2 border-gold-400 border-t-transparent rounded-full animate-spin" />
          <span className="text-surface-400">Loading league...</span>
        </div>
      </div>
    );
  }

  if (error || !league) {
    return (
      <div className="min-h-screen bg-surface-900 flex items-center justify-center">
        <div className="text-center">
          <h2 className="text-xl font-semibold text-white mb-2">League not found</h2>
          <p className="text-surface-400 text-sm mb-4">{error || "This league doesn't exist."}</p>
          <Link href="/dashboard" className="text-gold-400 hover:text-gold-300 text-sm font-medium">
            Back to Dashboard
          </Link>
        </div>
      </div>
    );
  }

  const sortedTeams = [...teams].sort((a, b) => b.wins - a.wins || a.losses - b.losses);
  const statusConfig = draftStatusConfig[league.draft_status] || draftStatusConfig.not_started;
  const StatusIcon = statusConfig.icon;
  const typeLabel = leagueTypeLabels[league.league_type] || league.league_type;
  const TypeIcon = typeIcons[league.league_type] || Users;
  const myTeamIds = getMyTeams();

  return (
    <div className="min-h-screen bg-surface-900">
      {/* Avatar Picker Overlay */}
      {editingAvatarTeam && (
        <AvatarPicker
          teamId={editingAvatarTeam}
          currentUrl={teams.find((t) => t.id === editingAvatarTeam)?.avatar_url || null}
          onClose={() => setEditingAvatarTeam(null)}
        />
      )}

      {/* Back link */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-6">
        <Link
          href="/dashboard"
          className="inline-flex items-center gap-1 text-surface-400 hover:text-gold-400 transition-colors text-sm"
        >
          <ChevronRight className="w-4 h-4 rotate-180" />
          Back to Dashboard
        </Link>
      </div>

      {/* League Header */}
      <section
        className={`relative overflow-hidden border-b ${
          league.draft_status === "in_progress" ? "border-gold-400/30" : "border-surface-700"
        }`}
      >
        <div className="absolute inset-0 bg-gradient-to-b from-surface-850 via-surface-900 to-surface-900" />
        <div
          className={`absolute top-0 right-0 w-[500px] h-[500px] rounded-full blur-3xl ${
            league.draft_status === "in_progress" ? "bg-gold-400/10" : "bg-gold-400/5"
          }`}
        />

        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 md:py-12">
          <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-8">
            {/* Name + Description */}
            <div className="flex-1 min-w-0">
              {editingLeague ? (
                <div className="space-y-3 max-w-xl">
                  <input
                    type="text"
                    value={leagueEditForm.name}
                    onChange={(e) => setLeagueEditForm((f) => ({ ...f, name: e.target.value }))}
                    className="w-full px-4 py-2.5 bg-surface-900 border border-surface-600 rounded-lg text-white placeholder-surface-500 focus:outline-none focus:ring-2 focus:ring-gold-400 text-xl font-bold"
                    placeholder="League name"
                  />
                  <textarea
                    value={leagueEditForm.description}
                    onChange={(e) => setLeagueEditForm((f) => ({ ...f, description: e.target.value }))}
                    className="w-full px-4 py-2.5 bg-surface-900 border border-surface-600 rounded-lg text-white placeholder-surface-500 focus:outline-none focus:ring-2 focus:ring-gold-400 text-sm resize-none"
                    rows={2}
                    placeholder="Description (optional)"
                  />
                  <div className="flex gap-2">
                    <button
                      onClick={handleSaveLeagueSettings}
                      className="inline-flex items-center gap-1.5 bg-gold-400 hover:bg-gold-300 text-surface-900 px-4 py-2 rounded-lg font-semibold text-xs transition-all"
                    >
                      <Check className="w-3.5 h-3.5" />
                      Save
                    </button>
                    <button
                      onClick={() => setEditingLeague(false)}
                      className="inline-flex items-center gap-1.5 border border-surface-600 hover:border-surface-500 text-surface-300 px-4 py-2 rounded-lg text-xs transition-all"
                    >
                      <X className="w-3.5 h-3.5" />
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="flex items-center gap-3">
                    <h1 className="text-3xl md:text-4xl font-bold text-white tracking-tight">
                      {league.name}
                    </h1>
                    {isLeagueManager && (
                      <button
                        onClick={() => {
                          setLeagueEditForm({ name: league.name, description: league.description || "" });
                          setEditingLeague(true);
                        }}
                        className="text-surface-500 hover:text-gold-400 transition-colors"
                        title="Edit league settings"
                      >
                        <Pencil className="w-4 h-4" />
                      </button>
                    )}
                  </div>
                  {league.description && (
                    <p className="text-surface-400 text-sm md:text-base leading-relaxed max-w-2xl mt-2">
                      {league.description}
                    </p>
                  )}
                  {teams.length > 0 && (
                    <div className="flex items-center gap-1.5 mt-4">
                      {teams.slice(0, 8).map((team) => {
                        const avatar = getAvatarStyle(team.avatar_url);
                        return (
                          <div
                            key={team.id}
                            className="w-8 h-8 rounded-full flex items-center justify-center text-sm border-2 border-surface-900 shrink-0 -ml-2 first:ml-0"
                            style={{ backgroundColor: avatar.bg }}
                            title={team.name}
                          >
                            {avatar.icon}
                          </div>
                        );
                      })}
                      {teams.length > 8 && (
                        <span className="text-surface-500 text-xs ml-2">
                          +{teams.length - 8} more
                        </span>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>

            {/* Draft + Commissioner Buttons */}
            <div className="shrink-0 flex flex-col sm:flex-row gap-2">
              {isLeagueManager && (
                <Link
                  href={`/leagues/${id}/commissioner`}
                  className="inline-flex items-center gap-2 border border-surface-600 hover:border-gold-400/50 text-surface-300 hover:text-gold-400 px-5 py-3 rounded-xl font-semibold text-sm transition-all"
                >
                  <Shield className="w-4 h-4" />
                  Commissioner
                </Link>
              )}
              <Link
                href={`/leagues/${id}/scoring`}
                className="inline-flex items-center gap-2 border border-surface-600 hover:border-gold-400/50 text-surface-300 hover:text-gold-400 px-5 py-3 rounded-xl font-semibold text-sm transition-all"
              >
                <Settings className="w-4 h-4" />
                Scoring
              </Link>
              <Link
                href={`/leagues/${id}/standings`}
                className="inline-flex items-center gap-2 border border-surface-600 hover:border-gold-400/50 text-surface-300 hover:text-gold-400 px-5 py-3 rounded-xl font-semibold text-sm transition-all"
              >
                <Trophy className="w-4 h-4" />
                Standings
              </Link>
              <Link
                href={`/leagues/${id}/trades`}
                className="inline-flex items-center gap-2 border border-surface-600 hover:border-gold-400/50 text-surface-300 hover:text-gold-400 px-5 py-3 rounded-xl font-semibold text-sm transition-all"
              >
                <ArrowLeftRight className="w-4 h-4" />
                Trades
              </Link>
              <Link
                href={`/leagues/${id}/waivers`}
                className="inline-flex items-center gap-2 border border-surface-600 hover:border-gold-400/50 text-surface-300 hover:text-gold-400 px-5 py-3 rounded-xl font-semibold text-sm transition-all"
              >
                <ListOrdered className="w-4 h-4" />
                Waivers
              </Link>
              {league.draft_status === "not_started" ? (
                <button
                  onClick={async () => {
                    setLoading(true);
                    try {
                      const draftRes = await draftsApi.create(league.id, 15) as { id: string };
                      window.location.href = `/draft/${draftRes.id}`;
                    } catch {
                      setError("Failed to create draft. Make sure your league has at least 2 teams.");
                      setLoading(false);
                    }
                  }}
                  disabled={loading}
                  className="inline-flex items-center gap-2 bg-gold-400 hover:bg-gold-300 text-surface-900 px-6 py-3 rounded-xl font-bold text-sm transition-all hover:shadow-xl hover:shadow-gold-400/30 hover:-translate-y-0.5 active:translate-y-0 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {loading ? "Creating Draft..." : "Start Draft"}
                  <ArrowRight className="w-4 h-4" />
                </button>
              ) : (
                <Link
                  href={`/draft/${draftId || league.id}`}
                  className="inline-flex items-center gap-2 bg-gold-400 hover:bg-gold-300 text-surface-900 px-6 py-3 rounded-xl font-bold text-sm transition-all hover:shadow-xl hover:shadow-gold-400/30 hover:-translate-y-0.5 active:translate-y-0"
                >
                  <Swords className="w-4 h-4" />
                  View Draft
                </Link>
              )}
            </div>
          </div>

          {/* Stats Row */}
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-4 mt-8">
            <div className="bg-surface-800 border border-surface-700 rounded-xl px-5 py-4 flex items-center gap-4">
              <div className="w-10 h-10 rounded-lg bg-gold-400/10 border border-gold-400/20 flex items-center justify-center shrink-0">
                <Users className="w-5 h-5 text-gold-400" />
              </div>
              <div>
                <p className="text-surface-400 text-xs font-medium uppercase tracking-wider">Teams</p>
                <p className="text-white text-lg font-semibold">{teams.length} / {league.max_teams}</p>
              </div>
            </div>
            <div className="bg-surface-800 border border-surface-700 rounded-xl px-5 py-4 flex items-center gap-4">
              <div className="w-10 h-10 rounded-lg bg-gold-400/10 border border-gold-400/20 flex items-center justify-center shrink-0">
                <TypeIcon className="w-5 h-5 text-gold-400" />
              </div>
              <div>
                <p className="text-surface-400 text-xs font-medium uppercase tracking-wider">Type</p>
                <p className="text-white text-lg font-semibold">{typeLabel}</p>
              </div>
            </div>
            <div className="bg-surface-800 border border-surface-700 rounded-xl px-5 py-4 flex items-center gap-4">
              <div className={`w-10 h-10 rounded-lg flex items-center justify-center shrink-0 ${statusConfig.color}`}>
                <StatusIcon className="w-5 h-5" />
              </div>
              <div>
                <p className="text-surface-400 text-xs font-medium uppercase tracking-wider">Draft</p>
                <p className="text-white text-lg font-semibold">{statusConfig.label}</p>
              </div>
            </div>
            <div className="bg-surface-800 border border-surface-700 rounded-xl px-5 py-4 flex items-center gap-4">
              <div className="w-10 h-10 rounded-lg bg-purple-400/10 border border-purple-400/20 flex items-center justify-center shrink-0">
                <Shield className="w-5 h-5 text-purple-400" />
              </div>
              <div>
                <p className="text-surface-400 text-xs font-medium uppercase tracking-wider">Manage</p>
                <p className="text-white text-lg font-semibold">
                  {isLeagueManager ? "Manager" : "Member"}
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Commissioner Panel */}
      {showComPanel && isLeagueManager && (
        <section className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-8">
          <div className="bg-surface-850 border border-surface-700 rounded-2xl p-6">
            <div className="flex items-center gap-3 mb-4">
              <Crown className="w-5 h-5 text-gold-400" />
              <h2 className="text-lg font-bold text-white">Commissioner Controls</h2>
            </div>

            {/* Current managers */}
            <div className="mb-5">
              <h3 className="text-sm font-semibold text-surface-300 mb-2">League Management Team</h3>
              <div className="space-y-2">
                <div className="flex items-center justify-between bg-surface-800 border border-surface-700 rounded-lg px-4 py-2.5">
                  <div className="flex items-center gap-2">
                    <Crown className="w-4 h-4 text-yellow-400" />
                    <span className="text-sm text-white font-medium">{league.commissioner_id}</span>
                    <span className="text-[10px] text-yellow-400 font-semibold uppercase tracking-wider bg-yellow-400/10 px-2 py-0.5 rounded">Owner</span>
                  </div>
                </div>
                {(league.co_commissioner_ids || []).map((coId) => (
                  <div key={coId} className="flex items-center justify-between bg-surface-800 border border-surface-700 rounded-lg px-4 py-2.5">
                    <div className="flex items-center gap-2">
                      <Shield className="w-4 h-4 text-purple-400" />
                      <span className="text-sm text-white">{coId}</span>
                      <span className="text-[10px] text-purple-400 font-semibold uppercase tracking-wider bg-purple-400/10 px-2 py-0.5 rounded">Co</span>
                    </div>
                    {isCommissioner && (
                      <button
                        onClick={() => handleRemoveCoCommish(coId)}
                        className="text-surface-500 hover:text-red-400 transition-colors"
                        title="Remove co-commissioner"
                      >
                        <UserMinus className="w-4 h-4" />
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* Add co-commissioner (owner only) */}
            {isCommissioner && (
              <div className="border-t border-surface-700 pt-4">
                <h3 className="text-sm font-semibold text-surface-300 mb-2">Add Co-Commissioner</h3>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={coCommishUserId}
                    onChange={(e) => setCoCommishUserId(e.target.value)}
                    placeholder="Enter user ID..."
                    className="flex-1 px-4 py-2 bg-surface-900 border border-surface-600 rounded-lg text-white placeholder-surface-500 text-sm focus:outline-none focus:ring-2 focus:ring-gold-400"
                  />
                  <button
                    onClick={handleAddCoCommish}
                    disabled={!coCommishUserId.trim()}
                    className="inline-flex items-center gap-1.5 bg-purple-500 hover:bg-purple-400 text-white px-4 py-2 rounded-lg font-semibold text-sm transition-all disabled:opacity-50"
                  >
                    <UserPlus className="w-4 h-4" />
                    Add
                  </button>
                </div>
                <p className="text-surface-500 text-xs mt-1">Co-commissioners can manage teams but can&apos;t add/remove other commissioners.</p>
              </div>
            )}
          </div>
        </section>
      )}

      {/* Standings Table */}
      <section className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-bold text-white">Standings</h2>
          <span className="text-surface-400 text-xs">{teams.length} teams</span>
        </div>

        {sortedTeams.length > 0 ? (
          <div className="overflow-x-auto rounded-xl border border-surface-700">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-surface-800 border-b border-surface-700">
                  <th className="text-left px-5 py-3.5 text-surface-400 font-medium text-xs uppercase tracking-wider w-12">#</th>
                  <th className="text-left px-5 py-3.5 text-surface-400 font-medium text-xs uppercase tracking-wider">Team</th>
                  <th className="text-left px-5 py-3.5 text-surface-400 font-medium text-xs uppercase tracking-wider">Owner</th>
                  <th className="text-center px-4 py-3.5 text-surface-400 font-medium text-xs uppercase tracking-wider">W</th>
                  <th className="text-center px-4 py-3.5 text-surface-400 font-medium text-xs uppercase tracking-wider">L</th>
                  <th className="text-center px-4 py-3.5 text-surface-400 font-medium text-xs uppercase tracking-wider">T</th>
                  <th className="text-right px-5 py-3.5 text-surface-400 font-medium text-xs uppercase tracking-wider">PF</th>
                  <th className="text-right px-5 py-3.5 text-surface-400 font-medium text-xs uppercase tracking-wider">PA</th>
                  {isLeagueManager && <th className="text-right px-5 py-3.5 text-surface-400 font-medium text-xs uppercase tracking-wider w-16">Actions</th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-700">
                {sortedTeams.map((team, idx) => {
                  const rank = idx + 1;
                  const owner = getOwnerDisplay(team);
                  const avatar = getAvatarStyle(team.avatar_url);
                  const isMyTeam = myTeamIds.includes(team.id);

                  return (
                    <tr
                      key={team.id}
                      className={`transition-colors ${
                        isMyTeam ? "bg-gold-400/5 border-l-2 border-l-gold-400" : "bg-surface-900 hover:bg-surface-800/80"
                      }`}
                    >
                      <td className="px-5 py-4">
                        <span
                          className={`inline-flex items-center justify-center w-7 h-7 rounded-lg text-xs font-bold ${
                            rank <= 3
                              ? "bg-gold-400/10 text-gold-400 border border-gold-400/20"
                              : "bg-surface-800 text-surface-400 border border-surface-700"
                          }`}
                        >
                          {rank}
                        </span>
                      </td>
                      <td className="px-5 py-4">
                        <div className="flex items-center gap-3">
                          {/* Avatar */}
                          <div
                            className="w-9 h-9 rounded-xl flex items-center justify-center text-lg shrink-0 border border-surface-700/50 cursor-pointer hover:opacity-80 transition-opacity"
                            style={{ backgroundColor: avatar.bg }}
                            onClick={() => {
                              if (isMyTeam || isLeagueManager) setEditingAvatarTeam(team.id);
                            }}
                            title={isMyTeam || isLeagueManager ? "Click to change avatar" : team.avatar_url ? team.avatar_url.replace(AVATAR_URL_PREFIX, "") : ""}
                          >
                            {avatar.icon}
                            {(isMyTeam || isLeagueManager) && (
                              <span className="absolute -top-1 -right-1 w-4 h-4 bg-surface-800 border border-surface-600 rounded-full flex items-center justify-center">
                                <Pencil className="w-2.5 h-2.5 text-surface-400" />
                              </span>
                            )}
                          </div>
                          <div>
                            <span className="font-medium text-white">{team.name}</span>
                            {isMyTeam && (
                              <span className="ml-2 text-[10px] text-gold-400 font-semibold uppercase tracking-wider bg-gold-400/10 px-1.5 py-0.5 rounded">Your Team</span>
                            )}
                            <Link
                              href={`/leagues/${id}/standings`}
                              className="ml-2 text-[10px] text-surface-500 hover:text-gold-400 transition-colors font-medium"
                            >
                              Standings →
                            </Link>
                          </div>
                        </div>
                      </td>
                      <td className="px-5 py-4">
                        {owner.isHuman ? (
                          <span className={`inline-flex items-center gap-1 ${
                            owner.isMe ? "text-gold-400" : "text-surface-400"
                          }`}>
                            <UserCheck className="w-3.5 h-3.5" />
                            {owner.label}
                          </span>
                        ) : (
                          <span className="text-surface-500 italic flex items-center gap-1">
                            <Bot className="w-3.5 h-3.5" />
                            {owner.label}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-4 text-center text-white font-medium">{team.wins}</td>
                      <td className="px-4 py-4 text-center text-white">{team.losses}</td>
                      <td className="px-4 py-4 text-center text-surface-400">{team.ties}</td>
                      <td className="px-5 py-4 text-right text-white font-medium">{team.points_for?.toFixed(1) || "0.0"}</td>
                      <td className="px-5 py-4 text-right text-surface-400">{team.points_against?.toFixed(1) || "0.0"}</td>
                      {isLeagueManager && (
                        <td className="px-5 py-4 text-right">
                          <div className="flex items-center justify-end gap-1">
                            {/* Claim CPU team */}
                            {team.is_cpu && (
                              <button
                                onClick={() => handleClaimTeam(team.id)}
                                disabled={claimingTeamId === team.id}
                                className="p-1.5 text-surface-500 hover:text-green-400 transition-colors disabled:opacity-50"
                                title="Claim this CPU team"
                              >
                                <UserCheck className="w-4 h-4" />
                              </button>
                            )}
                            {/* Delete team */}
                            {deleteConfirmId === team.id ? (
                              <div className="flex items-center gap-1">
                                <button
                                  onClick={() => handleDeleteTeam(team.id)}
                                  className="p-1.5 text-red-400 hover:text-red-300 transition-colors"
                                  title="Confirm delete"
                                >
                                  <Check className="w-4 h-4" />
                                </button>
                                <button
                                  onClick={() => setDeleteConfirmId(null)}
                                  className="p-1.5 text-surface-500 hover:text-white transition-colors"
                                  title="Cancel"
                                >
                                  <X className="w-4 h-4" />
                                </button>
                              </div>
                            ) : (
                              <button
                                onClick={() => setDeleteConfirmId(team.id)}
                                className="p-1.5 text-surface-500 hover:text-red-400 transition-colors"
                                title="Delete team"
                              >
                                <Trash2 className="w-4 h-4" />
                              </button>
                            )}
                          </div>
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="bg-surface-800 border border-surface-700 rounded-xl p-12 text-center">
            <Users className="w-12 h-12 text-surface-600 mx-auto mb-3" />
            <h3 className="text-white font-semibold mb-1">No teams yet</h3>
            <p className="text-surface-400 text-sm">Add teams to this league to see standings.</p>
          </div>
        )}
      </section>

      {/* Team Management */}
      <section className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pb-10">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-bold text-white">Team Management</h2>
          <button
            onClick={refreshTeams}
            className="inline-flex items-center gap-1.5 text-surface-400 hover:text-gold-400 text-sm transition-colors"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Refresh
          </button>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Team roster summary */}
          <div className="lg:col-span-2 bg-surface-800 border border-surface-700 rounded-2xl p-6">
            <h3 className="text-sm font-semibold text-surface-300 mb-3">Team Roster</h3>
            <div className="flex flex-wrap gap-2">
              {sortedTeams.map((team) => {
                const avatar = getAvatarStyle(team.avatar_url);
                const isMyTeam = myTeamIds.includes(team.id);
                const isCpu = team.is_cpu || team.owner_id === "cpu";
                return (
                  <div
                    key={team.id}
                    className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs ${
                      isMyTeam
                        ? "bg-gold-400/10 border border-gold-400/20 text-gold-300"
                        : isCpu
                        ? "bg-surface-900 border border-surface-700 text-surface-400"
                        : "bg-surface-900 border border-surface-700 text-surface-300"
                    }`}
                  >
                    <span className="text-sm">{avatar.icon}</span>
                    <span className="font-medium truncate max-w-[120px]">{team.name}</span>
                    {isCpu && <Bot className="w-3 h-3 text-surface-500" />}
                    {isMyTeam && <Crown className="w-3 h-3 text-gold-500" />}
                  </div>
                );
              })}
              {teams.length < league.max_teams && Array.from({ length: league.max_teams - teams.length }).map((_, i) => (
                <div key={`empty-${i}`} className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs bg-surface-900/50 border border-dashed border-surface-700 text-surface-600">
                  <Plus className="w-3 h-3" />
                  <span>Empty Slot</span>
                </div>
              ))}
            </div>
          </div>

          {/* Action buttons */}
          <div className="bg-surface-800 border border-surface-700 rounded-2xl p-6">
            <h3 className="text-sm font-semibold text-surface-300 mb-3">Actions</h3>
            <p className="text-surface-500 text-xs mb-4">
              {teams.length} of {league.max_teams} teams filled — add more to start the draft.
            </p>
            <div className="flex flex-col gap-2">
              {teams.length < league.max_teams && (
                <>
                  <button
                    onClick={handleFillCpuAll}
                    disabled={loading}
                    className="inline-flex items-center justify-center gap-2 bg-surface-700 hover:bg-surface-600 text-white px-5 py-2.5 rounded-xl text-sm font-semibold transition-all disabled:opacity-50"
                  >
                    <Bot className="w-4 h-4" />
                    Fill All with CPU Teams
                  </button>
                  <button
                    onClick={handleAddOneCpu}
                    disabled={loading}
                    className="inline-flex items-center justify-center gap-2 border border-surface-600 hover:border-surface-500 text-surface-300 hover:text-white px-5 py-2.5 rounded-xl text-sm font-semibold transition-all disabled:opacity-50"
                  >
                    <Plus className="w-4 h-4" />
                    Add One CPU Team
                  </button>
                </>
              )}
              {!isCommissioner && !isLoggedIn() && (
                <div className="border-t border-surface-700 pt-3 mt-1">
                  <p className="text-surface-500 text-xs">
                    <Link href="/login" className="text-gold-400 hover:text-gold-300 font-medium">
                      Log in
                    </Link>{" "}
                    to claim a team.
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
