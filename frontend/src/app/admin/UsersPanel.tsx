"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { adminApi } from "@/lib/api-client";
import { AlertTriangle, Ban, ChevronLeft, ChevronRight, KeyRound, LogOut, MailCheck, MoreHorizontal, Search, Shield, ShieldOff, Trash2, UserCheck } from "lucide-react";
import { apiErrorMessage } from "./adminUtils";

export interface AdminUser {
  id: string;
  username: string;
  email: string;
  provider: string;
  email_verified: boolean;
  is_admin: boolean;
  is_suspended: boolean;
  suspended_at: string | null;
  suspended_reason: string | null;
  has_password: boolean;
  created_at: string;
}

interface UsersPage {
  items: AdminUser[];
  total: number;
  limit: number;
  offset: number;
}

const PAGE_SIZE = 25;

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

type Action = "suspend" | "unsuspend" | "force-logout" | "reset" | "verify" | "grant-admin" | "revoke-admin";

const CONFIRM_TEXT: Partial<Record<Action, (u: AdminUser) => string>> = {
  "force-logout": (u) => `Sign ${u.username} out of every device? They can log straight back in.`,
  reset: (u) => `Email a password reset link to ${u.email}?`,
  verify: (u) => `Resend the verification email to ${u.email}?`,
  "grant-admin": (u) => `Give ${u.username} full admin access?`,
  "revoke-admin": (u) => `Remove ${u.username}'s admin access?`,
  unsuspend: (u) => `Restore ${u.username}'s access?`,
};

const SUCCESS_TEXT: Record<Action, string> = {
  suspend: "suspended and signed out",
  unsuspend: "unsuspended",
  "force-logout": "signed out everywhere",
  reset: "password reset email sent",
  verify: "verification email sent",
  "grant-admin": "is now an admin",
  "revoke-admin": "is no longer an admin",
};

export default function UsersPanel({
  currentUserId, onRequestDelete, refreshKey, onTotalChange,
}: {
  currentUserId: string | null;
  onRequestDelete: (u: AdminUser) => void;
  refreshKey: number;
  onTotalChange: (total: number) => void;
}) {
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<UsersPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const t = setTimeout(() => { setDebouncedQuery(query); setOffset(0); }, 250);
    return () => clearTimeout(t);
  }, [query]);

  const load = useCallback(() => {
    adminApi.getUsers({ q: debouncedQuery, status: statusFilter, limit: PAGE_SIZE, offset })
      .then((data) => {
        const p = data as UsersPage;
        setPage(p);
        setError(null);
        if (!debouncedQuery && !statusFilter) onTotalChange(p.total);
      })
      .catch((err: unknown) => setError(apiErrorMessage(err, "Failed to load users")));
  }, [debouncedQuery, statusFilter, offset, onTotalChange]);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  useEffect(() => {
    if (!openMenu) return;
    const close = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setOpenMenu(null);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [openMenu]);

  const run = (u: AdminUser, action: Action) => {
    setOpenMenu(null);
    let reason: string | undefined;
    if (action === "suspend") {
      const r = window.prompt(`Suspend ${u.username}? They'll be signed out and blocked from logging in.\n\nOptional reason (only admins see this):`, "");
      if (r === null) return;
      reason = r;
    } else {
      const confirmText = CONFIRM_TEXT[action];
      if (confirmText && !window.confirm(confirmText(u))) return;
    }
    const call: Record<Action, () => Promise<unknown>> = {
      suspend: () => adminApi.suspendUser(u.id, reason),
      unsuspend: () => adminApi.unsuspendUser(u.id),
      "force-logout": () => adminApi.forceLogoutUser(u.id),
      reset: () => adminApi.sendPasswordReset(u.id),
      verify: () => adminApi.resendVerification(u.id),
      "grant-admin": () => adminApi.setUserAdmin(u.id, true),
      "revoke-admin": () => adminApi.setUserAdmin(u.id, false),
    };
    setBusy(u.id);
    call[action]()
      .then(() => { setNotice({ kind: "ok", text: `${u.username}: ${SUCCESS_TEXT[action]}` }); load(); })
      .catch((err: unknown) => setNotice({ kind: "error", text: `${u.username}: ${apiErrorMessage(err, "Action failed")}` }))
      .finally(() => setBusy(null));
  };

  const total = page?.total ?? 0;
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + PAGE_SIZE, total);

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative flex-1 min-w-[220px] max-w-md">
          <Search className="w-4 h-4 text-surface-500 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search username or email"
            aria-label="Search users"
            className="w-full pl-9 pr-3 py-2 bg-surface-800 border border-surface-700 rounded-xl text-sm text-white placeholder:text-surface-500 focus:outline-none focus:ring-1 focus:ring-gold-400"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setOffset(0); }}
          aria-label="Filter users"
          className="px-3 py-2 bg-surface-800 border border-surface-700 rounded-xl text-sm text-white focus:outline-none focus:ring-1 focus:ring-gold-400"
        >
          <option value="">All users</option>
          <option value="suspended">Suspended</option>
          <option value="admin">Admins</option>
          <option value="unverified">Unverified</option>
        </select>
      </div>

      {notice && (
        <div
          role="status"
          className={`p-3 rounded-lg text-sm border flex items-center justify-between gap-3 ${
            notice.kind === "ok" ? "bg-green-500/10 border-green-500/30 text-green-400" : "bg-red-500/10 border-red-500/30 text-red-400"
          }`}
        >
          {notice.text}
          <button onClick={() => setNotice(null)} className="text-xs opacity-70 hover:opacity-100">Dismiss</button>
        </div>
      )}
      {error && (
        <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm" role="alert">{error}</div>
      )}

      <div className="bg-surface-800/60 border border-surface-700 rounded-2xl overflow-visible overflow-x-auto">
        <table className="w-full text-sm min-w-[760px]">
          <thead>
            <tr className="border-b border-surface-700 text-left text-surface-400 text-xs uppercase tracking-wider">
              <th className="px-4 py-3 font-medium">Username</th>
              <th className="px-4 py-3 font-medium">Email</th>
              <th className="px-4 py-3 font-medium">Provider</th>
              <th className="px-4 py-3 font-medium">Verified</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">Joined</th>
              <th className="px-4 py-3 font-medium" />
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-700/60">
            {page && page.items.length === 0 && (
              <tr><td colSpan={7} className="px-4 py-6 text-center text-surface-500">No users match.</td></tr>
            )}
            {page?.items.map((u) => {
              const isSelf = u.id === currentUserId;
              return (
                <tr key={u.id} className={`transition-colors ${u.is_suspended ? "bg-red-500/5" : "hover:bg-surface-900/40"}`}>
                  <td className="px-4 py-3 text-white font-medium">
                    {u.username}
                    {isSelf && <span className="ml-2 text-[9px] text-surface-500 uppercase tracking-wider bg-surface-700 px-1.5 py-0.5 rounded">You</span>}
                  </td>
                  <td className="px-4 py-3 text-surface-300">{u.email}</td>
                  <td className="px-4 py-3 text-surface-400">{u.provider}</td>
                  <td className="px-4 py-3">
                    {u.email_verified ? (
                      <span className="text-green-400 text-xs">Yes</span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-amber-400 text-xs">
                        <AlertTriangle className="w-3 h-3" /> No
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-col gap-1">
                      {u.is_admin && (
                        <span className="inline-flex items-center gap-1 text-gold-400 text-xs font-semibold">
                          <Shield className="w-3 h-3" /> Admin
                        </span>
                      )}
                      {u.is_suspended && (
                        <span className="inline-flex items-center gap-1 text-red-400 text-xs font-semibold" title={u.suspended_reason || undefined}>
                          <Ban className="w-3 h-3" /> Suspended{u.suspended_reason ? `: ${u.suspended_reason}` : ""}
                        </span>
                      )}
                      {!u.is_admin && !u.is_suspended && <span className="text-surface-500 text-xs">Active</span>}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-surface-500 text-xs">{fmtDate(u.created_at)}</td>
                  <td className="px-4 py-3 text-right relative">
                    {!isSelf && (
                      <button
                        onClick={() => setOpenMenu(openMenu === u.id ? null : u.id)}
                        disabled={busy === u.id}
                        aria-label={`Actions for ${u.username}`}
                        aria-haspopup="menu"
                        aria-expanded={openMenu === u.id}
                        className="text-surface-400 hover:text-white transition-colors disabled:opacity-40"
                      >
                        <MoreHorizontal className="w-5 h-5" />
                      </button>
                    )}
                    {openMenu === u.id && (
                      <div
                        ref={menuRef}
                        role="menu"
                        className="absolute right-4 top-10 z-30 w-56 bg-surface-800 border border-surface-700 rounded-xl shadow-xl py-1 text-left"
                      >
                        {u.is_suspended ? (
                          <MenuItem icon={<UserCheck className="w-4 h-4" />} label="Unsuspend" onClick={() => run(u, "unsuspend")} />
                        ) : (
                          <MenuItem icon={<Ban className="w-4 h-4" />} label="Suspend…" onClick={() => run(u, "suspend")} danger />
                        )}
                        <MenuItem icon={<LogOut className="w-4 h-4" />} label="Force sign-out" onClick={() => run(u, "force-logout")} />
                        {u.has_password && (
                          <MenuItem icon={<KeyRound className="w-4 h-4" />} label="Send password reset" onClick={() => run(u, "reset")} />
                        )}
                        {!u.email_verified && (
                          <MenuItem icon={<MailCheck className="w-4 h-4" />} label="Resend verification" onClick={() => run(u, "verify")} />
                        )}
                        {u.is_admin ? (
                          <MenuItem icon={<ShieldOff className="w-4 h-4" />} label="Revoke admin" onClick={() => run(u, "revoke-admin")} danger />
                        ) : (
                          <MenuItem icon={<Shield className="w-4 h-4" />} label="Make admin" onClick={() => run(u, "grant-admin")} />
                        )}
                        <div className="my-1 border-t border-surface-700" />
                        <MenuItem icon={<Trash2 className="w-4 h-4" />} label="Delete account…" onClick={() => { setOpenMenu(null); onRequestDelete(u); }} danger />
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between text-xs text-surface-400">
        <span>{total ? `${from}–${to} of ${total.toLocaleString()}` : ""}</span>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            disabled={offset === 0}
            aria-label="Previous page"
            className="p-1.5 rounded-lg bg-surface-800 border border-surface-700 hover:text-white disabled:opacity-40 transition-colors"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <button
            onClick={() => setOffset(offset + PAGE_SIZE)}
            disabled={offset + PAGE_SIZE >= total}
            aria-label="Next page"
            className="p-1.5 rounded-lg bg-surface-800 border border-surface-700 hover:text-white disabled:opacity-40 transition-colors"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

function MenuItem({ icon, label, onClick, danger }: { icon: React.ReactNode; label: string; onClick: () => void; danger?: boolean }) {
  return (
    <button
      role="menuitem"
      onClick={onClick}
      className={`w-full flex items-center gap-2 px-3 py-2 text-sm transition-colors hover:bg-surface-700/60 ${danger ? "text-red-400" : "text-surface-200"}`}
    >
      {icon} {label}
    </button>
  );
}
