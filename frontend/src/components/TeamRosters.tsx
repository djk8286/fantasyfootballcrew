"use client";

import { Star } from "lucide-react";
import PositionBadge, { POSITION_ORDER } from "./PositionBadge";
import { PlayerAvatar } from "./PlayerAvatar";

interface TeamRosterPick {
  id: string;
  pick_number: number;
  player?: {
    id: string;
    full_name: string;
    position: string;
    team: string;
    number?: number | null;
    age?: number | null;
    bye_week?: number | null;
    injury_status?: string | null;
    fantasy_positions?: string[] | null;
    avatar_url?: string | null;
    sleeper_id?: string | null;
    rank_score?: number;
    pos_rank?: number;
    headline_stats?: Record<string, number> | null;
  } | null;
  team: { id: string; name: string };
}

interface TeamRostersProps {
  myTeamId: string | null;
  team_order: string[];
  teams: Record<string, { name: string }>;
  teamRosters: Record<string, TeamRosterPick[]>;
  // Which single team's roster is shown -- shared with the desktop
  // draft-train's tap-to-select circles (DraftHeader.tsx) and mobile's
  // own equivalent, so switching teams from either place stays in sync.
  selectedTeamId: string | null;
  onSelectTeamId: (teamId: string) => void;
  onClaimTeam: (teamId: string) => void;
  onUnclaimTeam: () => void;
  onPlayerHover: (player: any, el: HTMLElement | null) => void;
}

export default function TeamRosters({
  myTeamId,
  team_order,
  teams,
  teamRosters,
  selectedTeamId,
  onSelectTeamId,
  onClaimTeam,
  onUnclaimTeam,
  onPlayerHover,
}: TeamRostersProps) {
  const selectedTeamPicks = (selectedTeamId && teamRosters[selectedTeamId]) || [];
  const selectedTeamByPos: Record<string, TeamRosterPick[]> = {};
  selectedTeamPicks.forEach((p) => {
    const pos = p.player?.position || "UNKNOWN";
    if (!selectedTeamByPos[pos]) selectedTeamByPos[pos] = [];
    selectedTeamByPos[pos].push(p);
  });
  const isViewingMyTeam = selectedTeamId !== null && selectedTeamId === myTeamId;
  const selectedTeamName = selectedTeamId ? teams[selectedTeamId]?.name || "Team" : null;
  return (
    // w-full, not a fixed width -- this only ever renders inside
    // draft/[id]/page.tsx's left column, which is itself already fixed at
    // w-[300px]. An xl:w-[380px] here used to force this component 80px
    // wider than that parent allows, and with no overflow-hidden on the
    // parent that overflow just spilled straight into the center player
    // pool column instead of being clipped -- the actual cause of the
    // reported "left panel overlaps center panel" bug.
    <div className="w-full shrink-0">
      <div className="xl:sticky xl:top-20 space-y-4">
        {/* Single-team roster view -- defaults to (and resets to, on
            claim/unclaim, via draft/[id]/page.tsx's effect) your own
            team; tap a circle in the desktop draft-train above
            (DraftHeader.tsx) to switch which team's picks show here.
            Same pattern as the mobile draft room's roster tab, replacing
            the old "My Team fixed + accordion of every other team" layout
            David called too congested. */}
        <div className="bg-surface-800/50 border border-surface-700 rounded-2xl overflow-hidden">
          <div className="px-4 py-3 border-b border-surface-700 flex items-center justify-between">
            <h2 className="text-xs font-semibold text-surface-400 uppercase tracking-wider flex items-center gap-2">
              {isViewingMyTeam && <Star className="w-3.5 h-3.5 text-gold-400" />}
              {selectedTeamName || "Select a Team"}
            </h2>
            <span className="text-surface-500 text-xs">
              {selectedTeamPicks.length} players
            </span>
          </div>
          {!selectedTeamId ? (
            <div className="p-4 text-center">
              <p className="text-surface-400 text-sm mb-4">
                Claim a team to start drafting
              </p>
              <div className="space-y-1.5">
                {team_order
                  .filter((tId, i, arr) => arr.indexOf(tId) === i)
                  .map((teamId) => {
                    const team = teams[teamId];
                    return (
                      <button
                        key={teamId}
                        onClick={() => onClaimTeam(teamId)}
                        className="w-full flex items-center justify-between px-3 py-2 bg-surface-900 hover:bg-surface-800 border border-surface-700 rounded-lg text-sm transition-all group"
                      >
                        <span className="text-surface-300 group-hover:text-white">
                          {team?.name || "Unknown"}
                        </span>
                        <span className="text-[10px] text-gold-400 opacity-0 group-hover:opacity-100 transition-opacity">
                          Claim →
                        </span>
                      </button>
                    );
                  })}
              </div>
            </div>
          ) : selectedTeamPicks.length === 0 ? (
            <div className="p-6 text-center text-surface-500 text-sm">
              No picks yet. {isViewingMyTeam ? "Your" : `${selectedTeamName}'s`} picks will appear here as the draft goes.
            </div>
          ) : (
            <div className="divide-y divide-surface-800 max-h-130 overflow-y-auto">
              {POSITION_ORDER.filter((pos) => selectedTeamByPos[pos]).map((pos) => (
                <div key={pos}>
                  <div className="px-4 py-1.5 bg-surface-900/30 text-[10px] font-semibold text-surface-500 uppercase tracking-wider">
                    {pos} ({selectedTeamByPos[pos].length})
                  </div>
                  {selectedTeamByPos[pos].map((p) => (
                    <div
                      key={p.id}
                      className="flex items-center gap-2 px-4 py-1.5"
                      onMouseEnter={(e) => p.player && onPlayerHover(p.player, e.currentTarget)}
                      onMouseLeave={() => onPlayerHover(null, null)}
                    >
                      <span className="text-surface-500 text-[10px] font-mono w-4 shrink-0">
                        {p.pick_number}
                      </span>
                      {p.player && <PlayerAvatar player={p.player as any} size="sm" onHover={onPlayerHover} />}
                      <span className="text-sm text-white truncate flex-1">
                        {p.player?.full_name}
                      </span>
                      <PositionBadge pos={p.player?.position || ""} />
                      <span className="text-[10px] text-surface-500 shrink-0">
                        {p.player?.team}
                      </span>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}
          {/* Claim/unclaim only make sense for your own slot -- shown
              regardless of which team is currently selected for viewing
              (unlike the roster body above), since claiming isn't tied to
              what you're currently looking at. */}
          <div className="px-4 py-2 border-t border-surface-700/50 flex items-center justify-between">
            {myTeamId ? (
              <>
                {!isViewingMyTeam && (
                  <button
                    onClick={() => onSelectTeamId(myTeamId)}
                    className="text-[10px] text-gold-400 hover:text-gold-300 transition-colors"
                  >
                    ← Back to my team
                  </button>
                )}
                <button
                  onClick={onUnclaimTeam}
                  className="text-[10px] text-surface-500 hover:text-red-400 transition-colors ml-auto"
                >
                  Unclaim Team
                </button>
              </>
            ) : (
              <span className="text-[10px] text-surface-600">Claim a team above to start drafting</span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
