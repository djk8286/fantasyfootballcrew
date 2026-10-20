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
