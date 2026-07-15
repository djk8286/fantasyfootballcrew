"use client";

// Team badge — colored avatar with initials cycling through a palette
const TEAM_COLORS = [
  { bg: "bg-blue-500/20", border: "border-blue-500/40", text: "text-blue-400" },
  { bg: "bg-red-500/20", border: "border-red-500/40", text: "text-red-400" },
  { bg: "bg-emerald-500/20", border: "border-emerald-500/40", text: "text-emerald-400" },
  { bg: "bg-purple-500/20", border: "border-purple-500/40", text: "text-purple-400" },
  { bg: "bg-orange-500/20", border: "border-orange-500/40", text: "text-orange-400" },
  { bg: "bg-cyan-500/20", border: "border-cyan-500/40", text: "text-cyan-400" },
  { bg: "bg-pink-500/20", border: "border-pink-500/40", text: "text-pink-400" },
  { bg: "bg-yellow-500/20", border: "border-yellow-500/40", text: "text-yellow-400" },
  { bg: "bg-teal-500/20", border: "border-teal-500/40", text: "text-teal-400" },
  { bg: "bg-indigo-500/20", border: "border-indigo-500/40", text: "text-indigo-400" },
  { bg: "bg-rose-500/20", border: "border-rose-500/40", text: "text-rose-400" },
  { bg: "bg-lime-500/20", border: "border-lime-500/40", text: "text-lime-400" },
];

function hashTeam(team: string): number {
  let hash = 0;
  for (let i = 0; i < team.length; i++) hash = (hash * 31 + team.charCodeAt(i)) | 0;
  return Math.abs(hash);
}

function TeamBadge({ team, isMine = false }: { team: string; isMine?: boolean }) {
  const colors = TEAM_COLORS[hashTeam(team) % TEAM_COLORS.length];
  const initials = team.replace("Team ", "T").slice(0, 2).toUpperCase();
  return (
    <div
      className={`w-5 h-5 rounded-full flex items-center justify-center text-[7px] font-bold shrink-0 border ${
        isMine
          ? "bg-gold-400/30 border-gold-400/50 text-gold-400 shadow-sm shadow-gold-400/20"
          : `${colors.bg} ${colors.border} ${colors.text}`
      }`}
      title={team}
    >
      {initials}
    </div>
  );
}

export { TeamBadge, TEAM_COLORS, hashTeam };
export default TeamBadge;
