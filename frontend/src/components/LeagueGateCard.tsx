"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { loginHref, type LeagueGate } from "@/lib/access-problem";

/** What a PRIVATE league shows a guest (log in, then come back to this
 * exact page) or a logged-in non-member. */
export default function LeagueGateCard({ gate }: { gate: LeagueGate }) {
  const pathname = usePathname();
  const search = useSearchParams()?.toString() ?? "";
  return (
    <div className="mx-auto max-w-5xl px-4 py-6 sm:px-6 lg:px-8">
      <div className="rounded-card border border-ink-700 bg-ink-900 px-4 py-3 text-sm text-ink-300">
        {gate.kind === "login" ? (
          <p>
            <Link href={loginHref(pathname, search)} className="font-semibold text-gold">
              Log in
            </Link>{" "}
            to see this league.
          </p>
        ) : (
          <p>
            This league is private. Only its members can see it.
            {gate.invited && " You have an invite: open the link in your email to join."}
          </p>
        )}
      </div>
    </div>
  );
}
