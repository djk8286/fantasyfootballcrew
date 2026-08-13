const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "";

interface ApiOptions {
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
}

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("ffc_token");
}

export function getCurrentUserId(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("ffc_user_id");
}

export function isLoggedIn(): boolean {
  return getToken() !== null;
}

export function logout(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem("ffc_token");
  localStorage.removeItem("ffc_user_id");
}

// "Which team is mine" is per-league, keyed by league_id, in the same
// ffc_user_teams blob the draft room's own claimTeam/unclaimTeam read and
// write (see frontend/src/app/draft/[id]/page.tsx) -- there's no
// server-side session for this, so it's the same localStorage shape
// everywhere rather than each caller inventing its own. Exported here so
// the mock-draft quickstart flow can claim its auto-created team the
// instant it knows the team_id, without waiting for the draft room's own
// "Select Your Team" screen -- which a quickstarted draft never shows in
// the first place, since it starts already in_progress, not pending.
export function setClaimedTeam(leagueId: string, teamId: string): void {
  if (typeof window === "undefined") return;
  try {
    const userTeams = JSON.parse(localStorage.getItem("ffc_user_teams") || "{}");
    userTeams[leagueId] = teamId;
    localStorage.setItem("ffc_user_teams", JSON.stringify(userTeams));
  } catch {
    // Malformed existing blob -- start fresh rather than crash the
    // quickstart flow over a corrupted localStorage value.
    localStorage.setItem("ffc_user_teams", JSON.stringify({ [leagueId]: teamId }));
  }
}

async function apiRequest<T>(endpoint: string, options: ApiOptions = {}): Promise<T> {
  const { method = "GET", body, headers = {} } = options;

  const token = getToken();

  const config: RequestInit = {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
  };

  if (body) {
    config.body = JSON.stringify(body);
  }

  const url = `${API_BASE_URL}${endpoint}`;
  console.debug("[FFC] Fetch:", url, { method });
  let response;
  try {
    response = await fetch(url, config);
  } catch (e) {
    throw new Error(`Failed to fetch ${url} — ${e instanceof Error ? e.message : "network error"}`);
  }
  if (!response.ok) {
    // A 401 on a request that DID carry a token means the token itself is
    // the problem -- expired (tokens are valid 30 days, see
    // create_access_token) or otherwise invalid, not just "this particular
    // action needs auth." Without this, isLoggedIn() keeps saying true
    // forever (it only checks whether a token exists in localStorage, not
    // whether it still works) and every request just quietly 401s instead
    // of the user ever actually being logged out. A 401 with NO token
    // attached is a normal auth failure for an anonymous/login action
    // (e.g. a wrong password on /login) -- leave that to the caller, which
    // already handles it, rather than hijacking it into a redirect loop.
    if (response.status === 401 && token) {
      logout();
      if (typeof window !== "undefined") {
        window.location.href = "/login?expired=1";
      }
    }
    const text = await response.text().catch(() => "");
    throw new Error(`API error: ${response.status} ${response.statusText}${text ? ` — ${text}` : ""}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}

// Auth
export const authApi = {
  login: (email: string, password: string) =>
    apiRequest("/api/v1/auth/login", {
      method: "POST",
      body: { email, password },
    }),
  register: (email: string, username: string, password: string) =>
    apiRequest("/api/v1/auth/register", {
      method: "POST",
      body: { email, username, password, provider: "email" },
    }),
  forgotPassword: (email: string) =>
    apiRequest("/api/v1/auth/forgot-password", {
      method: "POST",
      body: { email },
    }),
  resetPassword: (token: string, newPassword: string) =>
    apiRequest("/api/v1/auth/reset-password", {
      method: "POST",
      body: { token, new_password: newPassword },
    }),
};

// Users
export const usersApi = {
  me: () => apiRequest("/api/v1/users/me"),
  update: (username: string) =>
    apiRequest("/api/v1/users/me", { method: "PUT", body: { username } }),
  changePassword: (currentPassword: string, newPassword: string) =>
    apiRequest("/api/v1/users/me/change-password", {
      method: "POST",
      body: { current_password: currentPassword, new_password: newPassword },
    }),
};

export interface LeagueListFilters {
  mine?: boolean;
  visibility?: "private" | "invite_only" | "open";
  league_type?: "standard" | "two_man" | "conference";
  open_only?: boolean;
  wanted_board_only?: boolean;
  sort?: "newest" | "open_spots" | "name" | "size";
}

// Leagues
export const leaguesApi = {
  list: (filters?: LeagueListFilters) => {
    const params = new URLSearchParams();
    if (filters?.mine) params.set("mine", "true");
    if (filters?.visibility) params.set("visibility", filters.visibility);
    if (filters?.league_type) params.set("league_type", filters.league_type);
    if (filters?.open_only) params.set("open_only", "true");
    if (filters?.wanted_board_only) params.set("wanted_board_only", "true");
    if (filters?.sort) params.set("sort", filters.sort);
    const qs = params.toString();
    return apiRequest(`/api/v1/leagues${qs ? `?${qs}` : ""}`);
  },
  get: (id: string) => apiRequest(`/api/v1/leagues/${id}`),
  create: (data: Record<string, unknown>) =>
    apiRequest("/api/v1/leagues", { method: "POST", body: data }),
  update: (id: string, data: Record<string, unknown>) =>
    apiRequest(`/api/v1/leagues/${id}`, { method: "PATCH", body: data }),
  manageCommissioner: (id: string, action: string, userId: string) =>
    apiRequest(`/api/v1/leagues/${id}/commissioner`, {
      method: "POST",
      body: { action, user_id: userId },
    }),
  getRosterSlots: (id: string) =>
    apiRequest(`/api/v1/leagues/${id}/roster-slots`),
  updateRosterSlots: (id: string, rosterSlots: Record<string, number>) =>
    apiRequest(`/api/v1/leagues/${id}/roster-slots`, {
      method: "PUT",
      body: { roster_slots: rosterSlots },
    }),
  getPlayoffSettings: (id: string) =>
    apiRequest(`/api/v1/leagues/${id}/playoff-settings`),
  updatePlayoffSettings: (id: string, playoffSettings: Record<string, unknown>) =>
    apiRequest(`/api/v1/leagues/${id}/playoff-settings`, {
      method: "PUT",
      body: { playoff_settings: playoffSettings },
    }),
  getPlayoffs: (id: string) =>
    apiRequest(`/api/v1/leagues/${id}/playoffs`),
  getRivalryWeekSettings: (id: string) =>
    apiRequest(`/api/v1/leagues/${id}/rivalry-week-settings`),
  updateRivalryWeekSettings: (id: string, rivalryWeekSettings: Record<string, unknown>) =>
    apiRequest(`/api/v1/leagues/${id}/rivalry-week-settings`, {
      method: "PUT",
      body: { rivalry_week_settings: rivalryWeekSettings },
    }),
  getSalaryCapSettings: (id: string) =>
    apiRequest(`/api/v1/leagues/${id}/salary-cap-settings`),
  updateSalaryCapSettings: (id: string, salaryCapSettings: Record<string, unknown>) =>
    apiRequest(`/api/v1/leagues/${id}/salary-cap-settings`, {
      method: "PUT",
      body: { salary_cap_settings: salaryCapSettings },
    }),
  previewSigning: (id: string, playerId: string) =>
    apiRequest(`/api/v1/leagues/${id}/salary-cap/preview-signing?player_id=${encodeURIComponent(playerId)}`),
};

// Teams
export const teamsApi = {
  getByLeague: (leagueId: string) =>
    apiRequest(`/api/v1/teams/league/${leagueId}`),
  get: (teamId: string) =>
    apiRequest(`/api/v1/teams/${teamId}`),
  create: (data: Record<string, unknown>) =>
    apiRequest("/api/v1/teams", { method: "POST", body: data }),
  update: (id: string, data: Record<string, unknown>) =>
    apiRequest(`/api/v1/teams/${id}`, { method: "PATCH", body: data }),
  delete: (id: string) =>
    apiRequest(`/api/v1/teams/${id}`, { method: "DELETE" }),
  claim: (teamId: string) =>
    apiRequest(`/api/v1/teams/${teamId}/claim`, {
      method: "POST",
    }),
  claimCoOwner: (teamId: string) =>
    apiRequest(`/api/v1/teams/${teamId}/claim-co-owner`, {
      method: "POST",
    }),
  bulkAddCpu: (leagueId: string, count: number, namePrefix = "CPU Team") =>
    apiRequest(`/api/v1/teams/bulk-add/${leagueId}`, {
      method: "POST",
      body: { count, name_prefix: namePrefix },
    }),
  getCap: (teamId: string) =>
    apiRequest(`/api/v1/teams/${teamId}/cap`),
  release: (teamId: string, playerId: string) =>
    apiRequest(`/api/v1/teams/${teamId}/release`, {
      method: "POST",
      body: { player_id: playerId },
    }),
};

// Notifications
export const notificationsApi = {
  list: (unreadOnly = false) =>
    apiRequest(`/api/v1/notifications${unreadOnly ? "?unread_only=true" : ""}`),
  markRead: (id: string) =>
    apiRequest(`/api/v1/notifications/${id}/read`, { method: "POST" }),
  markAllRead: () =>
    apiRequest("/api/v1/notifications/read-all", { method: "POST" }),
};

// Lineups (starter/bench)
export const lineupsApi = {
  get: (teamId: string, week: number, year: number) =>
    apiRequest(`/api/v1/teams/${teamId}/lineup?week=${week}&year=${year}`),
  set: (teamId: string, week: number, year: number, starters: string[]) =>
    apiRequest(`/api/v1/teams/${teamId}/lineup?week=${week}&year=${year}`, {
      method: "PUT",
      body: { starters },
    }),
  optimize: (teamId: string, week: number, year: number) =>
    apiRequest(`/api/v1/teams/${teamId}/lineup/optimize?week=${week}&year=${year}`, {
      method: "POST",
    }),
};

// Players
export const playersApi = {
  list: (params?: Record<string, string>) => {
    const query = params
      ? "?" + new URLSearchParams(params).toString()
      : "";
    return apiRequest(`/api/v1/players${query}`);
  },
  get: (id: string, leagueId?: string) =>
    apiRequest(`/api/v1/players/${id}${leagueId ? `?league_id=${leagueId}` : ""}`),
  topProspects: (limit = 100) => apiRequest(`/api/v1/players/top-prospects?limit=${limit}`),
};

// Scoring
export const scoringApi = {
  getDefaults: () => apiRequest("/api/v1/scoring/defaults"),
  getByLeague: (leagueId: string) =>
    apiRequest(`/api/v1/scoring/league/${leagueId}`),
  getByLeagueV2: (leagueId: string) =>
    apiRequest(`/api/v1/leagues/${leagueId}/scoring`),
  updateByLeague: (leagueId: string, scoringConfig: Record<string, unknown>) =>
    apiRequest(`/api/v1/leagues/${leagueId}/scoring`, {
      method: "PUT",
      body: { scoring_config: scoringConfig },
    }),
};

// Drafts
export const draftsApi = {
  create: (leagueId: string, totalRounds = 15) =>
    apiRequest("/api/v1/drafts", {
      method: "POST",
      body: { league_id: leagueId, total_rounds: totalRounds },
    }),
  start: (draftId: string) =>
    apiRequest(`/api/v1/drafts/${draftId}/start`, { method: "POST" }),
  makePick: (draftId: string, teamId: string, playerId: string) =>
    apiRequest(`/api/v1/drafts/${draftId}/pick`, {
      method: "POST",
      body: { team_id: teamId, player_id: playerId },
    }),
  getState: (draftId: string) => apiRequest(`/api/v1/drafts/${draftId}/state`),
  runMock: (draftId: string, skipTeamIds?: string[]) =>
    apiRequest(`/api/v1/drafts/${draftId}/mock`, {
      method: "POST",
      body: { skip_team_ids: skipTeamIds || [] },
    }),
  autoPick: (draftId: string) =>
    apiRequest(`/api/v1/drafts/${draftId}/auto-pick`, { method: "POST" }),
  setTimer: (draftId: string, timerSeconds: number) =>
    apiRequest(`/api/v1/drafts/${draftId}/timer`, {
      method: "PATCH",
      body: { timer_seconds: timerSeconds },
    }),
  quickstartMock: (numTeams: number, totalRounds: number, draftPosition?: number) =>
    apiRequest("/api/v1/drafts/mock/quickstart", {
      method: "POST",
      body: {
        num_teams: numTeams,
        total_rounds: totalRounds,
        draft_position: draftPosition ?? null,
      },
    }),
};

// Standings
export const standingsApi = {
  getStandings: (leagueId: string) =>
    apiRequest(`/api/v1/leagues/${leagueId}/standings`),
  getWeeklyScores: (leagueId: string, week: number, year: number) =>
    apiRequest(`/api/v1/leagues/${leagueId}/standings/weekly?week=${week}&year=${year}`),
  calculateWeek: (leagueId: string, week: number, year: number) =>
    apiRequest(`/api/v1/leagues/${leagueId}/standings/calculate?week=${week}&year=${year}`, {
      method: "POST",
    }),
  getSchedule: (leagueId: string, year: number, weeks = 14) =>
    apiRequest(`/api/v1/leagues/${leagueId}/standings/schedule?year=${year}&weeks=${weeks}`),
};

// AI
export const aiApi = {
  lineup: (teamId: string) =>
    apiRequest("/api/v1/ai/lineup", {
      method: "POST",
      body: { team_id: teamId },
    }),
  trade: (tradeId: string) =>
    apiRequest("/api/v1/ai/trade", {
      method: "POST",
      body: { trade_id: tradeId },
    }),
  bet: (prompt: string) =>
    apiRequest("/api/v1/ai/bet", {
      method: "POST",
      body: { prompt },
    }),
};

export default apiRequest;

// Commissioner
export const commissionerApi = {
  // Points adjustments
  addAdjustment: (leagueId: string, data: { team_id: string; week: number; year: number; amount: number; reason: string }) =>
    apiRequest(`/api/v1/leagues/${leagueId}/commissioner/adjustments`, {
      method: "POST",
      body: data,
    }),
  listAdjustments: (leagueId: string, week?: number, teamId?: string) => {
    const params = new URLSearchParams();
    if (week !== undefined) params.set("week", String(week));
    if (teamId) params.set("team_id", teamId);
    const qs = params.toString() ? `?${params.toString()}` : "";
    return apiRequest(`/api/v1/leagues/${leagueId}/commissioner/adjustments${qs}`);
  },
  deleteAdjustment: (leagueId: string, adjustmentId: string) =>
    apiRequest(`/api/v1/leagues/${leagueId}/commissioner/adjustments/${adjustmentId}`, {
      method: "DELETE",
    }),

  // Trades
  listTrades: (leagueId: string, statusFilter?: string) => {
    const qs = statusFilter ? `?status_filter=${statusFilter}` : "";
    return apiRequest(`/api/v1/leagues/${leagueId}/commissioner/trades${qs}`);
  },
  reviewTrade: (leagueId: string, tradeId: string, action: "approve" | "deny") =>
    apiRequest(`/api/v1/leagues/${leagueId}/commissioner/trades/${tradeId}/review`, {
      method: "POST",
      body: { action },
    }),

  // Draft order
  getDraftOrder: (leagueId: string) =>
    apiRequest(`/api/v1/leagues/${leagueId}/commissioner/draft-order`),
  setDraftOrder: (leagueId: string, teamOrder: string[]) =>
    apiRequest(`/api/v1/leagues/${leagueId}/commissioner/draft-order`, {
      method: "PUT",
      body: { team_order: teamOrder },
    }),
  randomizeDraftOrder: (leagueId: string) =>
    apiRequest(`/api/v1/leagues/${leagueId}/commissioner/draft-order/randomize`, {
      method: "POST",
    }),
};

// Trades (proposing/listing — reviewing lives on commissionerApi)
export const tradesApi = {
  propose: (
    leagueId: string,
    data: { team_id: string; target_team_id: string; offered_player_ids: string[]; requested_player_ids: string[] },
  ) =>
    apiRequest(`/api/v1/leagues/${leagueId}/trades`, {
      method: "POST",
      body: data,
    }),
  list: (leagueId: string, teamId?: string) => {
    const qs = teamId ? `?team_id=${teamId}` : "";
    return apiRequest(`/api/v1/leagues/${leagueId}/trades${qs}`);
  },
};

// Waivers
export const waiversApi = {
  submitClaim: (leagueId: string, data: { team_id: string; add_player_id: string; drop_player_id?: string }) =>
    apiRequest(`/api/v1/leagues/${leagueId}/waivers/claims`, {
      method: "POST",
      body: data,
    }),
  listClaims: (leagueId: string, teamId?: string) => {
    const qs = teamId ? `?team_id=${teamId}` : "";
    return apiRequest(`/api/v1/leagues/${leagueId}/waivers/claims${qs}`);
  },
  cancelClaim: (leagueId: string, claimId: string) =>
    apiRequest(`/api/v1/leagues/${leagueId}/waivers/claims/${claimId}`, {
      method: "DELETE",
    }),
  getPriority: (leagueId: string) =>
    apiRequest(`/api/v1/leagues/${leagueId}/waivers/priority`),
  process: (leagueId: string) =>
    apiRequest(`/api/v1/leagues/${leagueId}/waivers/process`, {
      method: "POST",
    }),
  freeAgents: (leagueId: string, limitPerPosition = 25) =>
    apiRequest(`/api/v1/leagues/${leagueId}/waivers/free-agents?limit_per_position=${limitPerPosition}`),
};

// League Invites
export const invitesApi = {
  send: (leagueId: string, emails: string[], message?: string) =>
    apiRequest(`/api/v1/leagues/${leagueId}/invites`, {
      method: "POST",
      body: { emails, message: message || undefined },
    }),
  list: (leagueId: string) =>
    apiRequest(`/api/v1/leagues/${leagueId}/invites`),
  revoke: (leagueId: string, inviteId: string) =>
    apiRequest(`/api/v1/leagues/${leagueId}/invites/${inviteId}`, {
      method: "DELETE",
    }),
  // Public -- no auth required, unlike the two above.
  getByToken: (token: string) =>
    apiRequest(`/api/v1/invites/${token}`),
  accept: (token: string) =>
    apiRequest(`/api/v1/invites/${token}/accept`, { method: "POST" }),
};

// League Join Requests -- the "or approval" half of Invite-only, where a
// user found the league through discovery and asks the commissioner for
// access, rather than the commissioner reaching out first (invitesApi).
export const joinRequestsApi = {
  create: (leagueId: string, message?: string) =>
    apiRequest(`/api/v1/leagues/${leagueId}/join-requests`, {
      method: "POST",
      body: { message: message || undefined },
    }),
  list: (leagueId: string) =>
    apiRequest(`/api/v1/leagues/${leagueId}/join-requests`),
  decide: (leagueId: string, requestId: string, action: "approve" | "deny") =>
    apiRequest(`/api/v1/leagues/${leagueId}/join-requests/${requestId}/decision`, {
      method: "POST",
      body: { action },
    }),
};

// Coaches
export const coachesApi = {
  listByTeam: (teamId: string) => apiRequest(`/api/v1/teams/${teamId}/coaches`),
  create: (
    teamId: string,
    data: { name: string; position: string; bonus_type?: string; bonus_value?: number },
  ) =>
    apiRequest(`/api/v1/teams/${teamId}/coaches`, {
      method: "POST",
      body: data,
    }),
  update: (coachId: string, data: Record<string, unknown>) =>
    apiRequest(`/api/v1/coaches/${coachId}`, {
      method: "PATCH",
      body: data,
    }),
  delete: (coachId: string) =>
    apiRequest(`/api/v1/coaches/${coachId}`, {
      method: "DELETE",
    }),
};
