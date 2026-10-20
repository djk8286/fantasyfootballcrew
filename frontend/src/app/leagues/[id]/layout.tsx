import type { ReactNode } from "react";
import LeagueShell from "@/components/LeagueShell";

export default async function LeagueLayout({ children, params }: { children: ReactNode; params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <LeagueShell leagueId={id}>{children}</LeagueShell>;
}
