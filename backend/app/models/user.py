import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Integer, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String, nullable=True)
    provider: Mapped[str] = mapped_column(String, default="email")  # "email" or "google"
    hashed_password: Mapped[str | None] = mapped_column(String, nullable=True)
    # Bumped on password change/reset -- embedded in every JWT at issuance
    # (see auth_service.create_access_token's caller in auth.py's login())
    # and checked in api/deps.py's get_current_user. A mismatch means this
    # token was issued before the account's last password change, so it's
    # rejected -- closes the "a stolen token survives a password change"
    # gap without needing a dedicated logout-everywhere/session-list UI.
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
