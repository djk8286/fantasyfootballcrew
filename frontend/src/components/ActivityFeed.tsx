"use client";

import { ArrowLeftRight, Trophy, UserPlus, ListOrdered } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";

export interface ActivityItem {
  id: string;
  kind: "trade" | "claim" | "draft" | "result";
  status: "done" | "pending" | "declined";
  at: string | null;
  week: number | null;
  team_ids: string[];
  text: string;
  cancel: { type: "trade" | "claim"; id: string } | null;
}

const ICONS = { trade: ArrowLeftRight, claim: UserPlus, draft: ListOrdered, result: Trophy } as const;
const dateFormat = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });

export function ActivityFeed({
  items,
  onCancel,
  busyId,
  empty = "Nothing has happened yet.",
}: {
  items: ActivityItem[];
  onCancel?: (item: ActivityItem) => void;
  busyId?: string | null;
  empty?: string;
}) {
  if (items.length === 0) return <p className="py-2 text-sm text-ink-400">{empty}</p>;
  return (
    <ul className="divide-y divide-ink-700">
      {items.map((item) => {
        const Icon = ICONS[item.kind];
        return (
          <li key={item.id} className="flex items-start gap-3 py-2.5">
            <Icon className="mt-0.5 h-4 w-4 shrink-0 text-ink-400" aria-hidden />
            <div className="min-w-0 flex-1">
              <p className={`text-sm ${item.status === "declined" ? "text-ink-400" : "text-ink-100"}`}>{item.text}</p>
              <p className="mt-0.5 flex items-center gap-2 text-xs text-ink-400">
                {item.at && <time dateTime={item.at}>{dateFormat.format(new Date(item.at))}</time>}
                {item.status === "pending" && <Badge tone="warn">Pending</Badge>}
                {item.status === "declined" && <Badge>Declined</Badge>}
              </p>
            </div>
            {item.cancel && onCancel && (
              <Button size="sm" variant="ghost" onClick={() => onCancel(item)} disabled={busyId === item.id}>
                Cancel
              </Button>
            )}
          </li>
        );
      })}
    </ul>
  );
}
