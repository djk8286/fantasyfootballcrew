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
} from "lucide-react";

interface DraftHeaderProps {
  leagueId: string;
  isCompleted: boolean;
  currentRound: number;
  totalRounds: number;
  totalPicks: number;
  completedPicks: number;
  timerSeconds: number;
  timeLeft: number | null;
  showTimerSettings: boolean;
  viewMode: "draft" | "board";
  actionLoading: string;
  onViewModeChange: (mode: "draft" | "board") => void;
  onSetTimer: (seconds: number) => void;
  onToggleTimerSettings: () => void;
  onRunMock: () => void;
}

export default function DraftHeader({
  leagueId,
  isCompleted,
  currentRound,
  totalRounds,
  totalPicks,
  completedPicks,
  timerSeconds,
  timeLeft,
  showTimerSettings,
  viewMode,
  actionLoading,
  onViewModeChange,
  onSetTimer,
  onToggleTimerSettings,
  onRunMock,
}: DraftHeaderProps) {
  return (
    <div className="sticky top-0 z-40 bg-surface-900/95 backdrop-blur-md border-b border-surface-700">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-2.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3 min-w-0">
            <Link
              href={`/leagues/${leagueId}`}
              className="text-surface-400 hover:text-white transition-colors shrink-0"
            >
              <ChevronLeft className="w-5 h-5" />
            </Link>
            <h1 className="text-lg font-bold text-white truncate hidden sm:block">
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
            <div className="hidden sm:flex bg-surface-800 rounded-lg p-0.5 border border-surface-700">
              <button
                onClick={() => onViewModeChange("draft")}
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
                className={`px-3 py-1.5 rounded text-xs font-semibold transition-all flex items-center gap-1 ${
                  viewMode === "board"
                    ? "bg-surface-700 text-white"
                    : "text-surface-400 hover:text-white"
                }`}
              >
                <Grid3X3 className="w-3 h-3" /> Board
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
                  {timeLeft !== null ? timeLeft : timerSeconds}s
                </button>
                {showTimerSettings && (
                  <div className="absolute right-0 top-full mt-2 bg-surface-800 border border-surface-700 rounded-xl p-3 shadow-xl z-50 min-w-[180px]">
                    <p className="text-xs text-surface-400 mb-2">Pick Timer</p>
                    <div className="flex flex-wrap gap-1.5">
                      {[0, 15, 30, 60, 120].map((s) => (
                        <button
                          key={s}
                          onClick={() => onSetTimer(s)}
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
        <div className="w-full bg-surface-800 rounded-full h-1 mt-2 overflow-hidden">
          <div
            className="h-full rounded-full bg-gradient-to-r from-gold-500 to-gold-300 transition-all duration-500"
            style={{
              width: `${(completedPicks / totalPicks) * 100}%`,
            }}
          />
        </div>
      </div>
    </div>
  );
}
