"use client";

import { useState } from "react";
import { Users } from "lucide-react";
import { Badge, InjuryTag, PositionChip } from "@/components/ui/Badge";
import { Button, buttonClasses } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Num, StatBlock } from "@/components/ui/Num";
import { Skeleton, SkeletonRows } from "@/components/ui/Skeleton";
import { Tabs } from "@/components/ui/Tabs";

const SLOTS = ["QB", "RB", "WR", "TE", "FLEX", "SUPERFLEX", "K", "DEF", "DL", "LB", "DB", "IDP_FLEX"];

const ROWS = [
  { slot: "QB", name: "Jordan Love", team: "GB", status: null, pts: 20.24 },
  { slot: "RB", name: "Chuba Hubbard", team: "CAR", status: "Questionable", pts: 22.1 },
  { slot: "WR", name: "Chris Olave", team: "NO", status: null, pts: 14.3 },
  { slot: "TE", name: "Tucker Kraft", team: "GB", status: "Doubtful", pts: 8.7 },
  { slot: "FLEX", name: "Tre Harris", team: "LAC", status: null, pts: null, bye: true },
  { slot: "K", name: "Cairo Santos", team: "CHI", status: "Out", pts: 0 },
];

const TABS = [
  { id: "roster", label: "Roster" },
  { id: "schedule", label: "Schedule" },
  { id: "moves", label: "Moves" },
] as const;

export default function Showcase() {
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>("roster");

  return (
    <div className="min-h-full bg-ink-950 px-4 py-8 text-ink-100">
      <div className="mx-auto flex max-w-4xl flex-col gap-6">
        <header>
          <h1 className="text-title font-semibold">UI components</h1>
          <p className="text-sm text-ink-400">Shared pieces for the league pages. Not linked from the app.</p>
        </header>

        <Card>
          <CardHeader title="Buttons" />
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="primary">Set lineup</Button>
            <Button>Auto-fill</Button>
            <Button variant="ghost">Cancel</Button>
            <Button variant="danger">Drop player</Button>
            <Button size="sm">Small</Button>
            <Button disabled>Disabled</Button>
            <a href="#" className={buttonClasses("secondary", "sm")}>Link as button</a>
          </div>
        </Card>

        <Card>
          <CardHeader title="Positions and tags" />
          <div className="flex flex-wrap gap-2">
            {SLOTS.map((s) => (
              <PositionChip key={s} pos={s} />
            ))}
            <PositionChip pos="D/ST" />
            <PositionChip pos="BN" />
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {["Questionable", "Doubtful", "Out", "IR", "PUP", "Suspended"].map((s) => (
              <InjuryTag key={s} status={s} />
            ))}
            <InjuryTag onBye />
            <Badge tone="win">W</Badge>
            <Badge tone="loss">L</Badge>
            <Badge tone="warn">2 issues</Badge>
            <Badge tone="live">Live</Badge>
            <Badge tone="you">You</Badge>
            <Badge>Final</Badge>
          </div>
        </Card>

        <Card you>
          <CardHeader title="Your team" action={<Badge tone="you">You</Badge>} />
          <div className="flex flex-wrap gap-8">
            <StatBlock label="Record">1-0</StatBlock>
            <StatBlock label="Rank">1st</StatBlock>
            <StatBlock label="PF"><Num value={102.14} digits={2} size="lg" /></StatBlock>
            <StatBlock label="PA"><Num value={14.6} digits={2} size="lg" /></StatBlock>
            <StatBlock label="Margin"><Num value={87.54} digits={2} signed size="lg" className="text-win" /></StatBlock>
          </div>
          <div className="mt-4 flex items-baseline gap-3">
            <Num value={102.14} digits={2} size="score" className="text-gold" />
            <span className="text-ink-400">vs</span>
            <Num value={14.6} digits={2} size="score" className="text-ink-300" />
          </div>
        </Card>

        <Card>
          <div className="mb-3 flex items-center justify-between gap-3">
            <Tabs tabs={TABS} value={tab} onChange={setTab} label="Team sections" />
            <Button size="sm">Auto-fill</Button>
          </div>
          {tab === "roster" && (
            <div role="tabpanel" className="divide-y divide-ink-700">
              {ROWS.map((r) => (
                <div key={r.name} className="flex h-14 items-center gap-3">
                  <PositionChip pos={r.slot} />
                  <div className="flex min-w-0 flex-1 items-center gap-2">
                    <span className="truncate text-sm font-medium">{r.name}</span>
                    <span className="text-xs text-ink-400">{r.team}</span>
                    <InjuryTag status={r.status} onBye={r.bye} />
                  </div>
                  <Num value={r.pts} digits={2} className="w-16 text-right" />
                </div>
              ))}
            </div>
          )}
          {tab === "schedule" && (
            <div role="tabpanel">
              <SkeletonRows rows={4} />
            </div>
          )}
          {tab === "moves" && (
            <div role="tabpanel">
              <EmptyState
                icon={Users}
                title="No moves yet"
                body="Trades, waiver claims and free-agent adds will show up here."
                action={<Button variant="primary" size="sm">Browse free agents</Button>}
              />
            </div>
          )}
        </Card>

        <Card>
          <CardHeader title="Loading" />
          <div className="flex flex-col gap-2">
            <Skeleton className="h-6 w-1/3" />
            <Skeleton className="h-4 w-2/3" />
            <SkeletonRows rows={3} />
          </div>
        </Card>
      </div>
    </div>
  );
}
