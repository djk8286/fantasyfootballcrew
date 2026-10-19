"""Fantasy golf data layer (PR 1 of the plan in plans/fantasy-golf.md).

Golf data lives in its own tables -- golfers are not NFL players -- and a
golf league is an ordinary ``leagues`` row with ``sport='golf'``, reusing
teams, invites and notifications. Booleans use ``server_default=false()``
(renders 0 on SQLite, false on Postgres; never the string 'false').
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, false, func,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.core.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class GolfTournament(Base):
    __tablename__ = "golf_tournaments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    espn_event_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    tour: Mapped[str] = mapped_column(String(16), default="pga", server_default="pga", nullable=False)
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # scheduled | in_progress | final | canceled
    status: Mapped[str] = mapped_column(String(16), default="scheduled", server_default="scheduled", nullable=False)
    is_major: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    course: Mapped[str | None] = mapped_column(String, nullable=True)
    purse: Mapped[float | None] = mapped_column(Float, nullable=True)
    tiers_assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (Index("ix_golf_tournaments_season_start", "season", "start_date"),)


class Golfer(Base):
    __tablename__ = "golfers"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    espn_athlete_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    short_name: Mapped[str | None] = mapped_column(String, nullable=True)
    country: Mapped[str | None] = mapped_column(String, nullable=True)
    is_amateur: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    headshot_url: Mapped[str | None] = mapped_column(String, nullable=True)
    # Season FedEx points / earnings: the tiering signal (no paid rankings).
    season_points: Mapped[float] = mapped_column(Float, default=0, server_default="0", nullable=False)
    season_earnings: Mapped[float] = mapped_column(Float, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class GolfFieldEntry(Base):
    __tablename__ = "golf_field_entries"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tournament_id: Mapped[str] = mapped_column(String, ForeignKey("golf_tournaments.id", ondelete="CASCADE"), nullable=False)
    golfer_id: Mapped[str] = mapped_column(String, ForeignKey("golfers.id", ondelete="CASCADE"), nullable=False)
    tier: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1..6, set at tier assignment
    tee_time_r1: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # active | cut | wd | dq | finished
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active", nullable=False)
    position: Mapped[str | None] = mapped_column(String(8), nullable=True)  # e.g. "T9"
    to_par: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_strokes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thru: Mapped[int | None] = mapped_column(Integer, nullable=True)
    earnings: Mapped[float | None] = mapped_column(Float, nullable=True)
    cup_points: Mapped[float | None] = mapped_column(Float, nullable=True)
    rounds: Mapped[list | None] = mapped_column(JSON, nullable=True)  # per-round strokes/to-par + holes
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("tournament_id", "golfer_id", name="uq_golf_field_entry"),
        Index("ix_golf_field_entries_tournament_tier", "tournament_id", "tier"),
    )


class GolfPick(Base):
    __tablename__ = "golf_picks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    league_id: Mapped[str] = mapped_column(String, ForeignKey("leagues.id", ondelete="CASCADE"), nullable=False)
    team_id: Mapped[str] = mapped_column(String, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    tournament_id: Mapped[str] = mapped_column(String, ForeignKey("golf_tournaments.id", ondelete="CASCADE"), nullable=False)
    tier: Mapped[int] = mapped_column(Integer, nullable=False)
    golfer_id: Mapped[str] = mapped_column(String, ForeignKey("golfers.id"), nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("team_id", "tournament_id", "tier", name="uq_golf_pick_team_event_tier"),
        Index("ix_golf_picks_league_tournament", "league_id", "tournament_id"),
    )


class GolfTeamEventResult(Base):
    __tablename__ = "golf_team_event_results"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    league_id: Mapped[str] = mapped_column(String, ForeignKey("leagues.id", ondelete="CASCADE"), nullable=False)
    team_id: Mapped[str] = mapped_column(String, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    tournament_id: Mapped[str] = mapped_column(String, ForeignKey("golf_tournaments.id", ondelete="CASCADE"), nullable=False)
    counted_to_par: Mapped[int | None] = mapped_column(Integer, nullable=True)  # best 4 of 6
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    season_points: Mapped[float] = mapped_column(Float, default=0, server_default="0", nullable=False)
    is_final: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("team_id", "tournament_id", name="uq_golf_result_team_event"),
        Index("ix_golf_results_league_tournament", "league_id", "tournament_id"),
    )
