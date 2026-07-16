const MEDAL_GRADIENTS: Record<number, string> = {
  1: "from-gold-300 to-gold-600",
  2: "from-surface-200 to-surface-400",
  3: "from-orange-300 to-orange-600",
};

interface RankBadgeProps {
  rank: number;
  size?: "sm" | "md";
}

export default function RankBadge({ rank, size = "md" }: RankBadgeProps) {
  const dims = size === "sm" ? "w-7 h-7 text-xs" : "w-9 h-9 text-sm";
  const medal = MEDAL_GRADIENTS[rank];

  if (medal) {
    return (
      <div
        className={`${dims} rounded-full bg-gradient-to-br ${medal} flex items-center justify-center font-bold text-surface-900 shrink-0 shadow-lg`}
      >
        {rank}
      </div>
    );
  }

  return (
    <div
      className={`${dims} rounded-full bg-surface-800 border border-surface-700 flex items-center justify-center font-bold text-surface-400 shrink-0`}
    >
      {rank}
    </div>
  );
}
