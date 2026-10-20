import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, func, UniqueConstraint
from sqlalchemy.types import JSON
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class Lineup(Base):
    """A team's chosen starters for one specific week -- distinct from
    WeeklyScore, which only exists AFTER scoring runs and records the
    result, not the choice. A Lineup is set (or changed) by the team's
    owner ahead of that week's games; standings_service.calculate_week
    reads it to know which of the team's roster to actually score.

    No row here for a given (team, week, year) means no lineup was saved.
    calculate_week then scores a legal default lineup built from the
    league's roster slots (see services/default_lineup.py), never the
    whole roster and never zero. CPU teams get that default saved as a
    row here once the week's first game kicks off."""
    __tablename__ = "lineups"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    team_id: Mapped[str] = mapped_column(String, ForeignKey("teams.id"), nullable=False)
    week: Mapped[int] = mapped_column(Integer, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    # List of player IDs from the team's roster currently set as starters.
    # Everything else on the roster is implicitly bench. MutableList --
    # same reasoning as every other JSON list column in this codebase
    # (Team.roster, League.draft_order, ...): without it, in-place
    # .append()/.remove() is invisible to SQLAlchemy's change tracking.
    starters: Mapped[list | None] = mapped_column(MutableList.as_mutable(JSON), nullable=True, default=list)
    # [{"slot": "RB", "player_id": "..." | None}, ...] in league slot order
    # (services/lineup_slots.py). starters is kept equal to its filled
    # slots, so scoring reads one list. Null on rows saved before slots
    # existed; readers place those starters into slots on the fly.
    slots: Mapped[list | None] = mapped_column(MutableList.as_mutable(JSON), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("team_id", "week", "year", name="uq_lineup_team_week_year"),
    )
