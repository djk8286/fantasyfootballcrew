import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class RefreshToken(Base):
    """One rotating refresh token (cookie-auth sessions).

    Only the SHA-256 hash of the raw token is stored. Every refresh
    revokes the presented row and issues a new one in the same
    ``family_id``; presenting an already-rotated token (outside a short
    multi-tab grace window) is treated as theft and revokes the whole
    family. ``token_version`` snapshots User.token_version at issue time,
    so password change / admin force-logout / suspend (which bump it)
    kill every outstanding refresh token too.
    """
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    family_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
