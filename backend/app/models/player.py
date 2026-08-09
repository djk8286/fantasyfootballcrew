import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, func, ForeignKey
from sqlalchemy.types import JSON
from sqlalchemy.ext.mutable import MutableList, MutableDict
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class Player(Base):
    __tablename__ = "players"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    sleeper_id: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    first_name: Mapped[str] = mapped_column(String, nullable=False)
    last_name: Mapped[str] = mapped_column(String, nullable=False)
    position: Mapped[str] = mapped_column(String, nullable=False)  # QB, RB, WR, TE, K, DEF
    team: Mapped[str | None] = mapped_column(String, nullable=True)  # NFL team abbreviation
    bye_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    injury_status: Mapped[str | None] = mapped_column(String, nullable=True)
    fantasy_positions: Mapped[list | None] = mapped_column(MutableList.as_mutable(JSON), nullable=True)
    # MutableDict wrapper: without it, item assignment (player.stats[k] = v)
    # is invisible to SQLAlchemy's change tracking -- only whole-attribute
    # reassignment is. That silently dropped every week's stats after the
    # first sync for a given player before this fix (see sleeper_sync).
    stats: Mapped[dict | None] = mapped_column(MutableDict.as_mutable(JSON), nullable=True, default=dict)  # current-season aggregate stats
    stats_year: Mapped[int | None] = mapped_column(Integer, nullable=True)  # which season `stats` actually represents
    week_stats: Mapped[dict | None] = mapped_column(MutableDict.as_mutable(JSON), nullable=True, default=dict)  # {week_number: {stat_key: value}}
    # Static reference snapshot of the last fully-completed season, used as
    # a season_points fallback before the new season has any real synced
    # data -- see sleeper_sync.effective_season_stats for how the two are
    # chosen between.
    last_season_stats: Mapped[dict | None] = mapped_column(MutableDict.as_mutable(JSON), nullable=True)
    last_season_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
