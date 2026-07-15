"use client";

import PositionBadge from "./PositionBadge";

// Local type that matches the shape used in the draft page
interface HoverPlayer {
  id: string;
  full_name: string;
  first_name: string;
  last_name: string;
  position: string;
  team: string;
  age: number | null;
  number: number | null;
  bye_week: number | null;
  injury_status: string | null;
  fantasy_positions: string[] | null;
  avatar_url: string | null;
  sleeper_id: string | null;
  rank_score: number;
  pos_rank: number;
}

function PlayerAvatar({
  player,
  size = "md",
  onHover,
}: {
  player: HoverPlayer;
  size?: "sm" | "md" | "lg";
  onHover?: (player: HoverPlayer | null, el: HTMLElement | null) => void;
}) {
  const dims = { sm: "w-7 h-7", md: "w-9 h-9", lg: "w-12 h-12" };
  const fontSizes = { sm: "text-[9px]", md: "text-xs", lg: "text-sm" };
  return (
    <div
      className="relative"
      onMouseEnter={(e) => onHover?.(player, e.currentTarget)}
      onMouseLeave={() => onHover?.(null, null)}
    >
      <div
        className={`${dims[size]} rounded-full bg-surface-700 flex-shrink-0 overflow-hidden border border-surface-600 cursor-pointer`}
      >
        {"avatar_url" in player && player.avatar_url ? (
          <img
            src={player.avatar_url}
            alt={player.full_name}
            className="w-full h-full object-cover"
            onError={(e) => {
              (e.target as HTMLImageElement).style.display = "none";
              const parent = (e.target as HTMLImageElement).parentElement!;
              parent.classList.add("flex", "items-center", "justify-center");
              parent.innerHTML = `<span class="${fontSizes[size]} text-surface-500 font-bold">${player.full_name.charAt(0)}</span>`;
            }}
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center">
            <span className={`${fontSizes[size]} text-surface-500 font-bold`}>
              {player.full_name.charAt(0)}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

// Shared hover card — rendered as fixed overlay at page root so it escapes all containers
function PlayerCardOverlay({
  player,
  position,
}: {
  player: any;
  position: { x: number; y: number } | null;
}) {
  if (!player || !position) return null;

  // Flip below if too close to top
  const above = position.y > 300;

  return (
    <div
      className="fixed z-[9999] pointer-events-none"
      style={{
        left: Math.min(position.x, window.innerWidth - 240),
        top: above ? position.y - 10 : position.y + 10,
        transform: above ? "translateY(-100%)" : "translateY(0)",
      }}
    >
      <div className="w-56 bg-surface-850 border border-surface-600 rounded-xl shadow-2xl shadow-black/60 animate-in fade-in slide-in-from-top-2 duration-200">
        <div className="p-3">
          {/* Header: team badge + jersey number */}
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[10px] font-bold uppercase tracking-wider text-surface-500 bg-surface-900 px-2 py-0.5 rounded">
              {player.team || "FA"}
            </span>
            {player.number && (
              <span className="text-[10px] text-surface-600 font-mono">
                #{player.number}
              </span>
            )}
          </div>
          {/* Player name */}
          <p className="text-base font-bold text-white leading-tight mb-2">
            {player.full_name}
          </p>
          {/* Divider */}
          <div className="h-px bg-surface-700/60 mb-2" />
          {/* Position + Ranks row */}
          <div className="flex items-center gap-2 flex-wrap mb-2">
            <PositionBadge pos={player.position} size="md" />
            {player.pos_rank && player.pos_rank > 0 && (
              <span className="text-[10px] text-surface-400 font-semibold">
                {player.position}
                {player.pos_rank}
              </span>
            )}
            {"rank_score" in player && player.rank_score && player.rank_score < 500 && (
              <span className="text-[10px] text-gold-400/80 font-semibold ml-auto">
                #{player.rank_score}
              </span>
            )}
          </div>
          {/* Detail grid: 2-col */}
          <div className="grid grid-cols-2 gap-x-3 gap-y-1.5">
            {"age" in player && player.age && (
              <div className="flex items-center gap-1">
                <span className="text-[9px] text-surface-600 uppercase">Age</span>
                <span className="text-[10px] text-surface-300 font-medium">
                  {player.age}
                </span>
              </div>
            )}
            {"bye_week" in player && player.bye_week && (
              <div className="flex items-center gap-1">
                <span className="text-[9px] text-surface-600 uppercase">Bye</span>
                <span className="text-[10px] text-surface-300 font-medium">
                  WK {player.bye_week}
                </span>
              </div>
            )}
            {"injury_status" in player &&
              player.injury_status &&
              player.injury_status !== "None" &&
              player.injury_status !== null && (
                <div className="flex items-center gap-1">
                  <span className="text-[9px] text-surface-600 uppercase">Status</span>
                  <span
                    className={`text-[10px] font-semibold ${
                      player.injury_status === "Out" || player.injury_status === "IR"
                        ? "text-red-400"
                        : player.injury_status === "Questionable" ||
                            player.injury_status === "Doubtful"
                          ? "text-yellow-400"
                          : "text-green-400"
                    }`}
                  >
                    {player.injury_status}
                  </span>
                </div>
              )}
            {"fantasy_positions" in player &&
              player.fantasy_positions &&
              player.fantasy_positions.length > 1 && (
                <div className="flex items-center gap-1 col-span-2">
                  <span className="text-[9px] text-surface-600 uppercase">Eligible</span>
                  <div className="flex gap-1">
                    {player.fantasy_positions.map((pos: string) => (
                      <PositionBadge key={pos} pos={pos} />
                    ))}
                  </div>
                </div>
              )}
          </div>
        </div>
      </div>
    </div>
  );
}

export { PlayerAvatar, PlayerCardOverlay };
export type { HoverPlayer };
export default PlayerAvatar;
