"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowLeftRight, Bot, Check, Pencil, Plus, Trash2, X } from "lucide-react";
import Avatar from "@/components/Avatar";
import AvatarEditor from "@/components/AvatarEditor";
import { ConferenceBadge, conferenceShortLabel } from "@/components/LeagueBadges";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { friendlyErrorMessage, isCurrentUser, teamsApi } from "@/lib/api-client";
import { ownerLabel } from "@/lib/owner-label";
import { fieldClass, type AdminLeague, type AdminTeam } from "./types";

/** Every team with its owners and the commissioner's fixes: rename, avatar,
 * assign or remove owners, swap conference, delete, add CPU teams. */
export function TeamsAdmin({
  league,
  teams,
  onChanged,
}: {
  league: AdminLeague;
  teams: AdminTeam[];
  onChanged: () => Promise<void> | void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null);
  const [avatarFor, setAvatarFor] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const isTwoMan = league.league_type === "two_man";
  const openSlots = Math.max(0, league.max_teams - teams.length);

  async function run(key: string, fn: () => Promise<unknown>, fallback: string) {
    setBusy(key);
    setError("");
    try {
      await fn();
      await onChanged();
    } catch (err) {
      setError(friendlyErrorMessage(err, fallback));
    } finally {
      setBusy(null);
    }
  }

  function ask(prompt: string): string | null {
    const v = window.prompt(prompt);
    return v && v.trim() ? v.trim() : null;
  }

  function ownerText(t: AdminTeam): string {
    const o = ownerLabel({
      ownerId: t.owner_id,
      coOwnerId: t.co_owner_id,
      isCpu: t.is_cpu,
      commissionerId: league.commissioner_id,
      isOwnerMe: isCurrentUser(t.owner_id),
      isCoOwnerMe: !!t.co_owner_id && isCurrentUser(t.co_owner_id),
    });
    if (!o.isHuman) return o.label;
    const names = [t.owner_username, t.co_owner_username].filter(Boolean);
    return names.length ? names.join(" and ") : o.label;
  }

  return (
    <div>
      {avatarFor && (
        <AvatarEditor
          title="Team avatar"
          currentUrl={teams.find((t) => t.id === avatarFor)?.avatar_url ?? null}
          onSave={async (url: string) => {
            await teamsApi.update(avatarFor, { avatar_url: url });
            await onChanged();
            setAvatarFor(null);
          }}
          onClose={() => setAvatarFor(null)}
        />
      )}
      {error && (
        <p role="alert" className="mb-3 rounded-control border border-loss/40 bg-loss/10 px-3 py-2 text-sm text-loss">
          {error}
        </p>
      )}
      <ul className="divide-y divide-ink-700">
        {teams.map((t) => {
          const human = !t.is_cpu && !!t.owner_id && t.owner_id !== "placeholder" && t.owner_id !== "cpu";
          const other = t.conference === "A" ? "B" : "A";
          return (
            <li key={t.id} className="flex flex-wrap items-center gap-3 py-3">
              <button
                type="button"
                onClick={() => setAvatarFor(t.id)}
                aria-label={`Change avatar for ${t.name}`}
                className="shrink-0 rounded-full hover:opacity-80"
              >
                <Avatar url={t.avatar_url} size={32} />
              </button>
              <div className="min-w-0 flex-1 basis-48">
                {renaming?.id === t.id ? (
                  <form
                    className="flex items-center gap-1.5"
                    onSubmit={(e) => {
                      e.preventDefault();
                      const name = renaming.name.trim();
                      if (!name) return setRenaming(null);
                      run(t.id, () => teamsApi.update(t.id, { name }), "Couldn't rename the team.").then(() => setRenaming(null));
                    }}
                  >
                    <input
                      autoFocus
                      aria-label="Team name"
                      className={`${fieldClass} h-8 max-w-56`}
                      value={renaming.name}
                      onChange={(e) => setRenaming({ id: t.id, name: e.target.value })}
                      onKeyDown={(e) => e.key === "Escape" && setRenaming(null)}
                    />
                    <Button type="submit" size="sm" variant="ghost" aria-label="Save name" disabled={busy === t.id}>
                      <Check className="h-4 w-4" />
                    </Button>
                    <Button size="sm" variant="ghost" aria-label="Cancel rename" onClick={() => setRenaming(null)}>
                      <X className="h-4 w-4" />
                    </Button>
                  </form>
                ) : (
                  <div className="flex flex-wrap items-center gap-2">
                    <Link href={`/leagues/${league.id}/teams/${t.id}`} className="truncate text-sm font-medium text-ink-100 hover:text-gold">
                      {t.name}
                    </Link>
                    <button
                      type="button"
                      onClick={() => setRenaming({ id: t.id, name: t.name })}
                      aria-label={`Rename ${t.name}`}
                      className="text-ink-400 hover:text-gold"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                    {league.league_type === "conference" && (
                      <ConferenceBadge conference={t.conference} displayName={conferenceShortLabel(t.conference, league.conference_a_name, league.conference_b_name)} />
                    )}
                  </div>
                )}
                <p className="mt-0.5 flex items-center gap-1.5 text-xs text-ink-400">
                  {!human && <Bot className="h-3.5 w-3.5" aria-hidden />}
                  {ownerText(t)}
                  {t.owner_id === league.commissioner_id && <Badge tone="you">Commish</Badge>}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                {human ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={busy === t.id}
                    onClick={() =>
                      window.confirm(`Remove the owner from ${t.name}? A co-owner takes over. With no co-owner, the team goes back to CPU.`) &&
                      run(t.id, () => teamsApi.removeOwner(t.id), "Couldn't remove the owner.")
                    }
                  >
                    Remove owner
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={busy === t.id}
                    onClick={() => {
                      const who = ask("Assign this team to (username or email)");
                      if (who) run(t.id, () => teamsApi.assignOwner(t.id, who), "Couldn't assign the owner.");
                    }}
                  >
                    Assign owner
                  </Button>
                )}
                {t.co_owner_id ? (
                  <Button size="sm" variant="ghost" disabled={busy === t.id} onClick={() => run(t.id, () => teamsApi.removeCoOwner(t.id), "Couldn't remove the co-owner.")}>
                    Remove co-owner
                  </Button>
                ) : isTwoMan && human ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={busy === t.id}
                    onClick={() => {
                      const who = ask("Assign a co-owner (username or email)");
                      if (who) run(t.id, () => teamsApi.assignCoOwner(t.id, who), "Couldn't assign the co-owner.");
                    }}
                  >
                    Assign co-owner
                  </Button>
                ) : null}
                {league.league_type === "conference" && t.conference && (
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={busy === t.id}
                    aria-label={`Move ${t.name} to ${conferenceShortLabel(other, league.conference_a_name, league.conference_b_name)}`}
                    onClick={() => run(t.id, () => teamsApi.update(t.id, { conference: other }), "Couldn't move the team.")}
                  >
                    <ArrowLeftRight className="h-4 w-4" />
                  </Button>
                )}
                {confirmDelete === t.id ? (
                  <>
                    <Button size="sm" variant="danger" disabled={busy === t.id} onClick={() => run(t.id, () => teamsApi.delete(t.id), "Couldn't delete the team.").then(() => setConfirmDelete(null))}>
                      Delete
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(null)}>
                      Keep
                    </Button>
                  </>
                ) : (
                  <Button size="sm" variant="ghost" aria-label={`Delete ${t.name}`} onClick={() => setConfirmDelete(t.id)}>
                    <Trash2 className="h-4 w-4" />
                  </Button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
      {openSlots > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-ink-700 pt-3">
          <span className="mr-auto text-sm text-ink-400">
            {openSlots} open {openSlots === 1 ? "spot" : "spots"}.
          </span>
          <Button size="sm" disabled={busy === "cpu"} onClick={() => run("cpu", () => teamsApi.bulkAddCpu(league.id, 1, `${league.name} Team`), "Couldn't add a team.")}>
            <Plus className="h-4 w-4" /> Add a CPU team
          </Button>
          <Button size="sm" disabled={busy === "cpu"} onClick={() => run("cpu", () => teamsApi.bulkAddCpu(league.id, openSlots), "Couldn't add CPU teams.")}>
            <Bot className="h-4 w-4" /> Fill with CPU teams
          </Button>
        </div>
      )}
    </div>
  );
}
