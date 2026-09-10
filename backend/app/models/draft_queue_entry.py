import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, func, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class DraftQueueEntry(Base):
    """A team's pick queue for one draft -- persisted server-side (2026-09-09)
    so it survives a page refresh, unlike the old purely-in-browser-state
    version. One row per queued player; `position` is that player's order
    within the team's own queue (0 = next up). Deleted individually when a
    player is drafted (by anyone, on any team -- see draft_manager.make_pick)
    so a queue never accumulates dead entries for players no longer
    available to pick.

    Server-authoritative auto-pick (draft_manager.get_next_pick_for_team,
    used by both the manual /auto-pick endpoint and the timer-expiry
    watchdog in scheduler.py) reads this table FIRST, in `position` order,
    before falling back to the AI ranking -- so "auto-pick takes from the
    queue" is true regardless of whether any browser is even open, not
    just when the owning client's own tab happens to be watching."""
    __tablename__ = "draft_queue_entries"
    __table_args__ = (
        # A player can only be queued once per team (toggling it back on
        # after removing it just re-adds at the end, not exactly restores
        # its old spot -- same simple behavior the old client-only queue
        # already had).
        UniqueConstraint("draft_id", "team_id", "player_id", name="uq_draft_queue_team_player"),
        Index("ix_draft_queue_draft_team_position", "draft_id", "team_id", "position"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    draft_id: Mapped[str] = mapped_column(String, ForeignKey("drafts.id"), nullable=False, index=True)
    team_id: Mapped[str] = mapped_column(String, ForeignKey("teams.id"), nullable=False, index=True)
    player_id: Mapped[str] = mapped_column(String, ForeignKey("players.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
