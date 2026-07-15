import uuid
import enum
from datetime import datetime
from sqlalchemy import String, Integer, Float, Boolean, Enum, DateTime, func, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class CoachPosition(str, enum.Enum):
    HC = "HC"
    OC = "OC"
    DC = "DC"
    STC = "STC"


class Coach(Base):
    __tablename__ = "coaches"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String, nullable=False)
    position: Mapped[CoachPosition] = mapped_column(Enum(CoachPosition), nullable=False)
    team_id: Mapped[str] = mapped_column(String, ForeignKey("teams.id"), nullable=False)
    bonus_type: Mapped[str | None] = mapped_column(String, nullable=True)  # e.g. "points_per_win", "yards_bonus"
    bonus_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
