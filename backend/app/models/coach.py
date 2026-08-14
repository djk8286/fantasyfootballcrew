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
    team_id: Mapped[str] = mapped_column(String, ForeignKey("teams.id"), nullable=False, index=True)
    # "flat_weekly" | "win_bonus" are validated/scored today -- see
    # schemas/coach.py's BonusType Literal and standings_service.py's
    # _coach_bonus_sum. Plain String, not a DB enum, since this set is
    # deliberately expected to keep growing (e.g. a future "yards_bonus").
    bonus_type: Mapped[str | None] = mapped_column(String, nullable=True)
    bonus_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
