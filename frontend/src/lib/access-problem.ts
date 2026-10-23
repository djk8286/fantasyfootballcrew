/** Why a league-scoped read failed, from its HTTP status (null = network
 * or unknown). Rosters are public for open and invite-only leagues; lineups
 * need a login; private leagues are members-only (backend deps.can_view_*).
 * "login" -> show a log-in prompt instead of an error. */
export type LoadProblem = { kind: "login"; text: string } | { kind: "message"; text: string };

const LOGIN_TEXT = { lineup: "to see this lineup.", team: "to see this team.", league: "to see this league." } as const;
const RETRY_TEXT = {
  lineup: "Couldn't load this lineup. Try again in a moment.",
  team: "Couldn't load this team. Try again in a moment.",
  league: "Couldn't load this week. Try again in a moment.",
} as const;

export function loadProblem(status: number | null, what: keyof typeof LOGIN_TEXT): LoadProblem {
  if (status === 401) return { kind: "login", text: LOGIN_TEXT[what] };
  if (status === 403) {
    return {
      kind: "message",
      text: what === "lineup" ? "This league is private. Only its members can see lineups." : "This league is private. Only its members can see it.",
    };
  }
  if (status === 404) return { kind: "message", text: what === "league" ? "We couldn't find this league." : "We couldn't find this team." };
  return { kind: "message", text: RETRY_TEXT[what] };
}

/** Pulls the status off an ApiError-like rejection. */
export function errorStatus(err: unknown): number | null {
  const s = (err as { status?: unknown } | null)?.status;
  return typeof s === "number" ? s : null;
}

/** A PRIVATE league the viewer can't read: GET /leagues/{id} answers 401
 * (guest) or 403 (logged in, not a member or invitee) with only
 * {id, name, visibility[, viewer_join_status]} in detail.league. */
export interface LeagueGate {
  kind: "login" | "private";
  name: string | null;
  invited: boolean;
}

export function leagueGate(err: unknown): LeagueGate | null {
  const status = errorStatus(err);
  if (status !== 401 && status !== 403) return null;
  const detail = (err as { detail?: unknown } | null)?.detail;
  const league = (detail && typeof detail === "object" ? (detail as { league?: unknown }).league : null) as
    | { name?: unknown; viewer_join_status?: unknown }
    | null
    | undefined;
  return {
    kind: status === 401 ? "login" : "private",
    name: typeof league?.name === "string" ? league.name : null,
    invited: league?.viewer_join_status === "invited",
  };
}

/** `raw` when it's a path on this site, else `fallback`. Parsed the way the
 * browser will parse it, so "//evil.com", "/\evil.com" and a tab or
 * newline that collapses into "//" are all refused. */
export function safeNext(raw: string | null | undefined, fallback = "/dashboard"): string {
  if (!raw || !raw.startsWith("/") || raw.includes("\\")) return fallback;
  const base = "https://ffc.invalid";
  try {
    const url = new URL(raw, base);
    const path = `${url.pathname}${url.search}${url.hash}`;
    // Dot segments can normalize "/.//evil.com" to "//evil.com", which the router reads as another host.
    return url.origin === base && !path.startsWith("//") && !path.startsWith("/\\") ? path : fallback;
  } catch {
    return fallback;
  }
}

/** The log-in link for the page the viewer is on, query string kept. */
export function loginHref(pathname: string, search: string): string {
  const next = safeNext(search ? `${pathname}?${search.replace(/^\?/, "")}` : pathname, "/");
  return `/login?next=${encodeURIComponent(next)}`;
}
