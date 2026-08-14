import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Text, DateTime, func, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class CommissionerDigest(Base):
    """A commissioner-triggered, AI-generated weekly digest (power
    rankings, storylines, transaction recap) for one league/week (Phase
    8, "AI-Assisted Commissioner Tools"). One row per (league_id, week,
    year) -- regenerating upserts in place, mirroring WeeklyScore's own
    upsert-on-recalculate behavior, so a commissioner re-clicking
    "Generate" doesn't accumulate duplicate rows."""
    __tablename__ = "commissioner_digests"
    __table_args__ = (
        UniqueConstraint("league_id", "week", "year", name="uq_commissioner_digest_league_week_year"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    league_id: Mapped[str] = mapped_column(String, ForeignKey("leagues.id"), nullable=False)
    week: Mapped[int] = mapped_column(Integer, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    generated_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
