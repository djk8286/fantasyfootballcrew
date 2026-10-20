export interface Slot {
  slot: string;
  player_id: string | null;
}

export interface LineupPlayer {
  id: string;
  name: string;
  position: string;
  injuryStatus: string | null;
  locked: boolean;
  onBye: boolean;
}

/** A tapped row: a starting slot (maybe empty) or a bench player. */
export type Pick = { kind: "slot"; index: number } | { kind: "bench"; playerId: string };

export interface Targets {
  slots: Set<number>;
  bench: Set<string>;
  /** The picked starter can be moved to the bench without a replacement. */
  toBench: boolean;
}

export type IssueKind = "empty" | "out" | "bye";

export interface Issue {
  kind: IssueKind;
  slotIndex: number;
  playerId: string | null;
  message: string;
}

const ELIGIBLE: Record<string, readonly string[]> = {
  QB: ["QB"],
  RB: ["RB"],
  WR: ["WR"],
  TE: ["TE"],
  FLEX: ["RB", "WR", "TE"],
  SUPERFLEX: ["QB", "RB", "WR", "TE"],
  K: ["K"],
  DEF: ["DEF"],
  DL: ["DL"],
  LB: ["LB"],
  DB: ["DB"],
  IDP_FLEX: ["DL", "LB", "DB"],
};

// Sleeper designations that mean "won't play". Mirrors the backend's INACTIVE_STATUSES.
const INACTIVE = new Set(["out", "ir", "pup", "sus", "suspended", "na"]);

export function isInactive(status: string | null | undefined): boolean {
  return !!status && INACTIVE.has(status.trim().toLowerCase());
}

export function canPlay(slot: string, position: string | null | undefined): boolean {
  return !!position && (ELIGIBLE[slot] ?? []).includes(position);
}

export function benchIds(slots: readonly Slot[], rosterIds: readonly string[]): string[] {
  const starting = new Set(slots.map((s) => s.player_id).filter(Boolean));
  return rosterIds.filter((id) => !starting.has(id));
}

/** Where the picked row can go. Locked players are never picked or targeted. */
export function targetsFor(
  slots: readonly Slot[],
  pick: Pick,
  players: Record<string, LineupPlayer>,
  bench: readonly string[],
): Targets {
  const none: Targets = { slots: new Set(), bench: new Set(), toBench: false };
  const movable = (id: string | null) => !id || !players[id]?.locked;
  const pos = (id: string | null) => (id ? players[id]?.position : null);

  if (pick.kind === "bench") {
    const p = players[pick.playerId];
    if (!p || p.locked) return none;
    const slotTargets = slots.flatMap((s, i) => (canPlay(s.slot, p.position) && movable(s.player_id) ? [i] : []));
    return { slots: new Set(slotTargets), bench: new Set(), toBench: false };
  }

  const from = slots[pick.index];
  if (!from || !movable(from.player_id)) return none;
  const slotTargets = slots.flatMap((s, i) => {
    if (i === pick.index || !movable(s.player_id)) return [];
    const fits = from.player_id === null || canPlay(s.slot, pos(from.player_id));
    const back = s.player_id === null || canPlay(from.slot, pos(s.player_id));
    return fits && back && (from.player_id || s.player_id) ? [i] : [];
  });
  const benchTargets = bench.filter((id) => movable(id) && canPlay(from.slot, pos(id)));
  return { slots: new Set(slotTargets), bench: new Set(benchTargets), toBench: from.player_id !== null };
}

/** The slots after moving `pick` onto `target`: a swap, or a bench player taking a slot. */
export function applyMove(slots: readonly Slot[], pick: Pick, target: Pick | "bench"): Slot[] {
  const next = slots.map((s) => ({ ...s }));
  if (target === "bench") {
    if (pick.kind === "slot") next[pick.index].player_id = null;
    return next;
  }
  if (pick.kind === "slot" && target.kind === "slot") {
    const a = next[pick.index].player_id;
    next[pick.index].player_id = next[target.index].player_id;
    next[target.index].player_id = a;
    return next;
  }
  const slotIndex = pick.kind === "slot" ? pick.index : (target as { index: number }).index;
  const benchId = pick.kind === "bench" ? pick.playerId : (target as { playerId: string }).playerId;
  next[slotIndex].player_id = benchId;
  return next;
}

/** Why this player won't score, or null if he should. */
export function playerWarning(p: LineupPlayer): { kind: "bye" | "out"; message: string } | null {
  if (p.onBye) return { kind: "bye", message: `${p.name} is on bye and won't score.` };
  if (isInactive(p.injuryStatus)) return { kind: "out", message: `${p.name} is listed ${p.injuryStatus} and may not play.` };
  return null;
}

/** What will cost points, in slot order. Same rules as the server's lineup_issues. */
export function issuesFor(slots: readonly Slot[], players: Record<string, LineupPlayer>): Issue[] {
  return slots.flatMap((s, i): Issue[] => {
    if (!s.player_id) return [{ kind: "empty", slotIndex: i, playerId: null, message: `Your ${s.slot} slot is empty.` }];
    const p = players[s.player_id];
    const w = p ? playerWarning(p) : null;
    return w ? [{ kind: w.kind, slotIndex: i, playerId: p.id, message: w.message }] : [];
  });
}

/** The warning a move would add, shown on the target before the user commits.
 * Null when the move starts nobody new who won't score. */
export function moveWarning(
  slots: readonly Slot[],
  pick: Pick,
  target: Pick,
  players: Record<string, LineupPlayer>
): string | null {
  const before = new Set(issuesFor(slots, players).flatMap((i) => (i.playerId ? [i.playerId] : [])));
  const added = issuesFor(applyMove(slots, pick, target), players).find((i) => i.playerId && !before.has(i.playerId));
  return added ? added.message : null;
}

/** Projected points for the players in these slots. Null when the week
 * has no projections, so the UI can show "—" instead of a fake 0. */
export function projectedTotal(
  slots: readonly Slot[],
  projected: Record<string, number | null | undefined>,
  available: boolean,
): number | null {
  if (!available) return null;
  const sum = slots.reduce((t, s) => t + (s.player_id ? projected[s.player_id] ?? 0 : 0), 0);
  return Math.round(sum * 100) / 100;
}

/** Why the lineup didn't load, from the GET /lineup status (null = network
 * or unknown). "login" -> show a log-in prompt instead of an error. */
export type LineupLoadProblem = { kind: "login" } | { kind: "message"; text: string };

export function lineupLoadProblem(status: number | null): LineupLoadProblem {
  if (status === 401) return { kind: "login" };
  if (status === 403) return { kind: "message", text: "This league is private. Only its members can see lineups." };
  if (status === 404) return { kind: "message", text: "We couldn't find this team." };
  return { kind: "message", text: "Couldn't load this lineup. Try again in a moment." };
}
