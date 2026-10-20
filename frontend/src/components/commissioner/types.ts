export interface AdminTeam {
  id: string;
  name: string;
  owner_id: string | null;
  co_owner_id: string | null;
  avatar_url: string | null;
  is_cpu: boolean;
  conference: string | null;
  owner_username?: string | null;
  co_owner_username?: string | null;
}

export interface AdminLeague {
  id: string;
  name: string;
  description: string | null;
  commissioner_id: string;
  co_commissioner_ids: string[] | null;
  league_type: string;
  max_teams: number;
  draft_status: string;
  visibility: "private" | "invite_only" | "open";
  wanted_board_hidden: boolean;
  conference_a_name: string | null;
  conference_b_name: string | null;
}

export const fieldClass =
  "h-9 w-full rounded-control border border-ink-700 bg-ink-950 px-3 text-sm text-ink-100 placeholder:text-ink-400 focus:outline-none focus:ring-2 focus:ring-gold/60";
