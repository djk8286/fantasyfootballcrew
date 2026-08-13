import uuid
import enum
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Text, Enum, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class InviteStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"
    # EXPIRED is deliberately NOT a value app code ever writes -- it's a
    # display-only status computed at read time by comparing expires_at
    # against now, same as PasswordResetToken's reset_password flow
    # already does. Avoids needing a background job just to flip a status
    # column on a schedule.


class LeagueInvite(Base):
    """
    A commissioner's email invite for a prospective manager to join a
    specific league. Direct architectural copy of PasswordResetToken --
    only token_hash is ever stored, never the raw token; the raw value
    only ever exists in the emailed link itself (see email_service.py).

    Acceptance is token-possession-based, not email-matching: whoever
    holds the unguessable link and is logged in becomes
    accepted_by_user_id, even if their account email differs from
    invited_email (forwarded invite, different address, etc.). This
    mirrors the password-reset token's own trust model -- the token
    itself, not who typed in what email, is the real authorization.
    """
    __tablename__ = "league_invites"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    league_id: Mapped[str] = mapped_column(String, ForeignKey("leagues.id"), nullable=False, index=True)
    invited_email: Mapped[str] = mapped_column(String, nullable=False, index=True)
    invited_by_user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    personal_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    status: Mapped[InviteStatus] = mapped_column(Enum(InviteStatus), default=InviteStatus.PENDING, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_by_user_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
