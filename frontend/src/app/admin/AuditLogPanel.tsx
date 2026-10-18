"use client";

import { useCallback, useEffect, useState } from "react";
import { adminApi } from "@/lib/api-client";
import { ChevronLeft, ChevronRight, ScrollText } from "lucide-react";
import { apiErrorMessage, fmtDateTime } from "./adminUtils";

interface AuditEntry {
  id: string;
  admin_user_id: string;
  admin_username: string;
  action: string;
  target_type: string;
  target_id: string;
  target_label: string | null;
  details: Record<string, unknown> | null;
  created_at: string;
}

const PAGE_SIZE = 50;

const ACTION_LABEL: Record<string, { label: string; className: string }> = {
  "user.suspend": { label: "Suspended user", className: "text-red-400" },
  "user.unsuspend": { label: "Unsuspended user", className: "text-green-400" },
  "user.force_logout": { label: "Forced sign-out", className: "text-amber-400" },
  "user.send_password_reset": { label: "Sent password reset", className: "text-surface-200" },
  "user.resend_verification": { label: "Resent verification", className: "text-surface-200" },
  "user.grant_admin": { label: "Granted admin", className: "text-gold-400" },
  "user.revoke_admin": { label: "Revoked admin", className: "text-amber-400" },
  "user.delete": { label: "Deleted user", className: "text-red-400" },
  "league.delete": { label: "Deleted league", className: "text-red-400" },
};

export default function AuditLogPanel({ refreshKey }: { refreshKey: number }) {
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<{ items: AuditEntry[]; total: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    adminApi.getAuditLog({ limit: PAGE_SIZE, offset })
      .then((d) => { setData(d as { items: AuditEntry[]; total: number }); setError(null); })
      .catch((err: unknown) => setError(apiErrorMessage(err, "Failed to load audit log")));
  }, [offset]);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  const total = data?.total ?? 0;

  return (
    <div className="space-y-3">
      {error && <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm" role="alert">{error}</div>}
      <div className="bg-surface-800/60 border border-surface-700 rounded-2xl overflow-hidden overflow-x-auto">
        <table className="w-full text-sm min-w-[720px]">
          <thead>
            <tr className="border-b border-surface-700 text-left text-surface-400 text-xs uppercase tracking-wider">
              <th className="px-4 py-3 font-medium">When</th>
              <th className="px-4 py-3 font-medium">Admin</th>
              <th className="px-4 py-3 font-medium">Action</th>
              <th className="px-4 py-3 font-medium">Target</th>
              <th className="px-4 py-3 font-medium">Details</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-700/60">
            {data && data.items.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-surface-500">
                  <ScrollText className="w-5 h-5 mx-auto mb-2 text-surface-600" />
                  No admin actions recorded yet.
                </td>
              </tr>
            )}
            {data?.items.map((e) => {
              const a = ACTION_LABEL[e.action] ?? { label: e.action, className: "text-surface-200" };
              const details = e.details ? Object.entries(e.details).filter(([, v]) => v !== null && v !== "") : [];
              return (
                <tr key={e.id} className="hover:bg-surface-900/40 transition-colors">
                  <td className="px-4 py-3 text-surface-400 text-xs whitespace-nowrap">{fmtDateTime(e.created_at)}</td>
                  <td className="px-4 py-3 text-white font-medium">{e.admin_username}</td>
                  <td className={`px-4 py-3 text-xs font-semibold ${a.className}`}>{a.label}</td>
                  <td className="px-4 py-3 text-surface-300">
                    {e.target_label || "—"}
                    <span className="block text-surface-500 text-[11px]">{e.target_type} · {e.target_id.slice(0, 8)}</span>
                  </td>
                  <td className="px-4 py-3 text-surface-400 text-xs">
                    {details.length ? details.map(([k, v]) => `${k}: ${String(v)}`).join(" · ") : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {total > PAGE_SIZE && (
        <div className="flex items-center justify-between text-xs text-surface-400">
          <span>{offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total.toLocaleString()}</span>
          <div className="flex items-center gap-1">
            <button onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))} disabled={offset === 0} aria-label="Previous page"
              className="p-1.5 rounded-lg bg-surface-800 border border-surface-700 hover:text-white disabled:opacity-40 transition-colors">
              <ChevronLeft className="w-4 h-4" />
            </button>
            <button onClick={() => setOffset(offset + PAGE_SIZE)} disabled={offset + PAGE_SIZE >= total} aria-label="Next page"
              className="p-1.5 rounded-lg bg-surface-800 border border-surface-700 hover:text-white disabled:opacity-40 transition-colors">
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
