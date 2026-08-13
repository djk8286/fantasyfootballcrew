import uuid
import enum
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Text, Enum, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class JoinRequestStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class LeagueJoinRequest(Base):
    """
    A user asking a commissioner for access to an Invite-only league they
    found through discovery (as opposed to LeagueInvite, which is the
    commissioner reaching out first). Only meaningful for
    LeagueVisibility.INVITE_ONLY -- OPEN leagues are joined directly via
    claim_team, PRIVATE leagues aren't discoverable enough to request
    against in the first place. See invites.py's create_join_request.

    No DB uniqueness constraint on (league_id, requested_by_user_id) --
    deliberately enforced in application code instead (query-then-insert)
    so a DENIED request can be resubmitted later, but not spammed while
    one is still PENDING. See invites.py.
    """
    __tablename__ = "league_join_requests"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    league_id: Mapped[str] = mapped_column(String, ForeignKey("leagues.id"), nullable=False, index=True)
    requested_by_user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[JoinRequestStatus] = mapped_column(Enum(JoinRequestStatus), default=JoinRequestStatus.PENDING, nullable=False)
    decided_by_user_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
