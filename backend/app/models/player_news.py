import uuid
from datetime import datetime
from sqlalchemy import String, Text, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class PlayerNews(Base):
    """A real published news article tagged to one player (2026-10-18).
    Fetched from ESPN's public NFL news feed by espn_news_service.py and
    joined to players via Player.espn_id. One row per (article, player):
    an article that tags three players is stored three times so each
    player's news is a single indexed lookup. URL/headline are copied
    verbatim from the source -- nothing here is AI-written."""
    __tablename__ = "player_news"
    __table_args__ = (UniqueConstraint("source", "external_id", "player_id", name="uq_player_news_article_player"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    player_id: Mapped[str] = mapped_column(String, ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String, nullable=False)  # e.g. "ESPN"
    external_id: Mapped[str] = mapped_column(String, nullable=False)  # source's own article id
    headline: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str] = mapped_column(String, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
