const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8005";

interface ApiOptions {
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
}

async function apiRequest<T>(endpoint: string, options: ApiOptions = {}): Promise<T> {
  const { method = "GET", body, headers = {} } = options;

  const config: RequestInit = {
    method,
    headers: {
      "Content-Type": "application/json",
      ...headers,
    },
  };

  if (body) {
    config.body = JSON.stringify(body);
  }

  const response = await fetch(`${API_BASE_URL}${endpoint}`, config);
  if (!response.ok) {
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
};

// Leagues
export const leaguesApi = {
  list: () => apiRequest("/api/v1/leagues/"),
  get: (id: string) => apiRequest(`/api/v1/leagues/${id}`),
  create: (data: Record<string, unknown>) =>
    apiRequest("/api/v1/leagues/", { method: "POST", body: data }),
  update: (id: string, data: Record<string, unknown>) =>
    apiRequest(`/api/v1/leagues/${id}`, { method: "PATCH", body: data }),
  manageCommissioner: (id: string, action: string, userId: string) =>
    apiRequest(`/api/v1/leagues/${id}/commissioner`, {
      method: "POST",
      body: { action, user_id: userId },
    }),
};

// Teams
export const teamsApi = {
  getByLeague: (leagueId: string) =>
    apiRequest(`/api/v1/teams/league/${leagueId}`),
  get: (teamId: string) =>
    apiRequest(`/api/v1/teams/${teamId}`),
  create: (data: Record<string, unknown>) =>
    apiRequest("/api/v1/teams/", { method: "POST", body: data }),
  update: (id: string, data: Record<string, unknown>) =>
    apiRequest(`/api/v1/teams/${id}`, { method: "PATCH", body: data }),
  delete: (id: string) =>
    apiRequest(`/api/v1/teams/${id}`, { method: "DELETE" }),
  claim: (teamId: string, userId: string) =>
    apiRequest(`/api/v1/teams/${teamId}/claim`, {
      method: "POST",
      body: { user_id: userId },
    }),
  bulkAddCpu: (leagueId: string, count: number, namePrefix = "CPU Team") =>
    apiRequest(`/api/v1/teams/bulk-add/${leagueId}`, {
      method: "POST",
      body: { count, name_prefix: namePrefix },
    }),
};

// Players
export const playersApi = {
  list: (params?: Record<string, string>) => {
    const query = params
      ? "?" + new URLSearchParams(params).toString()
      : "";
    return apiRequest(`/api/v1/players/${query}`);
  },
  get: (id: string) => apiRequest(`/api/v1/players/${id}`),
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
    apiRequest("/api/v1/drafts/", {
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
};

// AI
export const aiApi = {
  analyze: (leagueId: string, prompt: string) =>
    apiRequest("/api/v1/ai/analyze", {
      method: "POST",
      body: { league_id: leagueId, prompt },
    }),
  lineup: (leagueId: string, prompt: string) =>
    apiRequest("/api/v1/ai/lineup", {
      method: "POST",
      body: { league_id: leagueId, prompt },
    }),
  trade: (leagueId: string, prompt: string) =>
    apiRequest("/api/v1/ai/trade", {
      method: "POST",
      body: { league_id: leagueId, prompt },
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
