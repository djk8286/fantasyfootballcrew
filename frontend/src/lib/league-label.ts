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
