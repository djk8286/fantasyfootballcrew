import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Text, func, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class EmailSendLog(Base):
    """One row per outbound-email attempt (password reset, verification,
    league invite -- see email_service.py's _send, the single choke
    point every send function already routes through). Exists specifically
    because the 2026-09-08 incident (invite AND verification emails
    silently 403ing against Resend for weeks) was only ever visible in
    Railway logs -- nobody was going to notice a `print()` statement
    scrolling by. This is the same information, just queryable from the
    admin dashboard instead of requiring `railway logs`."""
    __tablename__ = "email_send_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    to_email: Mapped[str] = mapped_column(String, nullable=False, index=True)
    # "password_reset" | "verification" | "league_invite" -- matches
    # each public send_*_email function's purpose, not a DB enum so a
    # new email type never needs a migration to log.
    email_type: Mapped[str] = mapped_column(String, nullable=False)
    subject: Mapped[str] = mapped_column(String, nullable=False)
    # "sent" (Resend accepted it) | "failed" (Resend/network error) |
    # "stubbed" (no RESEND_API_KEY configured -- logged to stdout only,
    # the pre-2026-08 default behavior, kept as a distinct status so it
    # doesn't read as a real delivery failure).
    status: Mapped[str] = mapped_column(String, nullable=False)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        # The dashboard's two real queries: "show me recent sends" and
        # "show me recent failures" -- both order by created_at, the
        # second also filters status.
        Index("ix_email_send_logs_created", "created_at"),
        Index("ix_email_send_logs_status_created", "status", "created_at"),
    )
