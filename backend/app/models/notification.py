import uuid
import enum
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, Enum, func, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class NotificationType(str, enum.Enum):
    TRADE_APPROVED = "trade_approved"
    TRADE_DENIED = "trade_denied"
    WAIVER_APPROVED = "waiver_approved"
    WAIVER_DENIED = "waiver_denied"
    MATCHUP_WON = "matchup_won"
    MATCHUP_LOST = "matchup_lost"
    MATCHUP_TIED = "matchup_tied"
    LEAGUE_INVITE_ACCEPTED = "league_invite_accepted"
    JOIN_REQUEST_RECEIVED = "join_request_received"
    JOIN_REQUEST_DECIDED = "join_request_decided"
    TEAM_ELIMINATED = "team_eliminated"
    # AI Co-Commissioner v1, Phase 2 -- Communication Helpers. A
    # commissioner-drafted-and-sent broadcast (trade deadline reminder,
    # playoff explanation, inactivity warning, general announcement),
    # delivered via notify_league_teams. Distinct from every other
    # value here, which are all system-generated from a state change.
    COMMISSIONER_MESSAGE = "commissioner_message"


class Notification(Base):
    """A minimal in-app activity feed. No email/push here -- this is
    specifically the "at least tell them inside the app" version of a
    gap where NOTHING currently tells a user their trade/waiver resolved
    or they won their matchup: Transaction.status flips and nothing
    downstream of it fires (confirmed while surveying what's missing --
    review_trade and process_waivers just commit and return; no
    caller anywhere sends anything to the affected user)."""
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    league_id: Mapped[str | None] = mapped_column(String, ForeignKey("leagues.id"), nullable=True)
    type: Mapped[NotificationType] = mapped_column(Enum(NotificationType), nullable=False)
    message: Mapped[str] = mapped_column(String, nullable=False)
    # Relative frontend path this notification should link to when clicked
    # (e.g. "/leagues/{id}/trades") -- built by the caller creating it,
    # since only the caller knows which page is relevant.
    link: Mapped[str | None] = mapped_column(String, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        # The only two access patterns this table has: "this user's
        # notifications, newest first" and "this user's unread count" --
        # both filter on user_id (and often is_read) and sort by
        # created_at, so a composite index on exactly those columns
        # covers both without a second index.
        Index("ix_notifications_user_created", "user_id", "created_at"),
    )
