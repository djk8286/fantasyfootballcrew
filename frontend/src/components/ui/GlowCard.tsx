import type { ReactNode } from "react";

interface GlowCardProps {
  children: ReactNode;
  active?: boolean;
  className?: string;
}

/**
 * Card wrapper with the same "live" glow treatment used for the draft room's
 * on-the-clock banner — a pulsing gold ring + soft shadow when `active`.
 */
export default function GlowCard({ children, active = false, className = "" }: GlowCardProps) {
  return (
    <div
      className={`rounded-2xl border transition-all duration-300 ${
        active
          ? "bg-gold-400/10 border-gold-400/40 ring-2 ring-gold-400/20 shadow-[0_0_30px_rgba(255,215,0,0.12)]"
          : "bg-surface-800/50 border-surface-700"
      } ${className}`}
    >
      {children}
    </div>
  );
}
