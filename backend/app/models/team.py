import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Float, Boolean, DateTime, Text, func, ForeignKey
from sqlalchemy.types import JSON
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String, nullable=False)
    owner_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    co_owner_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    # Dual-Squad/Mirror (Phase 7). Self-referential, symmetric -- if
    # A.partner_team_id == B.id then B.partner_team_id == A.id is also
    # set, in the same transaction (see teams.bulk_add_cpu_teams/
    # claim_team). Only meaningful for League.league_type == "dual_squad"
    # (None everywhere else), same "meaningless but harmless" precedent
    # Team.conference already follows for non-CONFERENCE leagues. See
    # standings_service._effective_matchups for how this keeps a
    # manager's own two teams from ever being scheduled against each
    # other, and get_combined_standings for the paired standings view.
    partner_team_id: Mapped[str | None] = mapped_column(String, ForeignKey("teams.id"), nullable=True, index=True)
    league_id: Mapped[str] = mapped_column(String, ForeignKey("leagues.id"), nullable=False, index=True)
    avatar_url: Mapped[str | None] = mapped_column(String, nullable=True)
    is_cpu: Mapped[bool] = mapped_column(default=False)
    # Only meaningful for League.league_type == "conference" -- which of the
    # two conferences ("A"/"B") this team belongs to. Null for standard/
    # two_man leagues.
    conference: Mapped[str | None] = mapped_column(String, nullable=True)
    # MutableList wrapper: without it, in-place .append()/.remove() on this
    # column is invisible to SQLAlchemy's change tracking (only whole-attribute
    # reassignment is), so mutations silently fail to persist. See draft_manager
    # .make_pick, which used to lose every pick after a team's first.
    roster: Mapped[list | None] = mapped_column(MutableList.as_mutable(JSON), nullable=True, default=list)  # list of player IDs
    # Bumped on every roster write made through a compare-and-swap (currently
    # just trade approval). Lets a writer detect "this roster changed under
    # me since I read it" with a plain integer WHERE-clause instead of
    # comparing the whole JSON blob (which Postgres's plain `json` column
    # type can't even do -- there's no `=` operator for it, only `jsonb`).
    # See commissioner.review_trade.
    roster_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Guillotine (Phase 4, "Guillotine + Custom Twist"). None = alive. A
    # non-None value is BOTH the elimination flag and the week it
    # happened -- no separate boolean, since one would just be a
    # driftable duplicate of "eliminated_week is not None". See
    # standings_service._effective_matchups for how this affects
    # scoring/standings, and guillotine_service.py for how it gets set.
    eliminated_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Optional flavor text an eliminated manager can submit once their
    # team is out -- set via the existing generic update_team PATCH,
    # gated there to only be settable post-elimination.
    last_words: Mapped[str | None] = mapped_column(Text, nullable=True)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    ties: Mapped[int] = mapped_column(Integer, default=0)
    points_for: Mapped[float] = mapped_column(Float, default=0.0)
    points_against: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
