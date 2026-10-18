"use client";

import { useEffect, useState } from "react";
import { adminApi } from "@/lib/api-client";
import { AlertTriangle, DollarSign, Gauge } from "lucide-react";
import { apiErrorMessage } from "./adminUtils";

interface AiCost {
  days: number;
  calls: number;
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  cost_24h_usd: number;
  errors_24h: number;
  unpriced_calls: number;
  spend_cap: { cap_usd: number | null; spent_24h_usd: number; reached: boolean; blocked_calls_24h: number };
  daily: { date: string; calls: number; cost_usd: number; input_tokens: number; output_tokens: number }[];
  top_users: { user_id: string; username: string; calls: number; cost_usd: number }[];
  by_feature: { endpoint: string; calls: number; cost_usd: number }[];
  by_model: { model: string; calls: number; cost_usd: number; input_tokens: number; output_tokens: number }[];
}

function usd(n: number): string {
  if (n === 0) return "$0.00";
  if (n < 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}

function compact(n: number): string {
  return Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(n);
}

function Tile({ label, value, sub, warn }: { label: string; value: string; sub?: string; warn?: boolean }) {
  return (
    <div className={`bg-surface-800/60 border rounded-xl p-4 ${warn ? "border-amber-400/40" : "border-surface-700"}`}>
      <p className="text-surface-400 text-xs">{label}</p>
      <p className={`text-xl font-bold mt-1 ${warn ? "text-amber-400" : "text-white"}`}>{value}</p>
      {sub && <p className="text-surface-500 text-[11px] mt-0.5">{sub}</p>}
    </div>
  );
}

function CostTable({ title, rows }: { title: string; rows: { key: string; label: string; calls: number; cost: number }[] }) {
  return (
    <div className="bg-surface-800/60 border border-surface-700 rounded-2xl overflow-hidden">
      <div className="px-4 py-3 bg-surface-800 border-b border-surface-700">
        <h3 className="text-white font-bold text-sm">{title}</h3>
      </div>
      <table className="w-full text-sm">
        <tbody className="divide-y divide-surface-700/60">
          {rows.length === 0 ? (
            <tr><td className="px-4 py-4 text-surface-500 text-center">No cost data yet.</td></tr>
          ) : rows.map((r) => (
            <tr key={r.key}>
              <td className="px-4 py-2.5 text-surface-300">{r.label}</td>
              <td className="px-4 py-2.5 text-surface-500 text-xs text-right">{r.calls.toLocaleString()} calls</td>
              <td className="px-4 py-2.5 text-white font-medium text-right">{usd(r.cost)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function AiCostPanel() {
  const [data, setData] = useState<AiCost | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    adminApi.getAiCost()
      .then((d) => setData(d as AiCost))
      .catch((err: unknown) => setError(apiErrorMessage(err, "Failed to load AI cost")));
  }, []);

  if (error) {
    return <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm" role="alert">{error}</div>;
  }
  if (!data) return <p className="text-surface-500 text-sm">Loading AI cost...</p>;

  const cap = data.spend_cap;
  const capPct = cap.cap_usd ? Math.min(100, (cap.spent_24h_usd / cap.cap_usd) * 100) : 0;
  const maxDaily = Math.max(...data.daily.map((d) => d.cost_usd), 0);

  return (
    <div className="space-y-4">
      <h3 className="text-white font-bold text-sm flex items-center gap-2">
        <DollarSign className="w-4 h-4 text-gold-400" /> Estimated AI Spend
        <span className="text-surface-500 font-normal text-xs">last {data.days} days</span>
      </h3>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Tile label={`Spend (${data.days}d)`} value={usd(data.cost_usd)} sub={`${data.calls.toLocaleString()} calls`} />
        <Tile label="Spend (24h)" value={usd(data.cost_24h_usd)} />
        <Tile label="Tokens in / out" value={`${compact(data.input_tokens)} / ${compact(data.output_tokens)}`} />
        <Tile
          label="Errors (24h)"
          value={data.errors_24h.toLocaleString()}
          sub={data.unpriced_calls ? `${data.unpriced_calls} unpriced call(s), update AI_MODEL_PRICING` : undefined}
          warn={data.errors_24h > 0 || data.unpriced_calls > 0}
        />
      </div>

      <div className={`bg-surface-800/60 border rounded-2xl p-4 ${cap.reached ? "border-red-500/40" : "border-surface-700"}`}>
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <p className="text-white font-bold text-sm flex items-center gap-2">
            <Gauge className="w-4 h-4 text-gold-400" /> Daily Spend Cap
          </p>
          {cap.cap_usd == null ? (
            <span className="text-surface-500 text-xs">Not set (AI_DAILY_SPEND_CAP_USD)</span>
          ) : (
            <span className={`text-xs font-semibold ${cap.reached ? "text-red-400" : "text-surface-300"}`}>
              {usd(cap.spent_24h_usd)} of {usd(cap.cap_usd)} in the last 24h
            </span>
          )}
        </div>
        {cap.cap_usd != null && (
          <div className="mt-3 h-2 rounded-full bg-surface-900 overflow-hidden">
            <div
              className={`h-full rounded-full ${cap.reached ? "bg-red-500" : capPct > 80 ? "bg-amber-400" : "bg-gold-400"}`}
              style={{ width: `${capPct}%` }}
            />
          </div>
        )}
        {cap.reached && (
          <p className="text-red-400 text-xs mt-2 flex items-center gap-1.5">
            <AlertTriangle className="w-3.5 h-3.5" /> Cap reached: AI features are paused and show a &quot;budget reached&quot; message. {cap.blocked_calls_24h} call(s) blocked.
          </p>
        )}
      </div>

      <div className="bg-surface-800/60 border border-surface-700 rounded-2xl p-4">
        <p className="text-white font-bold text-sm mb-3">Daily Cost (UTC days)</p>
        {data.daily.length === 0 ? (
          <p className="text-surface-500 text-sm">No AI calls in this period.</p>
        ) : (
          <div className="flex items-end gap-1.5 h-32" role="img" aria-label="Daily AI cost">
            {data.daily.map((d) => (
              <div key={d.date} className="flex-1 flex flex-col items-center justify-end h-full min-w-0" title={`${d.date}: ${usd(d.cost_usd)} · ${d.calls} calls`}>
                <span className="text-[10px] text-surface-400 mb-1">{usd(d.cost_usd)}</span>
                <div className="w-full bg-gold-400/80 rounded-t" style={{ height: `${maxDaily ? Math.max(2, (d.cost_usd / maxDaily) * 80) : 2}%` }} />
                <span className="text-[10px] text-surface-500 mt-1 truncate w-full text-center">{d.date.slice(5)}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <CostTable title="Top Spenders" rows={data.top_users.map((u) => ({ key: u.user_id, label: u.username, calls: u.calls, cost: u.cost_usd }))} />
        <CostTable title="Cost by Feature" rows={data.by_feature.map((f) => ({ key: f.endpoint, label: f.endpoint.replace(/_/g, " "), calls: f.calls, cost: f.cost_usd }))} />
        <CostTable title="Cost by Model" rows={data.by_model.map((m) => ({ key: m.model, label: m.model, calls: m.calls, cost: m.cost_usd }))} />
      </div>
    </div>
  );
}
