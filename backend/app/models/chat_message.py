import uuid
from datetime import datetime
from sqlalchemy import String, Text, DateTime, func, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class ChatMessage(Base):
    """One turn of the AI Co-Commissioner Chat (AI Co-Commissioner v1,
    deferred item 7) -- a single ongoing conversation per league, not
    multiple named threads (the simplest shape that satisfies the
    spec; nothing else in this app needs multi-conversation history).

    Both the commissioner's own messages and the AI's replies are rows
    here (role distinguishes them) so the full back-and-forth persists
    and survives a page reload -- unlike CommissionerDigest (one row
    per league/week/year, upserted), this is an append-only log with
    no unique constraint."""
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    league_id: Mapped[str] = mapped_column(String, ForeignKey("leagues.id"), nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        # The only access pattern this table has: "this league's chat
        # history, in order" -- same reasoning as Notification's own
        # composite index.
        Index("ix_chat_messages_league_created", "league_id", "created_at"),
    )
