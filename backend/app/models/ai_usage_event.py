import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, func, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class AIUsageEvent(Base):
    """One row per real LLM-spend call anywhere in the app -- originally
    just the AI Co-Commissioner surface (digest generate, trade review
    analyze, message draft, chat post), now ALSO the personal-tools
    surface (lineup analysis, trade analysis, bet analysis -- see
    ai_usage_service.record_ai_usage) that used to make real LLM calls
    with no usage record at all, which is why the admin AI-usage
    dashboard undercounted real spend. Pure append-only log, same shape/
    convention as ChatMessage/Notification.

    league_id is nullable (2026-09-09) -- bet analysis (POST /ai/bet)
    isn't scoped to any league at all (freeform personal betting
    questions), so it has nothing to attach here; every other endpoint
    still populates it. user_id is new too, letting the admin dashboard
    show per-user usage (not just per-league) the way David asked about.
    Neither nullable field changes check_and_record_ai_usage's existing
    per-league daily-cap behavior -- that still only ever counts/caps
    rows that DO have a league_id."""
    __tablename__ = "ai_usage_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    league_id: Mapped[str | None] = mapped_column(String, ForeignKey("leagues.id"), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    endpoint: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        # The only access patterns this table has: "how many rows for
        # this league in the last 24h" (check_and_record_ai_usage) and
        # "how many rows for this user" (admin dashboard) -- same
        # reasoning as ChatMessage/Notification's own composite indexes.
        Index("ix_ai_usage_events_league_created", "league_id", "created_at"),
        Index("ix_ai_usage_events_user_created", "user_id", "created_at"),
    )
