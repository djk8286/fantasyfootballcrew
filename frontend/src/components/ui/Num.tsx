import type { ReactNode } from "react";
import { formatPoints } from "./tokens";

type NumSize = "sm" | "row" | "lg" | "score";

const SIZES: Record<NumSize, string> = {
  sm: "text-xs",
  row: "text-row",
  lg: "text-xl",
  score: "text-score font-semibold",
};

interface NumProps {
  value: number | null | undefined;
  digits?: number;
  signed?: boolean;
  size?: NumSize;
  className?: string;
}

/** A score or stat in tabular mono, so columns line up. Null renders "—". */
export function Num({ value, digits = 1, signed = false, size = "row", className = "" }: NumProps) {
  return <span className={`num ${SIZES[size]} ${className}`}>{formatPoints(value, digits, signed)}</span>;
}

/** Label over a value, for header stat rows (record, rank, PF, PA). */
export function StatBlock({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-label font-semibold uppercase text-ink-400">{label}</span>
      <span className="num text-xl text-ink-100">{children}</span>
    </div>
  );
}
