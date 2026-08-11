import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class PasswordResetToken(Base):
    """
    A single-use, time-limited token for the forgot-password flow.

    Only token_hash is stored -- never the raw token -- same reasoning as
    never storing a plaintext password: if this table leaked, the tokens in
    it shouldn't be directly usable. The raw token only ever exists in the
    link sent to (or, until an email provider is configured, logged for)
    the user; see app/services/email_service.py.
    """
    __tablename__ = "password_reset_tokens"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
