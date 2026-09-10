import { getCurrentUserId } from "@/lib/api-client";

/** Minimal shape every league-settings page's own `league` state needs to
 * carry for this check -- just the two fields require_commissioner checks
 * server-side (app/api/deps.py), nothing else. */
export interface LeagueManagerInfo {
  commissioner_id?: string | null;
  co_commissioner_ids?: string[] | null;
}

/** Client-side mirror of the backend's require_commissioner check (see
 * app/api/deps.py). Every one of these settings pages' mutating calls
 * already 403s server-side for anyone who isn't the commissioner or a
 * co-commissioner -- this is purely about not showing the editor UI (and
 * the top-level nav links to it) to a member who was never going to be
 * allowed to save anything, whether they got here via a bookmark, a
 * shared link, browser history, or the league page itself before this
 * fix hid those links for them.
 *
 * Duplicated as a tiny shared helper (not a wrapping component) so each
 * settings page can drop it in as a one-line condition right after its
 * existing loading/error early-returns, without needing to restructure
 * its own JSX tree into a wrapper's children.
 */
export function isLeagueManagerOf(league: LeagueManagerInfo | null | undefined): boolean {
  const viewerId = getCurrentUserId();
  if (!league || !viewerId) return false;
  return viewerId === league.commissioner_id || (league.co_commissioner_ids || []).includes(viewerId);
}
