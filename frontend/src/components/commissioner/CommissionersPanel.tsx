"use client";

import { useState } from "react";
import { Crown, Shield } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { friendlyErrorMessage, leaguesApi } from "@/lib/api-client";
import { fieldClass } from "./types";

export interface Person {
  user_id: string;
  username: string;
}

export interface Members {
  viewer_is_owner: boolean;
  commissioner: Person | null;
  co_commissioners: Person[];
  teams: { team_id: string; name: string; owner: Person | null; co_owner: Person | null }[];
  members: (Person & { teams: string[] })[];
}

/** Who runs the league. Only the commissioner can change it. */
export function CommissionersPanel({ leagueId, members, onChanged }: { leagueId: string; members: Members; onChanged: () => Promise<void> | void }) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const owner = members.viewer_is_owner;
  const coIds = new Set(members.co_commissioners.map((c) => c.user_id));
  const candidates = members.members.filter((m) => m.user_id !== members.commissioner?.user_id && !coIds.has(m.user_id));

  async function act(action: "add_co_commish" | "remove_co_commish" | "transfer", who: string, done: string) {
    setBusy(`${action}:${who}`);
    setMsg(null);
    try {
      await leaguesApi.manageCommissionerByName(leagueId, action, who);
      setMsg({ ok: true, text: done });
      setName("");
      await onChanged();
    } catch (err) {
      setMsg({ ok: false, text: friendlyErrorMessage(err, "That didn't work. Check the username.") });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-5">
      <ul className="divide-y divide-ink-700 rounded-control border border-ink-700">
        {members.commissioner && (
          <li className="flex items-center gap-3 px-3 py-2.5">
            <Crown className="h-4 w-4 text-gold" aria-hidden />
            <span className="flex-1 text-sm font-medium text-ink-100">{members.commissioner.username}</span>
            <Badge tone="you">Commissioner</Badge>
          </li>
        )}
        {members.co_commissioners.map((c) => (
          <li key={c.user_id} className="flex flex-wrap items-center gap-3 px-3 py-2.5">
            <Shield className="h-4 w-4 text-ink-300" aria-hidden />
            <span className="flex-1 text-sm text-ink-100">{c.username}</span>
            <Badge>Co-commissioner</Badge>
            {owner && (
              <>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={!!busy}
                  onClick={() =>
                    window.confirm(`Make ${c.username} the commissioner? You become a co-commissioner.`) &&
                    act("transfer", c.username, `${c.username} is now the commissioner.`)
                  }
                >
                  Make commissioner
                </Button>
                <Button size="sm" variant="danger" disabled={!!busy} onClick={() => act("remove_co_commish", c.username, `Removed ${c.username}.`)}>
                  Remove
                </Button>
              </>
            )}
          </li>
        ))}
      </ul>
      {owner ? (
        <form
          className="grid gap-2 sm:max-w-md"
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim()) act("add_co_commish", name.trim(), `Added ${name.trim()}.`);
          }}
        >
          <label htmlFor="co-commish" className="text-sm text-ink-300">
            Add a co-commissioner
          </label>
          <div className="flex gap-2">
            <input id="co-commish" list="league-members" className={fieldClass} value={name} onChange={(e) => setName(e.target.value)} placeholder="Username or email" />
            <Button type="submit" variant="primary" disabled={!name.trim() || !!busy}>
              Add
            </Button>
          </div>
          <datalist id="league-members">
            {candidates.map((m) => (
              <option key={m.user_id} value={m.username}>
                {m.teams.join(", ")}
              </option>
            ))}
          </datalist>
          <p className="text-xs text-ink-400">Co-commissioners can run the league. Only you can change who runs it.</p>
        </form>
      ) : (
        <p className="text-sm text-ink-400">Only the commissioner can add or remove co-commissioners.</p>
      )}
      {msg && <p className={`text-sm ${msg.ok ? "text-win" : "text-loss"}`}>{msg.text}</p>}
    </div>
  );
}
