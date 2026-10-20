import { describe, expect, it } from "vitest";
import { pollJob, pollJobShared, JobTimeoutError, savePendingJob, loadPendingJob, clearPendingJob, type JobStatus } from "./ai-jobs";

function fakeClock() {
  let t = 0;
  return { now: () => t, sleep: async (ms: number) => { t += ms; } };
}

class MemStorage {
  m = new Map<string, string>();
  getItem(k: string) { return this.m.get(k) ?? null; }
  setItem(k: string, v: string) { this.m.set(k, v); }
  removeItem(k: string) { this.m.delete(k); }
}

describe("pollJob", () => {
  it("resolves with the analysis once the job is done", async () => {
    const seq: JobStatus[] = [
      { job_id: "j", status: "pending" },
      { job_id: "j", status: "pending" },
      { job_id: "j", status: "done", analysis: "Start Bijan." },
    ];
    const c = fakeClock();
    await expect(pollJob(async () => seq.shift()!, { ...c })).resolves.toBe("Start Bijan.");
  });

  it("rejects with the job's error", async () => {
    const c = fakeClock();
    await expect(pollJob(async () => ({ job_id: "j", status: "error", error: "boom" }), c)).rejects.toThrow("boom");
  });

  it("gives up after the client timeout instead of spinning forever", async () => {
    const c = fakeClock();
    let calls = 0;
    await expect(
      pollJob(async () => { calls++; return { job_id: "j", status: "pending" }; }, { ...c, intervalMs: 2000, timeoutMs: 10_000 })
    ).rejects.toBeInstanceOf(JobTimeoutError);
    expect(calls).toBeLessThanOrEqual(6);
  });

  it("stops quietly when cancelled (component unmounted)", async () => {
    const c = fakeClock();
    let cancelled = false;
    const p = pollJob(async () => { cancelled = true; return { job_id: "j", status: "pending" }; }, { ...c, isCancelled: () => cancelled });
    await expect(p).resolves.toBeNull();
  });
});

describe("pending job persistence", () => {
  it("round-trips and expires stale entries", () => {
    const s = new MemStorage() as unknown as Storage;
    savePendingJob({ jobId: "j1", leagueId: "l", teamId: "t", startedAt: 1000 }, s);
    expect(loadPendingJob(s, 2000)?.jobId).toBe("j1");
    expect(loadPendingJob(s, 1000 + 11 * 60_000)).toBeNull();
    savePendingJob({ jobId: "j2", leagueId: "l", teamId: "t", startedAt: 0 }, s);
    clearPendingJob(s);
    expect(loadPendingJob(s, 1)).toBeNull();
  });
});

describe("pollJob transient failures", () => {
  const err = (status: number) => Object.assign(new Error(`HTTP ${status}`), { status });

  it("keeps polling through 5xx/429/network errors and still returns the result", async () => {
    const seq: (JobStatus | Error)[] = [
      { job_id: "j", status: "pending" }, err(502), new TypeError("Failed to fetch"), err(429),
      { job_id: "j", status: "done", analysis: "Start Bijan." },
    ];
    const c = fakeClock();
    const fetch = async () => { const x = seq.shift()!; if (x instanceof Error) throw x; return x; };
    await expect(pollJob(fetch, c)).resolves.toBe("Start Bijan.");
  });

  it("does not retry a 404 (expired) or 403", async () => {
    for (const status of [404, 403]) {
      let calls = 0;
      const c = fakeClock();
      await expect(pollJob(async () => { calls++; throw err(status); }, c)).rejects.toMatchObject({ status });
      expect(calls).toBe(1);
    }
  });

  it("gives up after too many consecutive transient failures", async () => {
    let calls = 0;
    const c = fakeClock();
    await expect(pollJob(async () => { calls++; throw err(503); }, { ...c, maxTransientFailures: 3 })).rejects.toMatchObject({ status: 503 });
    expect(calls).toBe(4);
  });
});

describe("pollJobShared", () => {
  it("runs one poller per job id for concurrent callers", async () => {
    let calls = 0;
    let release!: () => void;
    const gate = new Promise<void>((r) => { release = r; });
    const fetch = async (): Promise<JobStatus> => { calls++; await gate; return { job_id: "s", status: "done", analysis: "ok" }; };
    const a = pollJobShared("s", fetch);
    const b = pollJobShared("s", fetch);
    expect(b).toBe(a);
    release();
    await expect(Promise.all([a, b])).resolves.toEqual(["ok", "ok"]);
    expect(calls).toBe(1);
    // Settled jobs are forgotten, so a new run with a new id polls again.
    await expect(pollJobShared("s", fetch)).resolves.toBe("ok");
    expect(calls).toBe(2);
  });
});
