import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Float, Boolean, DateTime, func, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class ScoringConfig(Base):
    __tablename__ = "scoring_configs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    league_id: Mapped[str] = mapped_column(String, ForeignKey("leagues.id"), nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)  # passing, rushing, receiving, defense, kicking, bonus, custom
    stat_name: Mapped[str] = mapped_column(String, nullable=False)  # pass_yds, rush_td, rec, etc.
    points_per_unit: Mapped[float] = mapped_column(Float, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
