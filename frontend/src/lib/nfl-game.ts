export interface NflGameScore {
  home_score: number | null;
  away_score: number | null;
  status_state?: string | null;
  completed: boolean;
}

/** "away - home" once the game has kicked off, else null. ESPN reports a
 * 0-0 score for games that haven't started, so the state decides, not the numbers. */
export function nflScoreLine(g: NflGameScore): string | null {
  const started = g.completed || (g.status_state != null && g.status_state !== "pre");
  if (!started || g.home_score == null || g.away_score == null) return null;
  return `${g.away_score} - ${g.home_score}`;
}
