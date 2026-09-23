import uuid
from datetime import datetime
from sqlalchemy import String, Text, DateTime, func, ForeignKey
from sqlalchemy.types import JSON
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class TeamPlayerNews(Base):
    """Per-team AI news digest for that team's ACTUAL roster
    (2026-09-22) -- one row per team_id (unique), upserted on every
    regenerate, same shape as WeeklyTopPlayersSummary/WeeklyScoresRecap.
    See team_news_service.py for how content mixes real web-search
    headlines with this app's own free structured injury/team-change
    detection, and scheduler.py for the once-daily refresh cadence."""
    __tablename__ = "team_player_news"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    team_id: Mapped[str] = mapped_column(String, ForeignKey("teams.id"), unique=True, nullable=False)
    league_id: Mapped[str] = mapped_column(String, ForeignKey("leagues.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # {player_id: {"injury_status": ..., "team": ...}} as of the last
    # generation -- diffed against the CURRENT roster next time to
    # detect real changes for free, no LLM call needed for detection
    # itself. See team_news_service._detect_changes/_snapshot.
    player_snapshot: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
