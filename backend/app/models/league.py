import uuid
import enum
from datetime import datetime
from sqlalchemy import String, Integer, Enum, Boolean, DateTime, Text, func, ForeignKey
from sqlalchemy.types import JSON
from sqlalchemy.ext.mutable import MutableList, MutableDict
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
    # MutableList/MutableDict wrappers: without them, in-place mutation
    # (.append(), .remove(), item assignment) on these columns is invisible
    # to SQLAlchemy's change tracking -- only whole-attribute reassignment
    # is. That silently dropped co-commissioner adds/removes before this fix.
    scoring_config: Mapped[dict | None] = mapped_column(MutableDict.as_mutable(JSON), nullable=True, default=dict)
    # How many starters at each position -- drives both the lineup-setting
    # UI (app/api/v1/lineups.py) and which of a team's roster actually
    # counts toward their weekly score (standings_service.calculate_week).
    # DL/LB/DB/IDP_FLEX default to 0 so no existing league is affected
    # until a commissioner deliberately turns IDP roster slots on -- see
    # DEFAULT_ROSTER_SLOTS.
    roster_slots: Mapped[dict | None] = mapped_column(MutableDict.as_mutable(JSON), nullable=True, default=dict)
    # Playoff configuration -- entirely opt-in (enabled defaults False, see
    # DEFAULT_PLAYOFF_SETTINGS in playoff_service.py), so no existing
    # league gets a bracket generated under it without a commissioner
    # deliberately turning this on. Shape: {enabled, regular_season_weeks,
    # num_teams, seeding_method: "wins"|"points",
    # conference_bracket_mode: "combined"|"separate"|None}.
    playoff_settings: Mapped[dict | None] = mapped_column(MutableDict.as_mutable(JSON), nullable=True, default=dict)
    max_teams: Mapped[int] = mapped_column(Integer, default=12)
    draft_status: Mapped[DraftStatus] = mapped_column(Enum(DraftStatus), default=DraftStatus.NOT_STARTED)
    draft_type: Mapped[DraftType] = mapped_column(Enum(DraftType), default=DraftType.SNAKE)
    draft_order: Mapped[list | None] = mapped_column(MutableList.as_mutable(JSON), nullable=True)
    waiver_priority: Mapped[list | None] = mapped_column(MutableList.as_mutable(JSON), nullable=True)
    co_commissioner_ids: Mapped[list | None] = mapped_column(MutableList.as_mutable(JSON), nullable=True, default=list)
    # Practice drafts (POST /drafts/mock/quickstart) auto-provision a real
    # League + Teams behind the scenes so they can reuse the entire
    # already-tested draft room/engine instead of a second implementation.
    # This keeps those scratch leagues out of "my leagues" and public
    # discovery -- see the is_mock filter in list_leagues.
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    commissioner = relationship("User", backref="commissioned_leagues")
    teams = relationship("Team", backref="league", lazy="selectin")
