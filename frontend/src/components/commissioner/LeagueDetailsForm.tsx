"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { friendlyErrorMessage, leaguesApi } from "@/lib/api-client";
import { fieldClass, type AdminLeague } from "./types";

/** Name, description, privacy and conference names. */
export function LeagueDetailsForm({ league, onSaved }: { league: AdminLeague; onSaved: () => void }) {
  const [form, setForm] = useState({
    name: league.name,
    description: league.description ?? "",
    visibility: league.visibility,
    wanted_board_hidden: league.wanted_board_hidden,
    conference_a_name: league.conference_a_name ?? "",
    conference_b_name: league.conference_b_name ?? "",
  });
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setMsg(null);
    try {
      await leaguesApi.update(league.id, { ...form, description: form.description || null });
      setMsg({ ok: true, text: "Saved." });
      onSaved();
    } catch (err) {
      setMsg({ ok: false, text: friendlyErrorMessage(err, "Couldn't save the league.") });
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={save} className="grid gap-3 sm:max-w-xl">
      <label className="grid gap-1 text-sm text-ink-300">
        League name
        <input className={fieldClass} value={form.name} maxLength={80} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
      </label>
      <label className="grid gap-1 text-sm text-ink-300">
        Description
        <textarea
          className={`${fieldClass} h-auto py-2`}
          rows={2}
          value={form.description}
          onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
        />
      </label>
      <label className="grid gap-1 text-sm text-ink-300">
        Who can join
        <select
          className={fieldClass}
          value={form.visibility}
          onChange={(e) => setForm((f) => ({ ...f, visibility: e.target.value as AdminLeague["visibility"] }))}
        >
          <option value="open">Open. Anyone can claim a team.</option>
          <option value="invite_only">Invite only. People can ask to join.</option>
          <option value="private">Private. Invites only.</option>
        </select>
      </label>
      {form.visibility !== "private" && (
        <label className="flex items-center gap-2 text-sm text-ink-300">
          <input
            type="checkbox"
            checked={form.wanted_board_hidden}
            onChange={(e) => setForm((f) => ({ ...f, wanted_board_hidden: e.target.checked }))}
          />
          Hide from the Wanted Board
        </label>
      )}
      {league.league_type === "conference" && (
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="grid gap-1 text-sm text-ink-300">
            Conference A
            <input className={fieldClass} maxLength={40} value={form.conference_a_name} onChange={(e) => setForm((f) => ({ ...f, conference_a_name: e.target.value }))} />
          </label>
          <label className="grid gap-1 text-sm text-ink-300">
            Conference B
            <input className={fieldClass} maxLength={40} value={form.conference_b_name} onChange={(e) => setForm((f) => ({ ...f, conference_b_name: e.target.value }))} />
          </label>
        </div>
      )}
      <div className="flex items-center gap-3">
        <Button type="submit" variant="primary" disabled={saving || !form.name.trim()}>
          {saving ? "Saving" : "Save"}
        </Button>
        {msg && <span className={`text-sm ${msg.ok ? "text-win" : "text-loss"}`}>{msg.text}</span>}
      </div>
    </form>
  );
}
