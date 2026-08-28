"use client";

import Link from "next/link";
import {
  ChevronLeft,
  CheckCircle2,
  Timer,
  Loader2,
  Sparkles,
  List,
  Grid3X3,
  History,
} from "lucide-react";
import TeamCircle from "./DraftTeamCircle";
import { usePickCountdown } from "./PickCountdown";
import { formatPickLabel, picksUntilMyTurn } from "@/lib/draftPickMath";

// Its own leaf component (not just an inline expression using the hook
// directly in DraftHeader's body) so the 500ms tick only re-renders this
// button, not the whole header -- same reasoning as PickCountdown.tsx.
// Needs its own idle fallback (the static configured timerSeconds, shown
// before the first tick / between picks) that PickCountdownText/Badge
// don't provide, so it's colocated here rather than a third exported
// variant there.
function TimerButtonLabel({ startedAt, timerSeconds }: { startedAt: string | null; timerSeconds: number }) {
  const timeLeft = usePickCountdown(startedAt, timerSeconds);
  return <>{timeLeft !== null ? timeLeft : timerSeconds}s</>;
}

interface DraftHeaderProps {
  leagueId: string;
  isCompleted: boolean;
  currentRound: number;
  totalRounds: number;
  totalPicks: number;
  completedPicks: number;
  timerSeconds: number;
  pickStartedAt: string | null;
  showTimerSettings: boolean;
  viewMode: "draft" | "board" | "history";
  actionLoading: string;
  onViewModeChange: (mode: "draft" | "board" | "history") => void;
  onSetTimer: (seconds: number) => void;
  onToggleTimerSettings: () => void;
  onRunMock: () => void;
  // Desktop-only draft train (xl:block below) -- mobile already has its
  // own, in MobileDraftRoom, so these are unused/harmless on small screens.
  teamOrder: string[];
  teams: Record<string, { name: string }>;
  currentTeamId: string | null;
  currentPickGlobalIndex: number;
  numTeams: number;
  myTeamId: string | null;
  // Which team's roster the desktop sidebar (TeamRosters.tsx) currently
  // shows -- tapping a circle here switches it, same interaction/shared
  // state as MobileDraftRoom's own draft-train.
  selectedTeamId: string | null;
  onSelectTeamId: (teamId: string) => void;
}

export default function DraftHeader({
  leagueId,
  isCompleted,
  currentRound,
  totalRounds,
  totalPicks,
  completedPicks,
  timerSeconds,
  pickStartedAt,
  showTimerSettings,
  viewMode,
  actionLoading,
  onViewModeChange,
  onSetTimer,
  onToggleTimerSettings,
  onRunMock,
  teamOrder,
  teams,
  currentTeamId,
  currentPickGlobalIndex,
  numTeams,
  myTeamId,
  selectedTeamId,
  onSelectTeamId,
}: DraftHeaderProps) {
  const uniqueTeams = teamOrder.filter((tid, i, arr) => arr.indexOf(tid) === i);
  const picksAway = !isCompleted ? picksUntilMyTurn(teamOrder, currentPickGlobalIndex, myTeamId) : null;
  const nextPickLabel =
    !isCompleted && myTeamId && picksAway !== null
      ? formatPickLabel(currentPickGlobalIndex + picksAway, numTeams)
      : null;
  return (
    <div className="sticky top-0 z-40 bg-surface-900/95 backdrop-blur-md border-b border-surface-700">
      {/* max-w-7xl (1280px) was fine for every other page, but the draft
          room's desktop layout is two fixed 300px side columns plus a
          stats-dense center player list -- that alone needs ~800px+ of
          breathing room, which 1280px can't give it without squeezing the
          player-name column down toward 0px (verified via CDP -- see the
          commit this landed in). Widened here AND in draft/[id]/page.tsx's
          own containers so the header stays edge-aligned with the body
          below it. */}
      <div className="max-w-425 mx-auto px-4 sm:px-6 lg:px-8 py-2.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3 min-w-0">
            <Link
              href={`/leagues/${leagueId}`}
              className="text-surface-400 hover:text-white transition-colors shrink-0"
            >
              <ChevronLeft className="w-5 h-5" />
            </Link>
            {/* sr-only below sm, not hidden -- MobileDraftRoom is what
                actually renders there, and it has no h1 of its own, so
                hiding this outright left the mobile draft room with no
                page heading at all in the accessibility tree. */}
            <h1 className="text-lg font-bold text-white truncate sr-only sm:not-sr-only sm:block">
              Draft Room
            </h1>
            <span
              className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold shrink-0 ${
                isCompleted
                  ? "bg-green-500/10 text-green-400 border border-green-500/20"
                  : "bg-gold-400/10 text-gold-400 border border-gold-400/20"
              }`}
            >
              {isCompleted ? (
                <>
                  <CheckCircle2 className="w-3 h-3" /> Completed
                </>
              ) : (
                <>
                  <span className="w-1.5 h-1.5 bg-gold-400 rounded-full animate-ping" /> Live
                </>
              )}
            </span>
          </div>
          <div className="flex items-center gap-3 text-sm shrink-0">
            {/* View toggle */}
            <div role="tablist" aria-label="Draft view" className="hidden sm:flex bg-surface-800 rounded-lg p-0.5 border border-surface-700">
              <button
                onClick={() => onViewModeChange("draft")}
                role="tab"
                aria-selected={viewMode === "draft"}
                className={`px-3 py-1.5 rounded text-xs font-semibold transition-all flex items-center gap-1 ${
                  viewMode === "draft"
                    ? "bg-surface-700 text-white"
                    : "text-surface-400 hover:text-white"
                }`}
              >
                <List className="w-3 h-3" /> Draft
              </button>
              <button
                onClick={() => onViewModeChange("board")}
                role="tab"
                aria-selected={viewMode === "board"}
                className={`px-3 py-1.5 rounded text-xs font-semibold transition-all flex items-center gap-1 ${
                  viewMode === "board"
                    ? "bg-surface-700 text-white"
                    : "text-surface-400 hover:text-white"
                }`}
              >
                <Grid3X3 className="w-3 h-3" /> Board
              </button>
              <button
                onClick={() => onViewModeChange("history")}
                role="tab"
                aria-selected={viewMode === "history"}
                className={`px-3 py-1.5 rounded text-xs font-semibold transition-all items-center gap-1 hidden lg:flex ${
                  viewMode === "history"
                    ? "bg-surface-700 text-white"
                    : "text-surface-400 hover:text-white"
                }`}
              >
                <History className="w-3 h-3" /> History
              </button>
            </div>
            <span className="text-surface-400 text-xs hidden sm:inline">
              Rd <span className="text-white font-semibold">{currentRound}</span>
              <span className="text-surface-500">/{totalRounds}</span>
            </span>
            {/* Timer */}
            {!isCompleted && timerSeconds > 0 && (
              <div className="relative">
                <button
                  onClick={onToggleTimerSettings}
                  className="inline-flex items-center gap-1 bg-surface-800 hover:bg-surface-700 border border-surface-700 text-surface-300 hover:text-white px-2 py-1.5 rounded-lg text-xs font-semibold transition-all"
                  title="Timer settings"
                >
                  <Timer className="w-3 h-3" />
                  <TimerButtonLabel startedAt={pickStartedAt} timerSeconds={timerSeconds} />
                </button>
                {showTimerSettings && (
                  <div className="absolute right-0 top-full mt-2 bg-surface-800 border border-surface-700 rounded-xl p-3 shadow-xl z-50 min-w-[180px]">
                    <p className="text-xs text-surface-400 mb-2">Pick Timer</p>
                    <div className="flex flex-wrap gap-1.5">
                      {[0, 15, 30, 60, 120].map((s) => (
                        <button
                          key={s}
                          onClick={() => onSetTimer(s)}
                          aria-pressed={timerSeconds === s}
                          className={`px-2.5 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                            timerSeconds === s
                              ? "bg-gold-400/20 text-gold-400 border border-gold-400/30"
                              : "bg-surface-900 text-surface-400 border border-surface-700 hover:border-surface-500"
                          }`}
                        >
                          {s === 0 ? "Off" : `${s}s`}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
            {!isCompleted && (
              <button
                onClick={onRunMock}
                disabled={actionLoading === "mock"}
                className="inline-flex items-center gap-1.5 bg-surface-800 hover:bg-surface-700 border border-surface-700 text-surface-300 hover:text-white px-3 py-1.5 rounded-lg text-xs font-semibold transition-all disabled:opacity-50"
              >
                {actionLoading === "mock" ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Sparkles className="w-3.5 h-3.5" />
                )}
                Auto-Fill
              </button>
            )}
          </div>
        </div>

        {/* Progress bar */}
        <div
          className="w-full bg-surface-800 rounded-full h-1 mt-2 overflow-hidden"
          role="progressbar"
          aria-valuenow={completedPicks}
          aria-valuemin={0}
          aria-valuemax={totalPicks}
          aria-label="Draft progress"
        >
          <div
            className="h-full rounded-full bg-gradient-to-r from-gold-500 to-gold-300 transition-all duration-500"
            style={{
              width: `${(completedPicks / totalPicks) * 100}%`,
            }}
          />
        </div>

        {/* Desktop draft train -- xl:block only. Mobile has its own,
            purpose-built version in MobileDraftRoom; showing both would be
            redundant on a screen where they'd both fit. */}
        {uniqueTeams.length > 0 && (
          <div className="hidden xl:flex items-center gap-4 mt-3 pt-3 border-t border-surface-800">
            <div className="flex-1 flex gap-3 overflow-x-auto no-scrollbar">
              {uniqueTeams.map((tid) => (
                <TeamCircle
                  key={tid}
                  teamId={tid}
                  name={teams[tid]?.name || "Team"}
                  isCurrent={tid === currentTeamId && !isCompleted}
                  isMine={tid === myTeamId}
                  isSelected={tid === selectedTeamId}
                  onClick={() => onSelectTeamId(tid)}
                  size="sm"
                />
              ))}
            </div>
            <div className="text-right shrink-0 pl-4 border-l border-surface-800">
              {isCompleted ? (
                <span className="text-xs text-green-400 font-semibold">Draft complete</span>
              ) : nextPickLabel ? (
                <span className="text-xs text-surface-300 whitespace-nowrap">
                  Your next pick: <span className="font-bold text-white">{nextPickLabel}</span>
                  {picksAway ? <span className="text-surface-500"> ({picksAway} away)</span> : <span className="text-gold-400 font-semibold"> — now</span>}
                </span>
              ) : (
                <span className="text-xs text-surface-500 whitespace-nowrap">Claim a team to track your picks</span>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
