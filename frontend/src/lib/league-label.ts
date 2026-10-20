// Disambiguates leagues that share a name (QA round 2 #10): when two of the
// listed leagues have the same name, append the created date (and a short id
// if the dates also match) so the user can tell them apart.
export interface LabelableLeague {
  id: string;
  name: string;
  created_at?: string | null;
}

function shortDate(iso?: string | null): string {
  if (!iso) return "";
  // Naive timestamps (no Z/offset) are UTC from the API.
  const hasZone = /[zZ]|[+-]\d\d:?\d\d$/.test(iso);
  const d = new Date(hasZone ? iso : iso.replace(" ", "T") + "Z");
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export function leagueLabel(league: LabelableLeague, all: LabelableLeague[]): string {
  const same = all.filter((l) => l.name === league.name);
  if (same.length < 2) return league.name;
  const date = shortDate(league.created_at);
  const dateClash = same.filter((l) => shortDate(l.created_at) === date).length > 1;
  const parts = [date ? `created ${date}` : "", !date || dateClash ? `#${league.id.slice(0, 6)}` : ""].filter(Boolean);
  return `${league.name} (${parts.join(", ")})`;
}

/** AI "Recent" entries are saved as "<team> — <league name>"; when the
 * user has two leagues with that name, swap in the disambiguated label
 * (QA 2026-10-19: identical "QA Tester Team — QA Test League" rows). */
export function historySummaryLabel(
  item: { summary: string; league_id: string | null },
  leagues: LabelableLeague[],
): string {
  const league = item.league_id ? leagues.find((l) => l.id === item.league_id) : undefined;
  if (!league) return item.summary;
  const suffix = ` — ${league.name}`;
  const label = leagueLabel(league, leagues);
  if (label === league.name) return item.summary;
  return item.summary.endsWith(suffix)
    ? item.summary.slice(0, -suffix.length) + ` — ${label}`
    : `${item.summary} (${label})`;
}

/** Labels for the league header switcher: the current league and the
 * user's other leagues, disambiguated the same way as the dashboard and
 * AI pages (QA 2026-10-19: two "QA Test League" rows in the switcher). */
export function switcherLabels(
  current: LabelableLeague,
  mine: LabelableLeague[],
): { current: string; others: { id: string; label: string }[] } {
  const all = mine.some((l) => l.id === current.id) ? mine : [current, ...mine];
  return {
    current: leagueLabel(current, all),
    others: mine.filter((l) => l.id !== current.id).map((l) => ({ id: l.id, label: leagueLabel(l, all) })),
  };
}
