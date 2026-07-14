"use client";

import Link from "next/link";
import { CheckCircle2 } from "lucide-react";
import TeamBadge from "./TeamBadge";
import PositionBadge from "./PositionBadge";

interface BoardViewTeam {
  id: string;
  name: string;
}

interface BoardViewPick {
  id: string;
  round: number;
  pick_number: number;
  player?: {
    id: string;
    full_name: string;
    position: string;
    team: string;
  } | null;
  team: { id: string; name: string };
}

interface BoardViewProps {
  isCompleted: boolean;
  draftInfo: {
    total_picks: number;
    num_teams: number;
    total_rounds: number;
    league_id: string;
  };
  team_order: string[];
  teams: Record<string, { name: string }>;
  allPicks: BoardViewPick[];
  currentPick: BoardViewPick | null;
  myTeamId: string | null;
  firstRoundTeams: BoardViewTeam[];
  onPlayerHover: (player: any, el: HTMLElement | null) => void;
}

export default function BoardView({
  isCompleted,
  draftInfo,
  team_order,
  teams,
  allPicks,
  currentPick,
  myTeamId,
  firstRoundTeams,
  onPlayerHover,
}: BoardViewProps) {
  return (
    <div>
      {/* Completed message */}
      {isCompleted && (
        <div className="mb-6 bg-surface-800 border border-surface-700 rounded-2xl p-6 text-center">
          <CheckCircle2 className="w-10 h-10 text-green-400 mx-auto mb-2" />
          <h2 className="text-xl font-bold text-white mb-1">Draft Complete!</h2>
          <p className="text-surface-400 text-sm">
            {draftInfo.total_picks} picks across {draftInfo.num_teams} teams
          </p>
          <Link
            href={`/leagues/${draftInfo.league_id}`}
            className="inline-flex items-center gap-2 bg-gold-400 hover:bg-gold-300 text-surface-900 px-6 py-2.5 rounded-xl font-bold text-sm mt-4 transition-all"
          >
            Back to League
          </Link>
        </div>
      )}
      {/* Board */}
      <div className="overflow-x-auto">
        <table className="w-full table-fixed border-collapse">
          <thead>
            <tr>
              <th className="text-[10px] text-surface-500 font-semibold uppercase tracking-wider px-1 py-1 text-left w-8 sticky left-0 bg-surface-900 z-10">
                Rd
              </th>
              {Array.from({ length: draftInfo.num_teams }, (_, pickPos) => {
                const team = firstRoundTeams[pickPos];
                const isMine = team && myTeamId === team.id;
                return (
                  <th
                    key={pickPos}
                    className={`px-0.5 py-1 text-[9px] font-bold uppercase tracking-wide w-[calc((100%-2rem)/${draftInfo.num_teams})] ${
                      isMine ? "text-gold-400" : "text-surface-400"
                    }`}
                  >
                    <div
                      className="flex flex-col items-center gap-0.5"
                      title={team?.name}
                    >
                      <div className="flex items-center gap-1">
                        <TeamBadge team={team?.name || ""} isMine={isMine} />
                        <span className="truncate max-w-[50px]">
                          {team?.name || `Pick ${pickPos + 1}`}
                        </span>
                      </div>
                    </div>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: draftInfo.total_rounds }, (_, i) => i + 1).map(
              (round) => {
                const roundStart = (round - 1) * draftInfo.num_teams;
                const roundTeamOrder = team_order.slice(
                  roundStart,
                  roundStart + draftInfo.num_teams
                );
                const roundPicks = allPicks.filter((p) => p.round === round);
                const roundComplete =
                  roundPicks.length > 0 &&
                  roundPicks.every((p) => p.player);
                return (
                  <tr
                    key={round}
                    className={`${round % 2 === 0 ? "bg-surface-850/30" : ""}`}
                  >
                    <td
                      className={`sticky left-0 bg-surface-900 z-10 px-1 py-0.5 text-[10px] font-semibold ${
                        roundComplete ? "text-surface-500" : "text-gold-400"
                      }`}
                    >
                      <div className="flex items-center gap-1">
                        {round}
                        {roundComplete && (
                          <CheckCircle2 className="w-2.5 h-2.5 text-green-400" />
                        )}
                      </div>
                    </td>
                    {roundTeamOrder.map((teamId, colIdx) => {
                      const pick = roundPicks.find(
                        (p) => p.team.id === teamId
                      );
                      const isDrafted = pick && pick.player;
                      const isCurrentPick =
                        currentPick &&
                        pick &&
                        pick.pick_number === currentPick.pick_number;
                      const isMine = myTeamId === teamId;
                      const team = teams[teamId];
                      const globalPickNum = roundStart + colIdx + 1;
                      return (
                        <td
                          key={colIdx}
                          className={`px-0.5 py-0.5 border-b border-surface-800 group ${
                            isCurrentPick && !isCompleted
                              ? "bg-gold-400/10"
                              : ""
                          }`}
                        >
                          <div
                            className={`rounded border p-1.5 min-h-[42px] transition-all text-xs leading-snug relative group cursor-default ${
                              isCurrentPick && !isCompleted
                                ? "border-gold-400/50 bg-gold-400/5 ring-1 ring-gold-400/20"
                                : isDrafted
                                  ? "border-surface-700 bg-surface-800/60"
                                  : roundComplete
                                    ? "border-surface-700/20 bg-surface-800/10 opacity-40"
                                    : "border-surface-700/30 bg-surface-800/20"
                            }`}
                          >
                            {/* Team badge + name */}
                            <div className="flex items-center gap-1 mb-0.5">
                              <TeamBadge
                                team={team?.name || ""}
                                isMine={isMine}
                              />
                              <span
                                className="text-[7px] uppercase tracking-wider font-semibold truncate"
                                style={{
                                  color: isMine ? "#fbbf24" : "#6b7280",
                                }}
                              >
                                {team?.name || "—"}
                              </span>
                            </div>
                            {isDrafted && pick?.player ? (
                              <div
                                onMouseEnter={(e) =>
                                  onPlayerHover(
                                    pick!.player,
                                    e.currentTarget
                                  )
                                }
                                onMouseLeave={() => onPlayerHover(null, null)}
                              >
                                <div className="flex items-center gap-1">
                                  <span
                                    className="text-[10px] font-semibold text-white truncate leading-tight max-w-[65px]"
                                    title={pick.player.full_name}
                                  >
                                    {pick.player.full_name}
                                  </span>
                                  <PositionBadge
                                    pos={pick.player.position}
                                  />
                                </div>
                              </div>
                            ) : isCurrentPick && !isCompleted ? (
                              <div className="flex items-center justify-center h-[24px]">
                                <span className="w-1.5 h-1.5 bg-gold-400 rounded-full animate-pulse" />
                              </div>
                            ) : (
                              <div className="flex items-center justify-center h-[24px]">
                                <span className="text-[9px] text-surface-600">
                                  —
                                </span>
                              </div>
                            )}
                            {/* Pick number */}
                            <div className="text-[6px] text-surface-600 absolute top-0.5 right-1">
                              #{globalPickNum}
                            </div>
                          </div>
                        </td>
                      );
                    })}
                  </tr>
                );
              }
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
