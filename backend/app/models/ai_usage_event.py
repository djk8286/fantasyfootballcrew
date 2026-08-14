import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, func, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class AIUsageEvent(Base):
    """One row per real LLM-spend call made under a league's AI
    Co-Commissioner surface -- digest generate, trade review analyze,
    message draft, chat post (the zero-LLM tools -- Health/Insights/
    Schedule Insights -- never write a row here, since they cost
    nothing). Pure append-only log, same shape/convention as
    ChatMessage/Notification -- exists specifically so
    ai_usage_service.check_and_record_ai_usage can count "how many
    real LLM calls has this league made in the last 24h" without
    depending on the per-IP rate limiter, which doesn't stop a
    single league's usage spread across multiple IPs."""
    __tablename__ = "ai_usage_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    league_id: Mapped[str] = mapped_column(String, ForeignKey("leagues.id"), nullable=False)
    endpoint: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        # The only access pattern this table has: "how many rows for
        # this league in the last 24h" -- same reasoning as
        # ChatMessage/Notification's own composite indexes.
        Index("ix_ai_usage_events_league_created", "league_id", "created_at"),
    )
