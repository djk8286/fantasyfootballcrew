import type { ReactNode } from "react";

interface CardProps {
  children: ReactNode;
  you?: boolean;
  className?: string;
}

/** Flat panel on the page background. Don't nest cards; use rows or dividers inside. */
export function Card({ children, you = false, className = "" }: CardProps) {
  return (
    <section
      className={`rounded-card border p-4 lg:p-5 ${
        you ? "border-gold/40 bg-gold/[0.07]" : "border-ink-700 bg-ink-900"
      } ${className}`}
    >
      {children}
    </section>
  );
}

export function CardHeader({ title, action }: { title: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between gap-3">
      <h2 className="text-label font-semibold uppercase text-ink-400">{title}</h2>
      {action}
    </div>
  );
}
