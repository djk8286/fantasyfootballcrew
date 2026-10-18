// apiRequest throws "API error: <status> <text> — <body>"; pull FastAPI's
// {"detail": "..."} out of that so admins see the real reason.
export function apiErrorMessage(err: unknown, fallback: string): string {
  if (!(err instanceof Error)) return fallback;
  const m = err.message.match(/—\s*(\{.*\})\s*$/);
  if (m) {
    try {
      const detail = (JSON.parse(m[1]) as { detail?: unknown }).detail;
      if (typeof detail === "string") return detail;
    } catch {
      // fall through to the raw message
    }
  }
  return err.message || fallback;
}

export function fmtDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}
