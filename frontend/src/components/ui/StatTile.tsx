import type { LucideIcon } from "lucide-react";

interface StatTileProps {
  icon?: LucideIcon;
  value: string | number;
  label: string;
  accent?: boolean;
}

export default function StatTile({ icon: Icon, value, label, accent = false }: StatTileProps) {
  return (
    <div className="flex flex-col items-center text-center gap-1">
      {Icon && (
        <Icon className={`w-4 h-4 mb-0.5 ${accent ? "text-gold-400" : "text-surface-500"}`} />
      )}
      <div
        className={`text-2xl md:text-3xl font-bold font-mono tabular-nums ${
          accent ? "text-gold-400" : "text-white"
        }`}
      >
        {value}
      </div>
      <div className="text-surface-500 text-[11px] uppercase tracking-wider font-semibold">
        {label}
      </div>
    </div>
  );
}
