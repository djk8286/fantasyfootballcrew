import uuid
from datetime import datetime
from sqlalchemy import String, Text, DateTime, func, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class AIAnalysisHistory(Base):
    """Persisted history for the personal AI Analysis tools (POST
    /ai/lineup, /ai/trade, /ai/bet) -- these were pure one-shot
    request/response calls with nothing saved anywhere (AIUsageEvent
    logs that a call happened, for spend metering, but never the actual
    question/answer), so a result vanished the moment you left the page
    or refreshed. Scoped to the calling user (user_id, not nullable) --
    unlike ChatMessage's one-shared-thread-per-league shape, each of
    these tools is a personal "ask the AI about my team/trade/bet", not
    a conversation the whole league sees or contributes to.

    league_id is nullable for the same reason AIUsageEvent.league_id is
    -- bet analysis (POST /ai/bet) is a freeform personal question, not
    scoped to any league. summary is a short, pre-rendered label (team
    name, trade description, or a truncated bet prompt) so the history
    list can render without re-joining out to Team/Transaction/League
    for rows whose underlying team/trade may since have been deleted.

    Deliberately NOT threaded back into a new LLM call the way
    ChatMessage's history is (see chat_service.py) -- these tools stay
    one-shot Q&A with no conversational memory; this only makes past
    answers retrievable, an append-only log like ChatMessage/
    AIUsageEvent, no unique constraint."""
    __tablename__ = "ai_analysis_history"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    league_id: Mapped[str | None] = mapped_column(String, ForeignKey("leagues.id"), nullable=True)
    analysis_type: Mapped[str] = mapped_column(String, nullable=False)  # "lineup" | "trade" | "bet"
    summary: Mapped[str] = mapped_column(String, nullable=False)
    result: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        # The only access pattern this table has: "this user's history
        # for this tool, most recent first" -- same reasoning as
        # ChatMessage/AIUsageEvent's own composite indexes.
        Index("ix_ai_analysis_history_user_type_created", "user_id", "analysis_type", "created_at"),
    )
