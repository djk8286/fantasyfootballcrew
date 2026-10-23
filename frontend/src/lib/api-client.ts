// Always same-origin: /api/* is proxied to the backend by src/proxy.ts,
// so the HttpOnly auth cookies are first-party. (NEXT_PUBLIC_API_URL is no
// longer used for API calls; it only feeds the CSP in next.config.ts.)
import { getCurrentNflState } from "./current-week";
import type { SyncStatus } from "./freshness";

const API_BASE_URL = "";

interface ApiOptions {
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
}

// Auth lives in HttpOnly cookies the page can't read. The only thing kept
// client-side is a NON-secret hint -- the logged-in user's id -- so the
// many synchronous isLoggedIn()/isCurrentUser() UI checks keep working.
// The server is the source of truth: syncSession() validates the hint
// against /auth/me on app load, and any request that 401s after one
// refresh attempt clears it.
const USER_HINT_KEY = "ffc_user_id";
const LEGACY_TOKEN_KEY = "ffc_token";

export function getCurrentUserId(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(USER_HINT_KEY) || null;
}

/** True only when a user is logged in AND `id` is that user's id.
 * Never compare `x === getCurrentUserId()` directly: for a logged-out
 * visitor both sides can be null (e.g. team.co_owner_id, or owner_id on
 * CPU teams), and null === null made anonymous visitors look like team
 * owners (QA round 1, bug #1). */
export function isCurrentUser(id: string | null | undefined): boolean {
  const me = getCurrentUserId();
  return !!me && !!id && id === me;
}

export function isLoggedIn(): boolean {
  return getCurrentUserId() !== null;
}

/** Record a successful login (cookies were already set by the server). */
export function setSession(userId: string): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(USER_HINT_KEY, userId);
  localStorage.removeItem(LEGACY_TOKEN_KEY);
  markAccessFresh();
}

function clearSessionHint(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(USER_HINT_KEY);
  localStorage.removeItem(ACCESS_AT_KEY);
}

// Proactive refresh (QA 2026-10-19 BUG J): the access cookie lives ~15
// min, so the first request after that used to go out, 401, refresh, and
// be retried -- harmless (a 401 is raised by auth before any handler side
// effect, so the retry is the only write) but noisy in the network panel.
// We remember when the access cookie was last issued (shared across tabs
// via localStorage) and refresh *before* sending once it's about to lapse.
// The 401 -> refresh -> retry path below stays as the fallback.
const ACCESS_AT_KEY = "ffc_access_at";
const ACCESS_REFRESH_AFTER_MS = 14 * 60_000; // server lifetime is 15 min

function markAccessFresh(): void {
  if (typeof window !== "undefined") localStorage.setItem(ACCESS_AT_KEY, String(Date.now()));
}

/** True when the access cookie was issued long enough ago that it's about
 * to (or did) expire. Unknown issue time -> false (fall back to 401 retry). */
export function accessLikelyExpired(issuedAt: string | null, now: number = Date.now()): boolean {
  if (!issuedAt) return false;
  const t = Number(issuedAt);
  return !Number.isFinite(t) || now - t > ACCESS_REFRESH_AFTER_MS;
}

/** Clear local state immediately and revoke the server session (refresh
 * token family + cookies). Returns the server call's promise for callers
 * that want to wait before navigating. */
export function logout(): Promise<void> {
  clearSessionHint();
  if (typeof window !== "undefined") localStorage.removeItem(LEGACY_TOKEN_KEY);
  if (typeof window === "undefined") return Promise.resolve();
  return fetch(`${API_BASE_URL}/api/v1/auth/logout`, {
    method: "POST",
    credentials: "include",
    keepalive: true,
  })
    .then(() => undefined)
    .catch(() => undefined);
}

// Single-flight refresh: concurrent 401s share one /auth/refresh call.
let refreshInFlight: Promise<boolean> | null = null;

function refreshSession(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = fetch(`${API_BASE_URL}/api/v1/auth/refresh`, {
      method: "POST",
      credentials: "include",
    })
      // 401 "Refresh superseded" = another tab rotated the refresh token a
      // moment ago; the shared cookie jar already has the new one, so a
      // retry will succeed.
      .then(async (r) => {
        if (r.ok) markAccessFresh();
        return r.ok || (r.status === 401 && (await r.text().catch(() => "")).includes("superseded"));
      })
      .catch(() => false)
      .finally(() => {
        // Let a later expiry trigger a new refresh.
        setTimeout(() => {
          refreshInFlight = null;
        }, 0);
      });
  }
  return refreshInFlight;
}

let sessionSynced: Promise<void> | null = null;

/** The backend sets a script-readable, non-secret `ffc_session=1` cookie
 * alongside the HttpOnly auth cookies (and clears it on logout/expiry). */
export function hasSessionHintCookie(cookieString: string = typeof document === "undefined" ? "" : document.cookie): boolean {
  return cookieString.split(";").some((c) => c.trim().startsWith("ffc_session="));
}

/** Whether the bootstrap should talk to the server at all. Pure, for tests. */
export function sessionProbePlan(s: { hasSessionCookie: boolean; hasUserHint: boolean; hasLegacyToken: boolean }): "skip" | "probe" {
  return s.hasSessionCookie || s.hasUserHint || s.hasLegacyToken ? "probe" : "skip";
}

/** Run once per page load (Header calls it): silently upgrade a legacy
 * localStorage JWT to a cookie session, then reconcile the logged-in hint
 * with the server via GET /auth/session. Never redirects. */
export function syncSession(): Promise<void> {
  if (typeof window === "undefined") return Promise.resolve();
  if (sessionSynced) return sessionSynced;
  sessionSynced = (async () => {
    const legacy = localStorage.getItem(LEGACY_TOKEN_KEY);
    if (legacy) {
      try {
        const r = await fetch(`${API_BASE_URL}/api/v1/auth/session`, {
          method: "POST",
          credentials: "include",
          headers: { Authorization: `Bearer ${legacy}` },
        });
        if (r.ok) {
          const data = (await r.json()) as { user?: { id?: string } };
          if (data.user?.id) localStorage.setItem(USER_HINT_KEY, data.user.id);
          localStorage.removeItem(LEGACY_TOKEN_KEY);
        } else if (r.status === 401 || r.status === 403) {
          // Token is dead (expired/revoked/suspended): drop it.
          localStorage.removeItem(LEGACY_TOKEN_KEY);
        }
        // Anything else (404 while the backend deploy lags the frontend,
        // 5xx, 429): keep the token and retry on the next page load.
      } catch {
        // Network hiccup: keep the token, retry next load.
      }
    }
    // Guests (no hint cookie, no stored user id, no legacy token) make no
    // auth calls at all -- previously every guest page view logged 401s
    // from /auth/me and /auth/refresh (QA regression 2026-10-19).
    const plan = sessionProbePlan({
      hasSessionCookie: hasSessionHintCookie(),
      hasUserHint: !!localStorage.getItem(USER_HINT_KEY),
      hasLegacyToken: !!localStorage.getItem(LEGACY_TOKEN_KEY),
    });
    if (plan === "skip") return;
    // /auth/session always answers 200 ({user: null} when signed out).
    const probe = async (): Promise<{ id?: string } | null | undefined> => {
      const r = await fetch(`${API_BASE_URL}/api/v1/auth/session`, { credentials: "include" });
      if (!r.ok) return undefined; // 5xx/429/offline-ish: unknown, keep hint
      return ((await r.json()) as { user: { id?: string } | null }).user;
    };
    try {
      let user = await probe();
      if (user === null && (await refreshSession())) user = await probe();
      if (user && user.id) {
        localStorage.setItem(USER_HINT_KEY, user.id);
      } else if (user === null && !localStorage.getItem(LEGACY_TOKEN_KEY)) {
        clearSessionHint();
      }
    } catch {
      // Offline: keep the hint; the next real request will sort it out.
    }
  })();
  return sessionSynced;
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

/** Team ids this browser has claimed in `leagueId` (ffc_user_teams).
 * Only meaningful for the logged-in user: pass it through
 * league-nav.findMyTeamId, which ignores it when nobody is logged in.
 * The blob is per-browser, not per-account, and survives logout. */
export function claimedTeamIds(leagueId: string): string[] {
  if (typeof window === "undefined") return [];
  try {
    const stored = JSON.parse(localStorage.getItem("ffc_user_teams") || "{}");
    return typeof stored?.[leagueId] === "string" ? [stored[leagueId]] : [];
  } catch {
    return [];
  }
}

/** Thrown by apiRequest on a non-2xx response. `message` keeps the legacy
 * "API error: <status> <text> — <body>" format (app/admin/adminUtils.ts and
 * settings parse it); UI that shows errors to visitors should use
 * friendlyErrorMessage() instead of printing `message` raw. */
export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(message: string, status: number, detail: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

const FIELD_LABELS: Record<string, string> = {
  email: "Email",
  username: "Username",
  password: "Password",
  new_password: "New password",
  current_password: "Current password",
};

/** Turn a FastAPI `detail` (string, or a 422 validation-error list) into a
 * sentence a person can read. */
export function formatApiDetail(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((d) => {
        if (!d || typeof d !== "object") return null;
        const e = d as { loc?: unknown[]; msg?: string; type?: string; ctx?: { min_length?: number; max_length?: number } };
        const field = Array.isArray(e.loc) ? String(e.loc[e.loc.length - 1] ?? "") : "";
        const label = FIELD_LABELS[field] || (field ? field.charAt(0).toUpperCase() + field.slice(1).replace(/_/g, " ") : "");
        if (e.type === "string_too_short" && e.ctx?.min_length != null) {
          return `${label || "Value"} must be at least ${e.ctx.min_length} characters.`;
        }
        if (e.type === "string_too_long" && e.ctx?.max_length != null) {
          return `${label || "Value"} must be at most ${e.ctx.max_length} characters.`;
        }
        if (e.msg) {
          const msg = e.msg.replace(/^Value error, /, "");
          return label ? `${label}: ${msg}` : msg;
        }
        return null;
      })
      .filter(Boolean);
    if (parts.length) return parts.join(" ");
  }
  return null;
}

/** Human-readable message for any error thrown by apiRequest (or anything
 * else). `overrides` maps HTTP status -> message for context-specific
 * wording, e.g. {401: "Invalid email or password."} on the login form. */
export function friendlyErrorMessage(
  err: unknown,
  fallback = "Something went wrong. Please try again.",
  overrides: Record<number, string> = {}
): string {
  if (err instanceof ApiError) {
    if (overrides[err.status]) return overrides[err.status];
    const formatted = formatApiDetail(err.detail);
    if (formatted) return formatted;
    if (err.status === 429) return "Too many attempts. Please wait a minute and try again.";
    if (err.status >= 500) return "The server had a problem. Please try again in a moment.";
    return fallback;
  }
  if (err instanceof Error && err.message.startsWith("Failed to fetch")) {
    return "Couldn't reach the server. Check your connection and try again.";
  }
  return fallback;
}

const NO_REFRESH_ENDPOINTS = ["/api/v1/auth/login", "/api/v1/auth/register", "/api/v1/auth/refresh", "/api/v1/auth/logout"];

async function apiRequest<T>(endpoint: string, options: ApiOptions = {}): Promise<T> {
  const { method = "GET", body, headers = {} } = options;

  // Transitional: a not-yet-migrated legacy token (syncSession couldn't
  // upgrade it yet, e.g. the backend deploy is lagging this frontend) is
  // still sent as Bearer so the user isn't bounced. Removed next release.
  const legacy = typeof window !== "undefined" ? localStorage.getItem(LEGACY_TOKEN_KEY) : null;
  const config: RequestInit = {
    method,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(legacy ? { Authorization: `Bearer ${legacy}` } : {}),
      ...headers,
    },
  };

  if (body) {
    config.body = JSON.stringify(body);
  }

  const url = `${API_BASE_URL}${endpoint}`;
  console.debug("[FFC] Fetch:", url, { method });
  const doFetch = async () => {
    try {
      return await fetch(url, config);
    } catch (e) {
      throw new Error(`Failed to fetch ${url} — ${e instanceof Error ? e.message : "network error"}`);
    }
  };
  if (
    typeof window !== "undefined" &&
    isLoggedIn() &&
    !NO_REFRESH_ENDPOINTS.includes(endpoint) &&
    accessLikelyExpired(localStorage.getItem(ACCESS_AT_KEY))
  ) {
    await refreshSession();
  }
  let response = await doFetch();
  // The ~15-minute access cookie expired (or is missing but a refresh
  // cookie may still exist): refresh once and retry. Login/register/etc.
  // 401s are real answers (e.g. wrong password) and are left to callers.
  if (response.status === 401 && isLoggedIn() && !NO_REFRESH_ENDPOINTS.includes(endpoint)) {
    if (await refreshSession()) {
      response = await doFetch();
    }
    if (response.status === 401 && isLoggedIn()) {
      // Session really is gone (expired refresh, force-logout, password
      // change elsewhere): drop the hint and send them to log in again.
      clearSessionHint();
      if (typeof window !== "undefined") {
        localStorage.removeItem(LEGACY_TOKEN_KEY);
        window.location.href = "/login?expired=1";
      }
    }
  }
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    let detail: unknown = undefined;
    try {
      detail = text ? (JSON.parse(text) as { detail?: unknown }).detail : undefined;
    } catch {
      detail = undefined;
    }
    throw new ApiError(
      `API error: ${response.status} ${response.statusText}${text ? ` — ${text}` : ""}`,
      response.status,
      detail
    );
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
  verifyEmail: (token: string) =>
    apiRequest("/api/v1/auth/verify-email", {
      method: "POST",
      body: { token },
    }),
  resendVerification: () =>
    apiRequest("/api/v1/auth/resend-verification", { method: "POST" }),
};

// Users
export const usersApi = {
  me: () => apiRequest("/api/v1/users/me"),
  update: (data: { username?: string; avatar_url?: string }) =>
    apiRequest("/api/v1/users/me", { method: "PUT", body: data }),
  changePassword: (currentPassword: string, newPassword: string) =>
    apiRequest("/api/v1/users/me/change-password", {
      method: "POST",
      body: { current_password: currentPassword, new_password: newPassword },
    }),
  // password is omitted entirely (not just empty-string) for Google-OAuth
  // accounts -- there's nothing to confirm, see backend delete_me.
  deleteAccount: (password?: string) =>
    apiRequest("/api/v1/users/me", {
      method: "DELETE",
      body: password ? { password } : {},
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
  /** League home in one call. See GET /leagues/{id}/home. */
  getHome: (leagueId: string, week: number, year: number) =>
    apiRequest(`/api/v1/leagues/${leagueId}/home?week=${week}&year=${year}`),
  /** League feed, newest first. teamId narrows it to one team. */
  getActivity: (leagueId: string, teamId?: string, limit = 30) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (teamId) params.set("team_id", teamId);
    return apiRequest(`/api/v1/leagues/${leagueId}/activity?${params.toString()}`);
  },
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
  // Dashboard AI Summaries -- open read, no auth required, same as
  // standings/schedule: visible to every manager on the league
  // dashboard, not gated behind commissioner access like the AI Digest.
  // week/year omitted -> most recently generated recap (the normal
  // case -- this is an ambient panel, no week-picker UI).
  getTeamRecap: (id: string, week?: number, year?: number) =>
    apiRequest(`/api/v1/leagues/${id}/team-recap${week && year ? `?week=${week}&year=${year}` : ""}`),
  create: (data: Record<string, unknown>) =>
    apiRequest("/api/v1/leagues", { method: "POST", body: data }),
  update: (id: string, data: Record<string, unknown>) =>
    apiRequest(`/api/v1/leagues/${id}`, { method: "PATCH", body: data }),
  /** Commissioner, co-commissioners and team managers by username. Managers only. */
  getMembers: (id: string) => apiRequest(`/api/v1/leagues/${id}/members`),
  /** Add or remove a co-commissioner, or hand over the league, by username or email. */
  manageCommissionerByName: (id: string, action: "add_co_commish" | "remove_co_commish" | "transfer", identifier: string) =>
    apiRequest(`/api/v1/leagues/${id}/commissioner`, { method: "POST", body: { action, identifier } }),
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
  getBestBallSettings: (id: string) =>
    apiRequest(`/api/v1/leagues/${id}/best-ball-settings`),
  updateBestBallSettings: (id: string, bestBallSettings: Record<string, unknown>) =>
    apiRequest(`/api/v1/leagues/${id}/best-ball-settings`, {
      method: "PUT",
      body: { best_ball_settings: bestBallSettings },
    }),
  getAiSettings: (id: string) =>
    apiRequest(`/api/v1/leagues/${id}/ai-settings`),
  updateAiSettings: (id: string, aiCommissionerSettings: Record<string, unknown>) =>
    apiRequest(`/api/v1/leagues/${id}/ai-settings`, {
      method: "PUT",
      body: { ai_commissioner_settings: aiCommissionerSettings },
    }),
  getManagementWindow: (id: string) =>
    apiRequest(`/api/v1/leagues/${id}/management-window`),
};

// Teams
export const teamsApi = {
  getByLeague: (leagueId: string) =>
    apiRequest(`/api/v1/teams/league/${leagueId}`),
  get: (teamId: string) =>
    apiRequest(`/api/v1/teams/${teamId}`),
  /** Team, record, owner usernames and this week's roster rows in one call. */
  getRoster: (teamId: string, week: number, year: number) =>
    apiRequest(`/api/v1/teams/${teamId}/roster?week=${week}&year=${year}`),
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
  // Commissioner-side equivalents -- assign/remove on someone else's
  // behalf, gated server-side to the league's commissioner/co-commissioners.
  removeOwner: (teamId: string) =>
    apiRequest(`/api/v1/teams/${teamId}/remove-owner`, { method: "POST" }),
  removeCoOwner: (teamId: string) =>
    apiRequest(`/api/v1/teams/${teamId}/remove-co-owner`, { method: "POST" }),
  assignOwner: (teamId: string, identifier: string) =>
    apiRequest(`/api/v1/teams/${teamId}/assign-owner`, { method: "POST", body: { identifier } }),
  assignCoOwner: (teamId: string, identifier: string) =>
    apiRequest(`/api/v1/teams/${teamId}/assign-co-owner`, { method: "POST", body: { identifier } }),
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
  setSlots: (teamId: string, week: number, year: number, slots: { slot: string; player_id: string | null }[]) =>
    apiRequest(`/api/v1/teams/${teamId}/lineup?week=${week}&year=${year}`, {
      method: "PUT",
      body: { slots },
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
  detail: (id: string) => apiRequest(`/api/v1/players/${id}/detail`),
  /** Batched lookup; 150 ids per call keeps the URL ~5.5 KB (server caps at 400). */
  byIds: async (ids: string[]): Promise<{ id: string; first_name?: string; last_name?: string }[]> => {
    const out: { id: string; first_name?: string; last_name?: string }[] = [];
    for (let i = 0; i < ids.length; i += 150) {
      const chunk = ids.slice(i, i + 150);
      out.push(...(await apiRequest<typeof out>(`/api/v1/players?ids=${chunk.map(encodeURIComponent).join(",")}`)));
    }
    return out;
  },
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
  // pickNumber (optional): the overall pick this is for -- the server
  // rejects it if that pick was already made, so a double-click can never
  // spill onto the next pick (e.g. your own back-to-back snake-turn pick).
  makePick: (draftId: string, teamId: string, playerId: string, pickNumber?: number) =>
    apiRequest<{ id: string; round: number; pick_number: number; player: string | null; position: string | null }>(
      `/api/v1/drafts/${draftId}/pick`,
      {
        method: "POST",
        body: { team_id: teamId, player_id: playerId, ...(pickNumber ? { pick_number: pickNumber } : {}) },
      },
    ),
  getState: (draftId: string) => apiRequest(`/api/v1/drafts/${draftId}/state`),
  runMock: (draftId: string, skipTeamIds?: string[]) =>
    apiRequest<{ message: string; total_picks: number; status: string }>(`/api/v1/drafts/${draftId}/mock`, {
      method: "POST",
      body: { skip_team_ids: skipTeamIds || [] },
    }),
  pause: (draftId: string) =>
    apiRequest(`/api/v1/drafts/${draftId}/pause`, { method: "POST" }),
  resume: (draftId: string) =>
    apiRequest(`/api/v1/drafts/${draftId}/resume`, { method: "POST" }),
  autoPick: (draftId: string) =>
    apiRequest(`/api/v1/drafts/${draftId}/auto-pick`, { method: "POST" }),
  setTimer: (draftId: string, timerSeconds: number) =>
    apiRequest(`/api/v1/drafts/${draftId}/timer`, {
      method: "PATCH",
      body: { timer_seconds: timerSeconds },
    }),
  // Server-persisted Autopick toggle (2026-10-19): ON = the server picks
  // for this team as soon as it's on the clock, tab open or not.
  getAutopick: (draftId: string, teamId: string) =>
    apiRequest<{ team_id: string; enabled: boolean }>(
      `/api/v1/drafts/${draftId}/autopick?team_id=${encodeURIComponent(teamId)}`,
    ),
  setAutopick: (draftId: string, teamId: string, enabled: boolean) =>
    apiRequest<{ team_id: string; enabled: boolean }>(`/api/v1/drafts/${draftId}/autopick`, {
      method: "PUT",
      body: { team_id: teamId, enabled },
    }),
  // Server-persisted pick queue (2026-09-09) -- survives a page refresh,
  // unlike the old purely-client-state version. See app/api/v1/drafts.py.
  getQueue: (draftId: string, teamId: string) =>
    apiRequest<{ player_ids: string[] }>(`/api/v1/drafts/${draftId}/queue?team_id=${encodeURIComponent(teamId)}`),
  addToQueue: (draftId: string, teamId: string, playerId: string) =>
    apiRequest<{ player_ids: string[] }>(`/api/v1/drafts/${draftId}/queue/add`, {
      method: "POST",
      body: { team_id: teamId, player_id: playerId },
    }),
  removeFromQueue: (draftId: string, teamId: string, playerId: string) =>
    apiRequest<{ player_ids: string[] }>(`/api/v1/drafts/${draftId}/queue/remove`, {
      method: "POST",
      body: { team_id: teamId, player_id: playerId },
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
  getCombinedStandings: (leagueId: string) =>
    apiRequest(`/api/v1/leagues/${leagueId}/standings/combined`),
  getWeeklyScores: (leagueId: string, week: number, year: number) =>
    apiRequest(`/api/v1/leagues/${leagueId}/standings/weekly?week=${week}&year=${year}`),
  calculateWeek: (leagueId: string, week: number, year: number) =>
    apiRequest(`/api/v1/leagues/${leagueId}/standings/calculate?week=${week}&year=${year}`, {
      method: "POST",
    }),
  getSchedule: (leagueId: string, year: number, weeks = 14) =>
    apiRequest(`/api/v1/leagues/${leagueId}/standings/schedule?year=${year}&weeks=${weeks}`),
};

// The real, live "what NFL week is it right now" -- straight from
// Sleeper (see backend's app/api/v1/nfl.py), not a frontend guess. The
// single source every page uses to decide which week's scores to show
// by default.
export const nflApi = {
  // Shared and cached (src/lib/current-week.ts): every page asking for the
  // current week gets the same answer from one request. Rejects on failure
  // like before, so existing .catch(() => null) callers are unchanged.
  getCurrentWeek: async () => {
    const s = await getCurrentNflState(() =>
      apiRequest<{ season: number; week: number; season_type: string }>("/api/v1/nfl/current-week"),
    );
    if (!s) throw new Error("Couldn't load the current NFL week");
    return s as { season: number; week: number; season_type: string };
  },
  /** When the Sleeper stats and ESPN scoreboard syncs last ran. Public. */
  getSyncStatus: () => apiRequest<SyncStatus>("/api/v1/nfl/sync-status"),
};

// AI
export const aiApi = {
  lineup: (teamId: string) =>
    apiRequest("/api/v1/ai/lineup", {
      method: "POST",
      body: { team_id: teamId },
    }),
  /** Async variant: returns a job id immediately; poll with job(). */
  startLineupJob: (teamId: string) =>
    apiRequest<{ job_id: string; status: string }>("/api/v1/ai/lineup/jobs", {
      method: "POST",
      body: { team_id: teamId },
    }),
  job: (jobId: string) =>
    apiRequest<{ job_id: string; status: "pending" | "done" | "error"; analysis?: string | null; error?: string | null }>(
      `/api/v1/ai/jobs/${jobId}`
    ),
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
  teamComparison: (teamAId: string, teamBId: string) =>
    apiRequest("/api/v1/ai/team-comparison", {
      method: "POST",
      body: { team_a_id: teamAId, team_b_id: teamBId },
    }),
  playerComparison: (playerAId: string, playerBId: string, leagueId: string) =>
    apiRequest("/api/v1/ai/player-comparison", {
      method: "POST",
      body: { player_a_id: playerAId, player_b_id: playerBId, league_id: leagueId },
    }),
  // Past results for one tool, newest first -- leagueId narrows
  // Lineup/Trade/team_compare/player_compare to the currently-selected
  // league; Bet has none, so callers just omit it.
  history: (
    analysisType: "lineup" | "trade" | "bet" | "team_compare" | "player_compare",
    leagueId?: string
  ) =>
    apiRequest(
      `/api/v1/ai/history?analysis_type=${analysisType}${leagueId ? `&league_id=${leagueId}` : ""}`
    ),
};

// Per-team AI player news digest (2026-09-22) -- refreshed roughly
// once daily by the scheduler; generate() is the manual fallback (the
// very first generation, or a fresher read before the next tick).
export const teamNewsApi = {
  get: (teamId: string) => apiRequest(`/api/v1/teams/${teamId}/news`),
  generate: (teamId: string) =>
    apiRequest(`/api/v1/teams/${teamId}/news/generate`, { method: "POST" }),
};

// Dashboard AI Summaries -- NFL-wide panels (top real performers, NFL
// scores + funny recap), auto-generated by the scheduler; the /generate
// endpoints here are just the manual fallback (e.g. before the first
// scheduler tick ever fires), open to any authenticated user since
// there's no "commissioner" of a global, not-per-league panel.
export const dashboardApi = {
  getTopPerformers: () => apiRequest("/api/v1/dashboard/top-performers"),
  generateTopPerformers: (week: number, year: number) =>
    apiRequest(`/api/v1/dashboard/top-performers/generate?week=${week}&year=${year}`, { method: "POST" }),
  getNflScores: () => apiRequest("/api/v1/dashboard/nfl-scores"),
  generateNflScores: (week: number, year: number, seasonType = 2) =>
    apiRequest(`/api/v1/dashboard/nfl-scores/generate?week=${week}&year=${year}&season_type=${seasonType}`, { method: "POST" }),
};

// Read-only dev/management dashboard -- 403s server-side for anyone
// whose account isn't User.is_admin. See app/api/v1/admin.py.
export const adminApi = {
  getStats: () => apiRequest("/api/v1/admin/stats"),
  getUsers: (params: { q?: string; status?: string; limit?: number; offset?: number } = {}) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") qs.set(k, String(v));
    const query = qs.toString();
    return apiRequest(`/api/v1/admin/users${query ? `?${query}` : ""}`);
  },
  suspendUser: (userId: string, reason?: string) =>
    apiRequest(`/api/v1/admin/users/${userId}/suspend`, { method: "POST", body: { reason: reason || null } }),
  unsuspendUser: (userId: string) => apiRequest(`/api/v1/admin/users/${userId}/unsuspend`, { method: "POST" }),
  forceLogoutUser: (userId: string) => apiRequest(`/api/v1/admin/users/${userId}/force-logout`, { method: "POST" }),
  sendPasswordReset: (userId: string) => apiRequest(`/api/v1/admin/users/${userId}/send-password-reset`, { method: "POST" }),
  resendVerification: (userId: string) => apiRequest(`/api/v1/admin/users/${userId}/resend-verification`, { method: "POST" }),
  setUserAdmin: (userId: string, isAdmin: boolean) =>
    apiRequest(`/api/v1/admin/users/${userId}/admin`, { method: "POST", body: { is_admin: isAdmin } }),
  getAuditLog: (params: { target_id?: string; limit?: number; offset?: number } = {}) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") qs.set(k, String(v));
    const query = qs.toString();
    return apiRequest(`/api/v1/admin/audit-log${query ? `?${query}` : ""}`);
  },
  getLeagues: () => apiRequest("/api/v1/admin/leagues"),
  getLeagueDetail: (leagueId: string) => apiRequest(`/api/v1/admin/leagues/${leagueId}`),
  deleteLeague: (leagueId: string) =>
    apiRequest(`/api/v1/admin/leagues/${leagueId}`, { method: "DELETE" }),
  deleteUser: (userId: string) =>
    apiRequest(`/api/v1/admin/users/${userId}`, { method: "DELETE" }),
  getAiUsage: () => apiRequest("/api/v1/admin/ai-usage"),
  getAiCost: (days = 14) => apiRequest(`/api/v1/admin/ai-cost?days=${days}`),
  getLeagueHealth: () => apiRequest("/api/v1/admin/league-health"),
  getSystemHealth: () => apiRequest("/api/v1/admin/system-health"),
  getEmailLog: (status?: string) =>
    apiRequest(`/api/v1/admin/email-log${status ? `?status=${status}` : ""}`),
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
  analyzeTradeForReview: (leagueId: string, tradeId: string) =>
    apiRequest(`/api/v1/leagues/${leagueId}/commissioner/trades/${tradeId}/analyze`, {
      method: "POST",
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

  // AI Commissioner Digest (Phase 8)
  generateDigest: (leagueId: string, week: number, year: number, tone = "professional", length = "full") =>
    apiRequest(`/api/v1/leagues/${leagueId}/commissioner/digest/generate?week=${week}&year=${year}&tone=${tone}&length=${length}`, {
      method: "POST",
    }),
  getDigest: (leagueId: string, week: number, year: number) =>
    apiRequest(`/api/v1/leagues/${leagueId}/commissioner/digest?week=${week}&year=${year}`),

  // Dashboard AI Summaries -- per-team weekly recap manual fallback
  // (normally auto-generated by the scheduler; see leaguesApi.getTeamRecap
  // for the open read every manager actually uses).
  generateTeamRecap: (leagueId: string, week: number, year: number) =>
    apiRequest(`/api/v1/leagues/${leagueId}/commissioner/team-recap/generate?week=${week}&year=${year}`, {
      method: "POST",
    }),

  // League Health Dashboard (AI Co-Commissioner v1)
  getLeagueHealth: (leagueId: string) =>
    apiRequest(`/api/v1/leagues/${leagueId}/commissioner/health`),

  // Scoring & Rule Balance Insights (AI Co-Commissioner v1, Phase 2)
  getScoringInsights: (leagueId: string) =>
    apiRequest(`/api/v1/leagues/${leagueId}/commissioner/insights`),

  // Schedule & Strength-of-Schedule Tools (AI Co-Commissioner v1, Phase 2)
  getScheduleInsights: (leagueId: string) =>
    apiRequest(`/api/v1/leagues/${leagueId}/commissioner/schedule-insights`),

  // Communication Helpers (AI Co-Commissioner v1, Phase 2)
  draftMessage: (leagueId: string, messageType: string, tone: string, customContext?: string) =>
    apiRequest(`/api/v1/leagues/${leagueId}/commissioner/messages/draft`, {
      method: "POST",
      body: { message_type: messageType, tone, custom_context: customContext || undefined },
    }),
  sendMessage: (leagueId: string, messageType: string, content: string) =>
    apiRequest(`/api/v1/leagues/${leagueId}/commissioner/messages/send`, {
      method: "POST",
      body: { message_type: messageType, content },
    }),

  // AI Co-Commissioner Chat (AI Co-Commissioner v1, deferred item 7)
  getChatHistory: (leagueId: string) =>
    apiRequest(`/api/v1/leagues/${leagueId}/commissioner/chat`),
  sendChatMessage: (leagueId: string, message: string) =>
    apiRequest(`/api/v1/leagues/${leagueId}/commissioner/chat`, {
      method: "POST",
      body: { message },
    }),
  clearChatHistory: (leagueId: string) =>
    apiRequest(`/api/v1/leagues/${leagueId}/commissioner/chat`, {
      method: "DELETE",
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
  cancel: (leagueId: string, tradeId: string) =>
    apiRequest(`/api/v1/leagues/${leagueId}/trades/${tradeId}/cancel`, { method: "POST" }),
  respond: (leagueId: string, tradeId: string, action: "accept" | "decline") =>
    apiRequest(`/api/v1/leagues/${leagueId}/trades/${tradeId}/respond`, { method: "POST", body: { action } }),
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
