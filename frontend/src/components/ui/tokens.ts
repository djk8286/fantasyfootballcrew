export type Position = "QB" | "RB" | "WR" | "TE" | "FLEX" | "SUPERFLEX" | "K" | "DEF" | "DL" | "LB" | "DB" | "IDP_FLEX";

export type Tone = "neutral" | "you" | "win" | "loss" | "warn" | "live";

export const TONE_CLASSES: Record<Tone, string> = {
  neutral: "bg-ink-800 text-ink-300",
  you: "bg-gold/15 text-gold",
  win: "bg-win/15 text-win",
  loss: "bg-loss/15 text-loss",
  warn: "bg-warn/15 text-warn",
  live: "bg-live/15 text-live",
};

const POSITION_CLASSES: Record<Position, string> = {
  QB: "bg-pos-qb/15 text-pos-qb",
  RB: "bg-pos-rb/15 text-pos-rb",
  WR: "bg-pos-wr/15 text-pos-wr",
  TE: "bg-pos-te/15 text-pos-te",
  FLEX: "bg-pos-flex/15 text-pos-flex",
  SUPERFLEX: "bg-pos-flex/15 text-pos-flex",
  K: "bg-pos-k/15 text-pos-k",
  DEF: "bg-pos-def/15 text-pos-def",
  DL: "bg-pos-idp/15 text-pos-idp",
  LB: "bg-pos-idp/15 text-pos-idp",
  DB: "bg-pos-idp/15 text-pos-idp",
  IDP_FLEX: "bg-pos-idp/15 text-pos-idp",
};

const POSITION_LABELS: Partial<Record<Position, string>> = {
  SUPERFLEX: "SFLX",
  IDP_FLEX: "IDP",
};

const POSITION_ALIASES: Record<string, Position> = {
  DST: "DEF",
  "D/ST": "DEF",
  SFLEX: "SUPERFLEX",
  SF: "SUPERFLEX",
  OP: "SUPERFLEX",
  IDP: "IDP_FLEX",
};

export function toPosition(raw: string | null | undefined): Position | null {
  if (!raw) return null;
  const key = raw.trim().toUpperCase();
  if (key in POSITION_CLASSES) return key as Position;
  return POSITION_ALIASES[key] ?? null;
}

export function positionStyle(pos: Position): { label: string; className: string } {
  return { label: POSITION_LABELS[pos] ?? pos, className: POSITION_CLASSES[pos] };
}

export type InjuryCode = "Q" | "D" | "O" | "IR" | "PUP" | "SUS" | "BYE";

const INJURY_CODES: Record<string, InjuryCode> = {
  questionable: "Q",
  doubtful: "D",
  out: "O",
  ir: "IR",
  "injured reserve": "IR",
  pup: "PUP",
  sus: "SUS",
  suspended: "SUS",
  na: "O",
};

export const INJURY_TONE: Record<InjuryCode, string> = {
  Q: "bg-warn/15 text-warn",
  D: "bg-pos-te/15 text-pos-te",
  O: "bg-loss/15 text-loss",
  IR: "bg-loss/15 text-loss",
  PUP: "bg-loss/15 text-loss",
  SUS: "bg-loss/15 text-loss",
  BYE: "bg-ink-800 text-ink-400",
};

/** Sleeper's injury designation as a short tag, or null for healthy / unknown. */
export function injuryCode(status: string | null | undefined): InjuryCode | null {
  if (!status) return null;
  return INJURY_CODES[status.trim().toLowerCase()] ?? null;
}

/** Fixed-decimal points, "—" when there is no number yet. */
export function formatPoints(value: number | null | undefined, digits = 1, signed = false): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const text = value.toFixed(digits);
  return signed && value > 0 ? `+${text}` : text;
}

/** Player positions in roster order, for filters and grouped lists. */
export const POSITION_ORDER = ["QB", "RB", "WR", "TE", "K", "DEF", "DB", "DL", "LB"];
