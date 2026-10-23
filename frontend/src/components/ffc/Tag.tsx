"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { FfcIcon, type FfcIconName } from "./icons";

export type TagKind = "block" | "cut" | "leading" | "tied" | "runnerup";

const KIND: Record<TagKind, { icon: FfcIconName; cls: string }> = {
  block: { icon: "warn", cls: "bg-ffc-cut/14 border-ffc-cut/55 text-ffc-cut-text" },
  cut: { icon: "blade", cls: "bg-ffc-cut/14 border-ffc-cut/40 text-ffc-cut-text" },
  leading: { icon: "up", cls: "bg-ffc-finale/14 border-ffc-finale/50 text-ffc-finale" },
  tied: { icon: "equals", cls: "bg-ffc-text-muted/12 border-ffc-text-muted/45 text-ffc-text" },
  runnerup: { icon: "medal", cls: "bg-ffc-text-muted/12 border-ffc-text-muted/45 text-ffc-text-muted" },
};

const HOVER_DELAY_MS = 300;

/** Status tag. With `tip`, it is focusable and owns a role=tooltip. */
export function Tag({ kind, children, tip, compact = false, align = "center" }: { kind: TagKind; children: ReactNode; tip?: string; compact?: boolean; align?: TipAlign }) {
  const k = KIND[kind];
  const body = (
    <>
      <FfcIcon name={k.icon} size={12} className="shrink-0" />
      <span className="whitespace-nowrap">{children}</span>
    </>
  );
  const cls = `inline-flex items-center gap-[5px] rounded border px-2 font-ffc-mono text-[11px] font-semibold leading-[14px] tracking-[0.06em] ${compact ? "h-5" : "h-[22px]"} ${k.cls}`;
  if (!tip) return <span className={cls}>{body}</span>;
  return <TipTag className={cls} tip={tip} align={align}>{body}</TipTag>;
}

type TipAlign = "center" | "start" | "end";
const ALIGN: Record<TipAlign, [string, string]> = {
  center: ["left-1/2 -translate-x-1/2", "left-1/2 -translate-x-1/2"],
  start: ["left-0", "left-4 -translate-x-1/2"],
  end: ["right-0", "right-4 translate-x-1/2"],
};

function TipTag({ className, tip, children, align }: { className: string; tip: string; children: ReactNode; align: TipAlign }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clear = () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  };
  useEffect(() => clear, []);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <span
      className="relative inline-flex"
      onMouseEnter={() => {
        clear();
        timer.current = setTimeout(() => setOpen(true), HOVER_DELAY_MS);
      }}
      onMouseLeave={() => {
        clear();
        setOpen(false);
      }}
    >
      <span
        tabIndex={0}
        aria-describedby={id}
        className={`${className} cursor-help outline-none focus-visible:ring-2 focus-visible:ring-ffc-focus focus-visible:ring-offset-2 focus-visible:ring-offset-ffc-bg`}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={() => setOpen((o) => !o)}
      >
        {children}
      </span>
      <span
        id={id}
        role="tooltip"
        className={`ffc-tooltip pointer-events-none absolute bottom-full z-30 mb-2 w-max max-w-[240px] ${ALIGN[align][0]} rounded-md border border-ffc-border-strong bg-ffc-raised px-2.5 py-1.5 text-left font-ffc-ui text-xs font-medium leading-4 text-ffc-text normal-case tracking-normal shadow-lg ${open ? "" : "hidden"}`}
      >
        {tip}
        <span
          aria-hidden="true"
          className={`absolute top-full h-0 w-0 ${ALIGN[align][1]} border-x-[6px] border-t-[6px] border-x-transparent border-t-ffc-border-strong`}
        />
      </span>
    </span>
  );
}
