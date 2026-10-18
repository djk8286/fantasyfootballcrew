import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Text, Integer, Boolean, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class JobRun(Base):
    """One row per background-job execution (see job_run_service.run_job,
    the wrapper every scheduler.py job call goes through). Exists for the
    same reason EmailSendLog does: scheduler failures used to be a
    `print()` in Railway logs that nobody saw. This makes "did the stats
    sync actually run, and when did it last succeed" answerable from the
    admin dashboard. Pruned to JOB_RUN_RETENTION_DAYS by the scheduler
    itself."""
    __tablename__ = "job_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_name: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_job_runs_job_started", "job_name", "started_at"),
        Index("ix_job_runs_started", "started_at"),
    )
