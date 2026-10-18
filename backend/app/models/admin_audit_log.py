import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, JSON, func, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class AdminAuditLog(Base):
    """One row per admin mutation (suspend, force-logout, grant admin,
    delete user/league, ...) -- written in the SAME transaction as the
    change itself (see admin.py's _audit), so a change can't land without
    its record. Deliberately no foreign keys: the admin or the target may
    later be deleted, and the record must outlive both, so usernames/
    labels are snapshotted as plain strings at write time."""
    __tablename__ = "admin_audit_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    admin_user_id: Mapped[str] = mapped_column(String, nullable=False)
    admin_username: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    target_type: Mapped[str] = mapped_column(String, nullable=False)  # "user" | "league"
    target_id: Mapped[str] = mapped_column(String, nullable=False)
    target_label: Mapped[str | None] = mapped_column(String, nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_admin_audit_logs_created", "created_at"),
        Index("ix_admin_audit_logs_target", "target_type", "target_id"),
    )
