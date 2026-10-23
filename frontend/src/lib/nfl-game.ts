export interface NflGameScore {
  home_score: number | null;
  away_score: number | null;
  status_state?: string | null;
  completed: boolean;
}

/** "away - home" once the game is live or final, else null. ESPN reports
 * 0-0 for games that haven't been played, postponed and canceled ones
 * included, so the state decides, not the numbers. */
export function nflScoreLine(g: NflGameScore): string | null {
  const played = g.completed || g.status_state === "in";
  if (!played || g.home_score == null || g.away_score == null) return null;
  return `${g.away_score} - ${g.home_score}`;
}

/** True when a game has no score and won't kick off as scheduled, such as
 * ESPN's postponed or canceled games, which arrive as "post" but not completed. */
export function nflGameOffSchedule(g: NflGameScore): boolean {
  return !g.completed && g.status_state != null && g.status_state !== "pre" && g.status_state !== "in";
}
