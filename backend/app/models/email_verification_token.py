import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class EmailVerificationToken(Base):
    """
    A single-use, time-limited token for the (track-only, not enforced
    -- see auth.py's register()/verify-email) email verification flow.
    Exact shape of PasswordResetToken -- only token_hash is stored,
    never the raw token, same reasoning: if this table leaked, the
    tokens in it shouldn't be directly usable.
    """
    __tablename__ = "email_verification_tokens"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
