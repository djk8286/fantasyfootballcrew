import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Float, Boolean, DateTime, Text, func, ForeignKey
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String, nullable=False)
    owner_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    co_owner_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    league_id: Mapped[str] = mapped_column(String, ForeignKey("leagues.id"), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String, nullable=True)
    is_cpu: Mapped[bool] = mapped_column(default=False)
    roster: Mapped[list | None] = mapped_column(JSON, nullable=True, default=list)  # list of player IDs
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    ties: Mapped[int] = mapped_column(Integer, default=0)
    points_for: Mapped[float] = mapped_column(Float, default=0.0)
    points_against: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
