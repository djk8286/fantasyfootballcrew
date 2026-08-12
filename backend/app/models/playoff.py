import uuid
import enum
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Enum, Boolean, func, ForeignKey, UniqueConstraint
from sqlalchemy.types import JSON
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class PlayoffStatus(str, enum.Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class Playoff(Base):
    """One row per league per season. Generated automatically once the
    live NFL week passes the league's configured regular_season_weeks
    (see playoff_service.generate_bracket, called from the scheduler)."""
    __tablename__ = "playoffs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    league_id: Mapped[str] = mapped_column(String, ForeignKey("leagues.id"), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    seeding_method: Mapped[str] = mapped_column(String, nullable=False)  # "wins" | "points"
    # Only meaningful for LeagueType.CONFERENCE -- "combined" (one bracket,
    # conference just tracked for display) or "separate" (two independent
    # brackets, one per conference). None for standard/two_man leagues.
    conference_bracket_mode: Mapped[str | None] = mapped_column(String, nullable=True)
    # Snapshot of who made it and their seed at generation time -- frozen
    # once generated, not re-derived from live standings later (a playoff
    # bracket shouldn't reshuffle mid-tournament just because someone
    # recalculates a past regular-season week). Shape:
    # {"combined": [{"team_id":.., "seed":1}, ...]} or
    # {"A": [...], "B": [...]} in separate mode.
    seeds: Mapped[dict | None] = mapped_column(MutableDict.as_mutable(JSON), nullable=True)
    status: Mapped[PlayoffStatus] = mapped_column(Enum(PlayoffStatus), default=PlayoffStatus.NOT_STARTED)
    start_week: Mapped[int] = mapped_column(Integer, nullable=False)
    total_rounds: Mapped[int] = mapped_column(Integer, nullable=False)
    current_round: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("league_id", "year", name="uq_playoff_league_year"),
    )


class PlayoffMatchup(Base):
    """A single bracket game. team_a_id/team_b_id null means a bye slot
    (no real opponent -- the standard consequence of the playoff field
    not being an exact power of 2). winner_team_id is set either
    immediately (a bye auto-advances) or once the round's week is
    treated as final (see playoff_service.try_advance)."""
    __tablename__ = "playoff_matchups"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    playoff_id: Mapped[str] = mapped_column(String, ForeignKey("playoffs.id"), nullable=False)
    # "combined" | "A" | "B" -- which sub-bracket this belongs to.
    bracket: Mapped[str] = mapped_column(String, nullable=False, default="combined")
    round: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-based
    # Position of this matchup within its round, left-to-right in bracket
    # order -- consecutive pairs (0,1), (2,3), ... feed into the next
    # round's matchups in that same order, same convention real seeded
    # tournament brackets use.
    slot: Mapped[int] = mapped_column(Integer, nullable=False)
    week: Mapped[int] = mapped_column(Integer, nullable=False)
    team_a_id: Mapped[str | None] = mapped_column(String, ForeignKey("teams.id"), nullable=True)
    team_b_id: Mapped[str | None] = mapped_column(String, ForeignKey("teams.id"), nullable=True)
    is_bye: Mapped[bool] = mapped_column(Boolean, default=False)
    winner_team_id: Mapped[str | None] = mapped_column(String, ForeignKey("teams.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
