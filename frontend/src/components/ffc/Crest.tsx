import Avatar from "@/components/Avatar";

const PALETTE = ["#4F8CFF", "#34D399", "#F59E0B", "#A78BFA", "#F472B6", "#22D3EE", "#FB7185", "#84CC16", "#E879F9", "#60A5FA", "#FBBF24", "#2DD4BF"];

function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return h;
}

export function initials(name: string): string {
  const words = name.replace(/[^A-Za-z0-9 ]/g, " ").split(/\s+/).filter(Boolean);
  const pick = words.filter((w) => w.length > 2 || /\d/.test(w));
  const use = pick.length >= 2 ? pick : words;
  return ((use[0]?.[0] ?? "?") + (use[1]?.[0] ?? use[0]?.[1] ?? "")).toUpperCase();
}

/** Shield with initials, tinted by a color hashed from the team id. A team avatar wins when set. */
export function Crest({ id, name, avatarUrl, size, faded = false }: { id: string; name: string; avatarUrl?: string | null; size: number; faded?: boolean }) {
  if (avatarUrl) {
    return (
      <span className={faded ? "grayscale opacity-45" : ""} style={{ display: "inline-flex" }}>
        <Avatar url={avatarUrl} size={size} rounded="rounded-lg" />
      </span>
    );
  }
  const color = faded ? "#7A859C" : PALETTE[hash(id) % PALETTE.length];
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" className="shrink-0" style={faded ? { opacity: 0.45 } : undefined}>
      <path d="M16 2 28 6v9c0 7.5-5.2 12.6-12 15-6.8-2.4-12-7.5-12-15V6z" fill={color} fillOpacity={0.18} stroke={color} strokeWidth={1.6} strokeLinejoin="round" />
      <text x="16" y="19.5" textAnchor="middle" fontSize="10" fontWeight="700" fill={faded ? color : "#E8EEF8"} fontFamily="var(--ffc-font-ui)">
        {initials(name)}
      </text>
    </svg>
  );
}
