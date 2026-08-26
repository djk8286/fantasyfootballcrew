import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Boolean, func, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class NFLGame(Base):
    """A real NFL game (team vs team, real score), synced from ESPN's
    public scoreboard endpoint (nfl_schedule_service.py) -- this app's
    only source of actual NFL game-level data (Sleeper, the only other
    external source, gives per-player stat lines but never a game
    object at all). Feeds the dashboard's NFL Scores panel and its AI
    recap (WeeklyScoresRecap).

    season_type mirrors ESPN's own enum (1=preseason, 2=regular,
    3=postseason) and is stored explicitly, not inferred -- this
    project already treats preseason-vs-regular-season conflation as a
    real correctness bug (see scheduler.py's own docstring on why
    Sleeper stats syncing skips preseason entirely), so the same
    discipline applies here: a preseason Week 1 and a regular-season
    Week 1 must never collide under the same (week, year) key.

    espn_event_id is the authoritative natural key (ESPN's own game
    id) -- more robust than (week, year, home, away) against the rare
    reschedule/flex case."""
    __tablename__ = "nfl_games"
    __table_args__ = (
        UniqueConstraint("espn_event_id", name="uq_nfl_games_espn_event_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    espn_event_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    week: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    season_type: Mapped[int] = mapped_column(Integer, nullable=False)  # 1=pre, 2=regular, 3=post
    home_team: Mapped[str] = mapped_column(String, nullable=False)  # abbreviation, e.g. "KC"
    home_team_name: Mapped[str] = mapped_column(String, nullable=False)  # e.g. "Kansas City Chiefs"
    home_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_team: Mapped[str] = mapped_column(String, nullable=False)
    away_team_name: Mapped[str] = mapped_column(String, nullable=False)
    away_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # ESPN's own status.type.state: "pre" | "in" | "post"
    status_state: Mapped[str] = mapped_column(String, nullable=False)
    status_detail: Mapped[str] = mapped_column(String, nullable=False)  # e.g. "Final", "Sun 1:00 PM", "Q3 4:12"
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    kickoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
