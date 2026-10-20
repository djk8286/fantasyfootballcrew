import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  body?: string;
  /** Required: an empty state always offers the next step. */
  action: ReactNode;
}

export function EmptyState({ icon: Icon, title, body, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center gap-2 px-4 py-10 text-center">
      {Icon && <Icon className="mb-1 h-6 w-6 text-ink-400" aria-hidden />}
      <p className="text-sm font-semibold text-ink-100">{title}</p>
      {body && <p className="max-w-sm text-sm text-ink-400">{body}</p>}
      <div className="mt-2">{action}</div>
    </div>
  );
}
