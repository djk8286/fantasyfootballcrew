// Background AI analysis jobs (POST .../jobs -> poll GET /api/v1/ai/jobs/{id}).
// Generation takes 20-40 s; holding one request open that long meant a
// navigation (or a dropped connection) lost the result even though the
// server finished and saved it to history (QA regression 2026-10-19).

export type JobStatus = { job_id: string; status: "pending" | "done" | "error"; analysis?: string | null; error?: string | null };

export class JobTimeoutError extends Error {
  constructor() {
    super("The analysis is taking longer than expected. It will appear under Recent when it finishes.");
    this.name = "JobTimeoutError";
  }
}

export interface PollOptions {
  intervalMs?: number;
  timeoutMs?: number;
  sleep?: (ms: number) => Promise<void>;
  now?: () => number;
  isCancelled?: () => boolean;
}

/** Poll `fetchStatus` until the job is done/error or `timeoutMs` passes.
 * Resolves with the analysis text; rejects with the job's error message,
 * JobTimeoutError, or whatever fetchStatus throws (e.g. 404 = expired). */
export async function pollJob(fetchStatus: () => Promise<JobStatus>, opts: PollOptions = {}): Promise<string | null> {
  const { intervalMs = 2000, timeoutMs = 120_000 } = opts;
  const sleep = opts.sleep ?? ((ms: number) => new Promise<void>((r) => setTimeout(r, ms)));
  const now = opts.now ?? (() => Date.now());
  const deadline = now() + timeoutMs;
  for (;;) {
    if (opts.isCancelled?.()) return null;
    const s = await fetchStatus();
    if (s.status === "done") return s.analysis ?? "";
    if (s.status === "error") throw new Error(s.error || "The analysis failed. Please try again.");
    if (now() + intervalMs > deadline) throw new JobTimeoutError();
    await sleep(intervalMs);
  }
}

// A pending lineup job survives navigating away and back (sessionStorage).
const PENDING_KEY = "ffc_ai_lineup_job";
const PENDING_MAX_AGE_MS = 10 * 60_000;

export interface PendingJob { jobId: string; leagueId: string; teamId: string; startedAt: number }

export function savePendingJob(job: PendingJob, storage: Storage | undefined = globalThis.sessionStorage): void {
  storage?.setItem(PENDING_KEY, JSON.stringify(job));
}

export function loadPendingJob(storage: Storage | undefined = globalThis.sessionStorage, now = Date.now()): PendingJob | null {
  const raw = storage?.getItem(PENDING_KEY);
  if (!raw) return null;
  try {
    const job = JSON.parse(raw) as PendingJob;
    if (!job.jobId || now - job.startedAt > PENDING_MAX_AGE_MS) {
      storage?.removeItem(PENDING_KEY);
      return null;
    }
    return job;
  } catch {
    storage?.removeItem(PENDING_KEY);
    return null;
  }
}

export function clearPendingJob(storage: Storage | undefined = globalThis.sessionStorage): void {
  storage?.removeItem(PENDING_KEY);
}
