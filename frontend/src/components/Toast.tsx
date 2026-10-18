"use client";

import { useEffect, useState, useCallback } from "react";
import { CheckCircle2 } from "lucide-react";

/** Minimal success toast: fixed bottom-right, auto-dismisses. */
export default function Toast({ message, onDone, ms = 3500 }: { message: string; onDone: () => void; ms?: number }) {
  useEffect(() => {
    if (!message) return;
    const t = setTimeout(onDone, ms);
    return () => clearTimeout(t);
  }, [message, onDone, ms]);
  if (!message) return null;
  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="toast"
      className="fixed bottom-6 right-6 z-[100] flex items-center gap-2 rounded-xl border border-emerald-500/40 bg-surface-800 px-4 py-3 text-sm text-emerald-300 shadow-xl"
    >
      <CheckCircle2 className="h-4 w-4 shrink-0" />
      {message}
    </div>
  );
}

export function useToast() {
  const [toast, setToast] = useState("");
  const clear = useCallback(() => setToast(""), []);
  return { toast, showToast: setToast, clearToast: clear };
}
