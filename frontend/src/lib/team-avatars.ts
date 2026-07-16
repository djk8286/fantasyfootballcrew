export const TEAM_AVATARS = [
  { id: "helmet-red", label: "Red Helmet", bg: "#dc2626", icon: "🏈" },
  { id: "helmet-blue", label: "Blue Helmet", bg: "#2563eb", icon: "🏈" },
  { id: "helmet-green", label: "Green Helmet", bg: "#16a34a", icon: "🏈" },
  { id: "helmet-gold", label: "Gold Helmet", bg: "#ca8a04", icon: "🏈" },
  { id: "helmet-purple", label: "Purple Helmet", bg: "#9333ea", icon: "🏈" },
  { id: "helmet-orange", label: "Orange Helmet", bg: "#ea580c", icon: "🏈" },
  { id: "helmet-teal", label: "Teal Helmet", bg: "#0d9488", icon: "🏈" },
  { id: "helmet-pink", label: "Pink Helmet", bg: "#db2777", icon: "🏈" },
  { id: "helmet-indigo", label: "Indigo Helmet", bg: "#4f46e5", icon: "🏈" },
  { id: "helmet-cyan", label: "Cyan Helmet", bg: "#0891b2", icon: "🏈" },
  { id: "star", label: "Star", bg: "#f59e0b", icon: "⭐" },
  { id: "lightning", label: "Lightning", bg: "#6366f1", icon: "⚡" },
  { id: "flame", label: "Flame", bg: "#ef4444", icon: "🔥" },
  { id: "skull", label: "Skull", bg: "#6b7280", icon: "💀" },
  { id: "crown", label: "Crown", bg: "#fbbf24", icon: "👑" },
  { id: "eagle", label: "Eagle", bg: "#1d4ed8", icon: "🦅" },
  { id: "lion", label: "Lion", bg: "#b45309", icon: "🦁" },
  { id: "wolf", label: "Wolf", bg: "#475569", icon: "🐺" },
  { id: "shark", label: "Shark", bg: "#0f766e", icon: "🦈" },
  { id: "bull", label: "Bull", bg: "#991b1b", icon: "🐂" },
];

export const AVATAR_URL_PREFIX = "ffc-avatar:";

export function getAvatarStyle(avatarUrl: string | null): { bg: string; icon: string } {
  if (!avatarUrl) return { bg: "#374151", icon: "🏈" };
  const avatar = TEAM_AVATARS.find((a) => a.id === avatarUrl.replace(AVATAR_URL_PREFIX, ""));
  return avatar ? { bg: avatar.bg, icon: avatar.icon } : { bg: "#374151", icon: "🏈" };
}
