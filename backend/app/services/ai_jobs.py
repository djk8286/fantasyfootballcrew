"""In-process background jobs for slow AI analyses.

Single-instance deploy (one uvicorn process), so an in-memory registry is
enough; a restart drops in-flight jobs, which the client surfaces as
"expired, try again" (the result, if it finished, is still in history).
Jobs are owner-scoped and pruned after JOB_TTL_S.
"""
import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable

JOB_TTL_S = 30 * 60
# Hard ceiling on one generation so a hung provider call can't leave a job
# "pending" forever (the client also gives up on its own after ~2 min).
JOB_TIMEOUT_S = 150


@dataclass
class AnalysisJob:
    id: str
    user_id: str
    kind: str
    status: str = "pending"  # pending | done | error
    analysis: str | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    task: asyncio.Task | None = None

    def public(self) -> dict:
        return {"job_id": self.id, "kind": self.kind, "status": self.status,
                "analysis": self.analysis, "error": self.error}


_jobs: dict[str, AnalysisJob] = {}


def _prune() -> None:
    cutoff = time.time() - JOB_TTL_S
    for jid in [j for j, job in _jobs.items() if job.created_at < cutoff and job.status != "pending"]:
        _jobs.pop(jid, None)


def start(user_id: str, kind: str, runner: Callable[[], Awaitable[str]]) -> AnalysisJob:
    _prune()
    job = AnalysisJob(id=str(uuid.uuid4()), user_id=user_id, kind=kind)

    async def _wrapped():
        try:
            job.analysis = await asyncio.wait_for(runner(), timeout=JOB_TIMEOUT_S)
            job.status = "done"
        except asyncio.TimeoutError:
            job.status, job.error = "error", "The analysis took too long. Please try again."
        except Exception as e:  # surfaced to the owner only, generic text
            print(f"[ai_jobs] {kind} job {job.id} failed: {e!r}", flush=True)
            job.status, job.error = "error", "The analysis failed. Please try again."

    job.task = asyncio.create_task(_wrapped())
    _jobs[job.id] = job
    return job


def get(job_id: str, user_id: str) -> AnalysisJob | None:
    job = _jobs.get(job_id)
    if job is None or job.user_id != user_id:
        return None
    return job
