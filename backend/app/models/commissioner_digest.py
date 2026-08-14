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
    # Nullable: an account can be hard-deleted (self-service account
    # deletion) after generating digests other people still rely on --
    # the digest content survives, only the attribution is cleared.
    generated_by: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    # AI Co-Commissioner v1: the tone/length actually used to generate
    # this digest -- per-generation params, not a persisted league
    # default (see ai_service.py's TONE_INSTRUCTIONS/LENGTH_INSTRUCTIONS).
    # Stored here purely so a cached/re-viewed digest shows what was
    # actually used, not as a reusable "default" anywhere.
    tone: Mapped[str] = mapped_column(String, nullable=False, default="professional")
    length: Mapped[str] = mapped_column(String, nullable=False, default="full")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
