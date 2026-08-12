// Pure draft-state math shared between MobileDraftRoom and the desktop
// draft room -- pulled out of MobileDraftRoom (where it was built first)
// so both use the exact same tested logic instead of two copies that can
// drift. No backend calls, no React -- everything here operates on data
// the draft state response already includes.

// Global pick index (0-based, matches team_order's indexing) -> "round.pick"
// display, e.g. index 39 in a 12-team draft is round 4 (indices 36-47),
// pick 4 within that round -> "4.04".
export function formatPickLabel(globalIndex: number, numTeams: number): string {
  if (numTeams <= 0) return "";
  const round = Math.floor(globalIndex / numTeams) + 1;
  const pickInRound = (globalIndex % numTeams) + 1;
  return `${round}.${String(pickInRound).padStart(2, "0")}`;
}

// How many picks (including CPU/other-human picks) happen before it's
// myTeamId's turn again, counting from currentIndex. 0 means it's already
// my turn. null means I don't have a claimed team, or I'm not in this
// draft's team_order at all.
export function picksUntilMyTurn(teamOrder: string[], currentIndex: number, myTeamId: string | null): number | null {
  if (!myTeamId) return null;
  for (let i = currentIndex; i < teamOrder.length; i++) {
    if (teamOrder[i] === myTeamId) return i - currentIndex;
  }
  return null;
}

// Best-available-at-a-position-of-need, falling back to pure best-player-
// available. Not a real projections model (this app doesn't have one) --
// a simple, honest heuristic: standard starter counts per position, most-
// short-handed need first, tie-broken by rank; once every modeled slot is
// filled, just the single best-ranked player left. availablePlayers is
// assumed already sorted best-to-worst by rank_score.
export const STARTER_SLOTS: Record<string, number> = { QB: 1, RB: 2, WR: 2, TE: 1, K: 1, DEF: 1 };

export function projectNextPick<P extends { id: string; position: string }>(
  availablePlayers: P[],
  myRosterByPos: Record<string, unknown[]>
): { player: P; reason: string } | null {
  if (availablePlayers.length === 0) return null;

  const needs = Object.entries(STARTER_SLOTS)
    .map(([pos, need]) => ({ pos, short: need - (myRosterByPos[pos]?.length || 0) }))
    .filter((n) => n.short > 0)
    .sort((a, b) => b.short - a.short);

  for (const need of needs) {
    const best = availablePlayers.find((p) => p.position === need.pos);
    if (best) {
      return { player: best, reason: `Fills your ${need.pos} need` };
    }
  }
  return { player: availablePlayers[0], reason: "Best player available" };
}
