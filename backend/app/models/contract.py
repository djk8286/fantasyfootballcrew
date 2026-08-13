import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Float, Boolean, DateTime, ForeignKey, Index, func, text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class Contract(Base):
    """A player's salary/contract terms on a specific team, for
    Salary-Cap + Contract Leagues (Phase 5). Single-season enforcement
    only -- contract_years/signed_year are stored for a hypothetical
    future keeper/dynasty phase, but nothing in this app rolls a
    contract forward between fantasy seasons today (see
    salary_cap_service.py's module docstring). A row's salary/
    contract_years/signed_year are never mutated after creation --
    only is_active flips to False on release/drop/elimination, giving a
    real audit trail (mirrors Team.eliminated_week's "never rewritten,
    only ever set once" precedent from Phase 4)."""
    __tablename__ = "contracts"
    __table_args__ = (
        # One ACTIVE contract per player per league at a time -- mirrors
        # Draft's own uq_drafts_one_active_per_league partial-unique-index
        # precedent (backend/app/models/draft.py). A player can accumulate
        # multiple historical (is_active=False) Contract rows over a
        # season (drafted, dropped, re-signed elsewhere), but never two
        # simultaneously-active ones.
        Index(
            "uq_contracts_one_active_per_league_player",
            "league_id", "player_id",
            unique=True,
            postgresql_where=text("is_active = true"),
            sqlite_where=text("is_active = 1"),
        ),
        Index("ix_contracts_league_team_active", "league_id", "team_id", "is_active"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    league_id: Mapped[str] = mapped_column(String, ForeignKey("leagues.id"), nullable=False)
    team_id: Mapped[str] = mapped_column(String, ForeignKey("teams.id"), nullable=False)
    player_id: Mapped[str] = mapped_column(String, ForeignKey("players.id"), nullable=False)
    salary: Mapped[float] = mapped_column(Float, nullable=False)
    contract_years: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-4
    signed_year: Mapped[int] = mapped_column(Integer, nullable=False)
    # "draft" | "waiver" -- plain String, not a Postgres enum, mirroring
    # Draft.draft_type's own plain-String precedent specifically to avoid
    # the enum-creation migration gotcha for a field with only 2 values.
    source: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DeadMoney(Base):
    """An append-only ledger of cap penalties charged for releasing a
    multi-year-contract player early (Contract.contract_years > 1 at
    signing) -- see salary_cap_service.release_player. A dedicated table
    rather than a running total column on Team, matching the same
    reasoning that already justifies ScoreAdjustment being its own table
    instead of a Team running total: a real per-release audit trail, and
    one less mutable column on the already-heavily-mutated Team model."""
    __tablename__ = "dead_money_entries"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    league_id: Mapped[str] = mapped_column(String, ForeignKey("leagues.id"), nullable=False)
    team_id: Mapped[str] = mapped_column(String, ForeignKey("teams.id"), nullable=False)
    player_id: Mapped[str] = mapped_column(String, ForeignKey("players.id"), nullable=False)
    contract_id: Mapped[str | None] = mapped_column(String, ForeignKey("contracts.id"), nullable=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False, default="early release")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
