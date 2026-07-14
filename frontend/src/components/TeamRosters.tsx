"use client";

import { Star } from "lucide-react";
import PositionBadge, { POSITION_ORDER } from "./PositionBadge";

interface TeamRosterPick {
  id: string;
  pick_number: number;
  player?: {
    id: string;
    full_name: string;
    position: string;
    team: string;
  } | null;
  team: { id: string; name: string };
}

interface TeamRostersProps {
  myTeamId: string | null;
  myPicks: TeamRosterPick[];
  myRosterByPos: Record<string, TeamRosterPick[]>;
  team_order: string[];
  teams: Record<string, { name: string }>;
  teamRosters: Record<string, TeamRosterPick[]>;
  isCompleted: boolean;
  currentTeamId: string | null;
  expandedTeams: Record<string, boolean>;
  onToggleExpand: (teamId: string) => void;
  onClaimTeam: (teamId: string) => void;
  onUnclaimTeam: () => void;
}

export default function TeamRosters({
  myTeamId,
  myPicks,
  myRosterByPos,
  team_order,
  teams,
  teamRosters,
  isCompleted,
  currentTeamId,
  expandedTeams,
  onToggleExpand,
  onClaimTeam,
  onUnclaimTeam,
}: TeamRostersProps) {
  return (
    <div className="w-full xl:w-[380px] shrink-0">
      <div className="xl:sticky xl:top-20 space-y-4">
        {/* My Team */}
        <div className="bg-surface-800/50 border border-surface-700 rounded-2xl overflow-hidden">
          <div className="px-4 py-3 border-b border-surface-700 flex items-center justify-between">
            <h3 className="text-xs font-semibold text-surface-400 uppercase tracking-wider flex items-center gap-2">
              <Star className="w-3.5 h-3.5 text-gold-400" />
              {myTeamId
                ? teams[myTeamId]?.name || "My Team"
                : "Your Team"}
            </h3>
            <span className="text-surface-500 text-xs">
              {myPicks.length} players
            </span>
          </div>
          {myTeamId ? (
            myPicks.length === 0 ? (
              <div className="p-6 text-center text-surface-500 text-sm">
                No picks yet. Your team will appear here as you draft.
              </div>
            ) : (
              <div className="divide-y divide-surface-800">
                {POSITION_ORDER.filter((pos) => myRosterByPos[pos]).map((pos) => (
                  <div key={pos}>
                    <div className="px-4 py-1.5 bg-surface-900/30 text-[10px] font-semibold text-surface-500 uppercase tracking-wider">
                      {pos} ({myRosterByPos[pos].length})
                    </div>
                    {myRosterByPos[pos].map((p) => (
                      <div key={p.id} className="flex items-center gap-2 px-4 py-1.5">
                        <span className="text-surface-500 text-[10px] font-mono w-4 shrink-0">
                          {p.pick_number}
                        </span>
                        <span className="text-sm text-white truncate flex-1">
                          {p.player?.full_name}
                        </span>
                        <span className="text-[10px] text-surface-500 shrink-0">
                          {p.player?.team}
                        </span>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            )
          ) : (
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
          )}
          {myTeamId && (
            <div className="px-4 py-2 border-t border-surface-700/50 flex justify-end">
              <button
                onClick={onUnclaimTeam}
                className="text-[10px] text-surface-500 hover:text-red-400 transition-colors"
              >
                Unclaim Team
              </button>
            </div>
          )}
        </div>

        {/* Team Rosters */}
        <div className="bg-surface-800/50 border border-surface-700 rounded-2xl overflow-hidden">
          <div className="px-4 py-3 border-b border-surface-700">
            <h3 className="text-xs font-semibold text-surface-400 uppercase tracking-wider">
              League · {Object.keys(teamRosters).length || "?"} Teams
            </h3>
          </div>
          <div className="divide-y divide-surface-800 max-h-[400px] overflow-y-auto">
            {Object.entries(teamRosters).map(([teamId, picks]) => {
              const isCurrent = !isCompleted && currentTeamId === teamId;
              const isMine = myTeamId === teamId;
              const expanded = expandedTeams[teamId] || false;
              return (
                <div
                  key={teamId}
                  className={`${
                    isCurrent
                      ? "bg-gold-400/5"
                      : isMine
                        ? "bg-surface-800/30"
                        : ""
                  }`}
                >
                  {/* Header */}
                  <div
                    className="flex items-center justify-between px-4 py-2 cursor-pointer hover:bg-surface-800/30 transition-colors"
                    onClick={() => onToggleExpand(teamId)}
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      {isMine && (
                        <Star className="w-3 h-3 text-gold-400 shrink-0" />
                      )}
                      <span
                        className={`text-sm font-medium truncate ${
                          isMine || isCurrent ? "text-gold-400" : "text-surface-300"
                        }`}
                      >
                        {picks[0]?.team.name || "Unknown"}
                      </span>
                      {isCurrent && !isCompleted && (
                        <span className="w-1.5 h-1.5 bg-gold-400 rounded-full animate-pulse shrink-0" />
                      )}
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="text-surface-500 text-xs font-mono">
                        {picks.length}
                      </span>
                      <span
                        className="text-surface-600 text-[9px] transition-transform"
                        style={{
                          transform: expanded
                            ? "rotate(180deg)"
                            : "rotate(0deg)",
                        }}
                      >
                        ▼
                      </span>
                    </div>
                  </div>
                  {/* Expanded roster */}
                  {expanded && (
                    <div className="border-t border-surface-800/50">
                      {picks
                        .sort((a, b) => a.pick_number - b.pick_number)
                        .map((p) => (
                          <div
                            key={p.id}
                            className="flex items-center gap-2 px-4 py-1.5 text-xs hover:bg-surface-800/20"
                          >
                            <span className="text-surface-500 text-[10px] font-mono w-5 shrink-0">
                              {p.pick_number}
                            </span>
                            <span className="text-white truncate flex-1">
                              {p.player?.full_name || "—"}
                            </span>
                            <PositionBadge pos={p.player?.position || ""} />
                            <span className="text-[9px] text-surface-500 shrink-0">
                              {p.player?.team || ""}
                            </span>
                          </div>
                        ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
