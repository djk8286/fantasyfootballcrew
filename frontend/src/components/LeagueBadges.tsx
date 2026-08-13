"use client";

import { Users, Swords, Lock, Unlock, ShieldCheck, Skull } from "lucide-react";

// Shared definitions used everywhere a league's type/visibility/open-spot
// count needs to render -- the leagues grid, the Wanted Board, and the
// league detail page header (which previously had its own separate
// inline conference badge markup). One definition here means changing
// how a badge looks only ever needs to happen in one place.

export const LEAGUE_TYPE_LABELS: Record<string, string> = {
  standard: "Standard",
  two_man: "2-Man",
  conference: "Conference",
  guillotine: "Guillotine",
};

const LEAGUE_TYPE_ICONS: Record<string, typeof Users> = {
  standard: Users,
  two_man: Users,
  conference: Swords,
  guillotine: Skull,
};

export function LeagueTypeBadge({ leagueType }: { leagueType: string }) {
  const Icon = LEAGUE_TYPE_ICONS[leagueType] || Users;
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-surface-400">
      <Icon className="w-3.5 h-3.5" />
      {LEAGUE_TYPE_LABELS[leagueType] || leagueType}
    </span>
  );
}

const VISIBILITY_LABELS: Record<string, string> = {
  private: "Private",
  invite_only: "Invite Only",
  open: "Open",
};

const VISIBILITY_ICONS: Record<string, typeof Lock> = {
  private: Lock,
  invite_only: ShieldCheck,
  open: Unlock,
};

const VISIBILITY_COLORS: Record<string, string> = {
  private: "text-surface-400 bg-surface-800 border-surface-700",
  invite_only: "text-blue-400 bg-blue-400/10 border-blue-400/20",
  open: "text-green-400 bg-green-400/10 border-green-400/20",
};

export function VisibilityBadge({ visibility }: { visibility?: string | null }) {
  if (!visibility) return null;
  const Icon = VISIBILITY_ICONS[visibility] || Unlock;
  return (
    <span
      className={`inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full border shrink-0 ${
        VISIBILITY_COLORS[visibility] || VISIBILITY_COLORS.open
      }`}
    >
      <Icon className="w-3 h-3" />
      {VISIBILITY_LABELS[visibility] || visibility}
    </span>
  );
}

export function OpenSpotsBadge({ teamCount, maxTeams }: { teamCount: number | null; maxTeams: number }) {
  const count = teamCount ?? 0;
  const slotsOpen = maxTeams - count;
  const isFull = slotsOpen <= 0;
  return isFull ? (
    <span className="text-xs text-surface-500 font-semibold shrink-0">Full</span>
  ) : (
    <span className="text-xs text-gold-400 font-semibold shrink-0">
      {slotsOpen} slot{slotsOpen !== 1 ? "s" : ""} open
    </span>
  );
}

// Guillotine (Phase 4) -- Team.eliminated_week is null (alive) or the
// week a team was eliminated. Styled like ConferenceBadge's small pill,
// but red-toned since elimination is a stronger status signal than
// conference membership.
export function EliminatedBadge({ week }: { week: number }) {
  return (
    <span className="inline-flex items-center gap-1 text-[10px] text-red-400 font-semibold uppercase tracking-wider bg-red-400/10 border border-red-400/20 px-1.5 py-0.5 rounded shrink-0">
      Eliminated Wk {week}
    </span>
  );
}

export function ConferenceBadge({ conference, displayName }: { conference?: string | null; displayName?: string | null }) {
  if (!conference) return null;
  return (
    <span className="text-[10px] text-surface-400 font-semibold uppercase tracking-wider bg-surface-700/60 px-1.5 py-0.5 rounded shrink-0">
      {displayName || `Conf ${conference}`}
    </span>
  );
}

// Enhanced Conference/Rivalry (Phase 3) -- a commissioner can name their
// two conferences (League.conference_a_name/conference_b_name, both
// nullable). These resolve "A"/"B" to the custom name if set, falling
// back to the short badge form ("Conf A") or the full heading form
// ("Conference A") otherwise. Kept as plain functions (not components)
// since callers need the resolved string, not JSX -- e.g. to build a
// button's title attribute, not just to render text.
export function conferenceShortLabel(
  conference: string | null | undefined,
  aName?: string | null,
  bName?: string | null,
): string | undefined {
  if (!conference) return undefined;
  const custom = conference === "A" ? aName : conference === "B" ? bName : null;
  return custom || `Conf ${conference}`;
}

export function conferenceFullLabel(
  conference: string | null | undefined,
  aName?: string | null,
  bName?: string | null,
): string {
  const custom = conference === "A" ? aName : conference === "B" ? bName : null;
  return custom || `Conference ${conference}`;
}
