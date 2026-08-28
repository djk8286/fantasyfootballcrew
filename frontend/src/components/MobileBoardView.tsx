"use client";

// Mobile-friendly replacement for BoardView's round x team grid -- David
// called that grid unreadable on a phone (too many narrow columns). This
// shows the same "who's drafted what" information as a stack of
// per-team roster cards instead, reusing TeamRosterCard (the exact style
// he pointed to as what he wanted here) -- one card per team, each
// showing that team's full position-grouped roster, no nested scroll
// containers or tiny columns to squint at.
import TeamRosterCard, { TeamRosterCardPick } from "./TeamRosterCard";

interface MobileBoardViewProps {
  team_order: string[];
  teams: Record<string, { name: string }>;
  teamRosters: Record<string, TeamRosterCardPick[]>;
  myTeamId: string | null;
  onPlayerHover: (player: any, el: HTMLElement | null) => void;
}

export default function MobileBoardView({
  team_order,
  teams,
  teamRosters,
  myTeamId,
  onPlayerHover,
}: MobileBoardViewProps) {
  const uniqueTeams = team_order.filter((tid, i, arr) => arr.indexOf(tid) === i);

  return (
    <div className="space-y-4">
      {uniqueTeams.map((tid) => (
        <TeamRosterCard
          key={tid}
          teamName={teams[tid]?.name || "Team"}
          isMine={tid === myTeamId}
          picks={teamRosters[tid] || []}
          emptyLabel="No picks yet."
          onPlayerHover={onPlayerHover}
        />
      ))}
    </div>
  );
}
