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


class LeagueVisibility(str, enum.Enum):
    PRIVATE = "private"          # invite-only, not listed anywhere public
    INVITE_ONLY = "invite_only"  # listed, but joining needs an accepted invite or approved request
    OPEN = "open"                # listed, anyone can claim an open slot directly


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
    # Discovery/privacy. Defaults to OPEN deliberately -- every league
    # created before this field existed already behaves exactly like
    # "Open" today (fully public, freely claimable), so this migration
    # changes nothing for existing leagues until a commissioner
    # deliberately opts into something stricter. See list_leagues/
    # get_league in api/v1/leagues.py for how this is actually enforced.
    visibility: Mapped[LeagueVisibility] = mapped_column(Enum(LeagueVisibility), default=LeagueVisibility.OPEN, nullable=False)
    # Commissioner pause/hide for the Wanted Board specifically -- does
    # NOT remove the league from general discovery (list_leagues), only
    # from the highlighted "needs managers" section. A league stays
    # findable either way; this just stops it being pushed as "join now."
    wanted_board_hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Enhanced Conference/Rivalry (Phase 3). Pure display-layer naming --
    # NULL means "not customized", every display site falls back to
    # "Conference A"/"Conference B" (or the short "Conf A"/"Conf B" badge
    # form). Internal conference identity (Team.conference values "A"/"B")
    # is completely unaffected by these; only meaningful/rendered for
    # league_type == CONFERENCE, but harmless (never shown) if set on any
    # other league type -- same "meaningless but harmless" precedent
    # Team.conference itself already follows.
    conference_a_name: Mapped[str | None] = mapped_column(String, nullable=True)
    conference_b_name: Mapped[str | None] = mapped_column(String, nullable=True)
    # Rivalry Week: a commissioner-designated week where every team that
    # wins its normal (same-conference) matchup that week gets a flat
    # bonus, on top of any Coach win_bonus -- see
    # standings_service.DEFAULT_RIVALRY_WEEK_SETTINGS/calculate_week for
    # where this is actually consumed. Same JSON-blob-with-defaults
    # pattern as playoff_settings. Shape: {enabled, week, bonus_value}.
    # Entirely opt-in (enabled defaults False) and only meaningful for
    # CONFERENCE leagues -- calculate_week gates on league_type too, not
    # just this flag, so enabling it on a non-conference league (blocked
    # at the API layer, see update_league_rivalry_week_settings) could
    # never silently pay out even if the stored value were somehow wrong.
    rivalry_week_settings: Mapped[dict | None] = mapped_column(MutableDict.as_mutable(JSON), nullable=True, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    commissioner = relationship("User", backref="commissioned_leagues")
    teams = relationship("Team", backref="league", lazy="selectin")
