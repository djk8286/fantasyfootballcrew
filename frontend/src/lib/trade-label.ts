// Readable labels for trade pickers (QA 2026-10-19: every option in the AI
// Trade tab read "pending trade (1 for 1)"). Pure, for tests.

export interface TradeLike {
  id: string;
  team_id: string;
  status: string;
  processed_at?: string | null;
  details?: { target_team_id?: string; offered_player_ids?: string[]; requested_player_ids?: string[] };
}

function names(ids: string[] | undefined, playerName: (id: string) => string | undefined): string {
  const list = (ids || []).map((id) => playerName(id) || "Unknown player");
  if (list.length === 0) return "nothing";
  if (list.length <= 2) return list.join(" + ");
  return `${list.slice(0, 2).join(" + ")} +${list.length - 2} more`;
}

export function tradeOptionLabel(
  t: TradeLike,
  teamName: (id: string) => string | undefined,
  playerName: (id: string) => string | undefined,
): string {
  const status = t.status ? t.status[0].toUpperCase() + t.status.slice(1) : "Trade";
  const from = teamName(t.team_id) || "Unknown team";
  const to = teamName(t.details?.target_team_id || "") || "Unknown team";
  return `${status}: ${from} gives ${names(t.details?.offered_player_ids, playerName)} to ${to} for ${names(t.details?.requested_player_ids, playerName)}`;
}

/** Default Team A / Team B for Compare Teams: the viewer's own team first
 * (if they have one in this league), and always two different teams. */
export function defaultComparePair(
  teams: { id: string; owner_id?: string | null; co_owner_id?: string | null }[],
  userId: string | null,
): [string, string] {
  if (teams.length === 0) return ["", ""];
  const mine = userId ? teams.find((t) => t.owner_id === userId || t.co_owner_id === userId) : undefined;
  const a = (mine ?? teams[0]).id;
  const b = teams.find((t) => t.id !== a)?.id ?? "";
  return [a, b];
}

export interface TradeAnswer {
  team_id: string;
  status: string;
  details?: {
    target_team_id?: string;
    cpu_response?: "accepted" | "rejected";
    recipient_response?: "accepted" | "declined";
  };
}

/** The receiving team (human or CPU) said yes, so the commissioner can approve. */
export function tradeAccepted(details?: Record<string, unknown>): boolean {
  return details?.recipient_response === "accepted" || details?.cpu_response === "accepted";
}

/** What a pending trade is waiting on, and what this viewer can do about it. */
export function pendingTradeView(
  t: TradeAnswer,
  myTeamIds: string[],
  teamName: (id: string) => string | undefined,
): { note: string | null; canRespond: boolean; canCancel: boolean } {
  if (t.status !== "pending") return { note: null, canRespond: false, canCancel: false };
  const target = t.details?.target_team_id || "";
  const canCancel = myTeamIds.includes(t.team_id);
  if (tradeAccepted(t.details)) {
    const who = t.details?.cpu_response ? "" : `${teamName(target) || "They"} accepted. `;
    return { note: `${who}Awaiting commissioner approval.`, canRespond: false, canCancel };
  }
  const canRespond = myTeamIds.includes(target);
  const note = canRespond ? "Your answer is needed." : `Waiting on ${teamName(target) || "the other team"} to accept or decline.`;
  return { note, canRespond, canCancel };
}
