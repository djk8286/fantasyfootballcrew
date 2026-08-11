import uuid
import enum
from datetime import datetime
from sqlalchemy import String, Integer, Enum, DateTime, func, ForeignKey, Index, text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class DraftRunStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class Draft(Base):
    __tablename__ = "drafts"
    __table_args__ = (
        # At most one non-completed draft per league, enforced at the DB
        # level -- not just the check-then-insert guard in
        # draft_manager.create_draft (a plain SELECT then INSERT, no
        # locking between them). Two concurrent "start draft" calls for
        # the same league could both pass that guard's "no active draft"
        # check before either committed, producing two independent Draft
        # rows whose picks then silently merge onto the same team.roster
        # (team.roster accumulates by player ID across *every* Draft row
        # for that team) -- confirmed in production: a league with 5
        # separate Draft rows for the same 14 teams, one team's roster
        # showing 27 players instead of 15. This index turns the loser of
        # that race into a clean, catchable IntegrityError instead of
        # silently-merged rosters. The enum's *name* is compared, not its
        # value ('COMPLETED' not 'completed') -- SQLAlchemy's Enum column
        # type stores the member name by default; confirmed against
        # production's actual stored values, not assumed.
        Index(
            "uq_drafts_one_active_per_league",
            "league_id",
            unique=True,
            postgresql_where=text("status != 'COMPLETED'"),
            sqlite_where=text("status != 'COMPLETED'"),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    league_id: Mapped[str] = mapped_column(String, ForeignKey("leagues.id"), nullable=False)
    status: Mapped[DraftRunStatus] = mapped_column(Enum(DraftRunStatus), default=DraftRunStatus.PENDING)
    draft_type: Mapped[str] = mapped_column(String, default="snake")  # snake or auction
    current_round: Mapped[int] = mapped_column(Integer, default=0)
    current_pick: Mapped[int] = mapped_column(Integer, default=0)
    total_rounds: Mapped[int] = mapped_column(Integer, default=15)
    team_order: Mapped[str | None] = mapped_column(String, nullable=True)  # JSON string of team IDs in draft order
    timer_seconds: Mapped[int] = mapped_column(Integer, default=60)  # Countdown timer per pick (0 = no timer)
    current_pick_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def snake_order(self, num_teams: int, team_ids: list[str]) -> list[str]:
        """Generate snake draft order list for all rounds."""
        order = []
        forward = list(team_ids)
        for rnd in range(1, self.total_rounds + 1):
            if rnd % 2 == 1:
                order.extend(forward)
            else:
                order.extend(reversed(forward))
        return order

    def current_team_id(self) -> str | None:
        """Get the team ID for the current pick."""
        if not self.team_order:
            return None
        return None


class DraftPick(Base):
    __tablename__ = "draft_picks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    draft_id: Mapped[str] = mapped_column(String, ForeignKey("drafts.id"), nullable=False)
    league_id: Mapped[str] = mapped_column(String, ForeignKey("leagues.id"), nullable=False)
    team_id: Mapped[str] = mapped_column(String, ForeignKey("teams.id"), nullable=False)
    player_id: Mapped[str] = mapped_column(String, ForeignKey("players.id"), nullable=False)
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    pick_number: Mapped[int] = mapped_column(Integer, nullable=False)
    drafted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
