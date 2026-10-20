import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, false, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DraftAutopick(Base):
    """Per-team "Autopick" toggle for one draft (QA 2026-10-19: it used to
    be browser-tab state, so it reset to Off on every reload and only
    worked while that tab was open). Server-persisted and read by the
    draft watchdog (draft_manager.advance_draft_if_due): ON = the server
    picks for this team as soon as it's on the clock, like a CPU team.
    OFF = it waits for the pick clock, then the server autopicks anyway."""

    __tablename__ = "draft_autopick"
    __table_args__ = (UniqueConstraint("draft_id", "team_id", name="uq_draft_autopick_draft_team"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    draft_id: Mapped[str] = mapped_column(String, ForeignKey("drafts.id", ondelete="CASCADE"), nullable=False, index=True)
    team_id: Mapped[str] = mapped_column(String, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
