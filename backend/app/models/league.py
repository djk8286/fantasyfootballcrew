import uuid
import enum
from datetime import datetime
from sqlalchemy import String, Integer, Enum, Boolean, DateTime, Text, func, ForeignKey
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class LeagueType(str, enum.Enum):
    STANDARD = "standard"
    TWO_MAN = "two_man"
    CONFERENCE = "conference"


class DraftStatus(str, enum.Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class DraftType(str, enum.Enum):
    SNAKE = "snake"
    AUCTION = "auction"


class League(Base):
    __tablename__ = "leagues"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    commissioner_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    league_type: Mapped[LeagueType] = mapped_column(Enum(LeagueType), default=LeagueType.STANDARD)
    scoring_config: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)
    max_teams: Mapped[int] = mapped_column(Integer, default=12)
    draft_status: Mapped[DraftStatus] = mapped_column(Enum(DraftStatus), default=DraftStatus.NOT_STARTED)
    draft_type: Mapped[DraftType] = mapped_column(Enum(DraftType), default=DraftType.SNAKE)
    draft_order: Mapped[list | None] = mapped_column(JSON, nullable=True)
    co_commissioner_ids: Mapped[list | None] = mapped_column(JSON, nullable=True, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    commissioner = relationship("User", backref="commissioned_leagues")
    teams = relationship("Team", backref="league", lazy="selectin")
