"use client";

const POSITION_COLORS: Record<string, string> = {
  QB: "bg-blue-700/40 text-blue-300 border-blue-500/40",
  RB: "bg-emerald-700/50 text-emerald-300 border-emerald-500/40",
  WR: "bg-purple-700/40 text-purple-300 border-purple-500/40",
  TE: "bg-orange-700/40 text-orange-300 border-orange-500/40",
  K: "bg-red-700/40 text-red-300 border-red-500/40",
  DEF: "bg-yellow-700/40 text-yellow-300 border-yellow-500/40",
  DB: "bg-cyan-700/40 text-cyan-300 border-cyan-500/40",
  DL: "bg-pink-700/40 text-pink-300 border-pink-500/40",
  LB: "bg-indigo-700/40 text-indigo-300 border-indigo-500/40",
};

const POSITION_ORDER = ["QB", "RB", "WR", "TE", "K", "DEF", "DB", "DL", "LB"];
const POSITION_SORT: Record<string, number> = {
  QB: 0, RB: 1, WR: 2, TE: 3, K: 4, DEF: 5, DB: 6, DL: 7, LB: 8,
};

function PositionBadge({ pos, size = "sm" }: { pos: string; size?: "sm" | "md" }) {
  const colors = POSITION_COLORS[pos] || "bg-surface-600 text-surface-300 border-surface-600";
  const s = size === "md" ? "px-2.5 py-0.5 text-xs" : "px-2 py-0.5 text-[10px]";
  return (
    <span className={`inline-flex items-center ${s} rounded font-bold border ${colors}`}>
      {pos}
    </span>
  );
}

export { PositionBadge, POSITION_COLORS, POSITION_ORDER, POSITION_SORT };
export default PositionBadge;
