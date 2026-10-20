import type { ReactNode } from "react";
import { TONE_CLASSES, INJURY_TONE, injuryCode, positionStyle, toPosition, type Tone } from "./tokens";

const CHIP = "inline-flex h-5 items-center rounded-chip px-1.5 text-label font-bold uppercase";

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`${CHIP} ${TONE_CLASSES[tone]}`}>{children}</span>;
}

/** Position or roster-slot chip. Unknown positions render as a neutral chip with the raw text. */
export function PositionChip({ pos, className = "" }: { pos: string; className?: string }) {
  const known = toPosition(pos);
  if (!known) return <span className={`${CHIP} ${TONE_CLASSES.neutral} ${className}`}>{pos}</span>;
  const { label, className: color } = positionStyle(known);
  return <span className={`${CHIP} min-w-9 justify-center ${color} ${className}`}>{label}</span>;
}

/** Short injury or bye tag. Renders nothing for a healthy player. */
export function InjuryTag({ status, onBye = false }: { status?: string | null; onBye?: boolean }) {
  const code = onBye ? "BYE" : injuryCode(status);
  if (!code) return null;
  return (
    <span className={`${CHIP} ${INJURY_TONE[code]}`} title={onBye ? "On bye" : (status ?? undefined)}>
      {code}
    </span>
  );
}
