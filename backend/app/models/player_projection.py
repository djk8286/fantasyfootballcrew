import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, func, UniqueConstraint
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class PlayerProjection(Base):
    """Sleeper's projected stat line for one player in one NFL week.
    Raw stats, so each league scores them with its own scoring_config.
    A player with no row for a week has no real projection (bye, injured,
    or too deep for Sleeper to project)."""
    __tablename__ = "player_projections"
    __table_args__ = (
        UniqueConstraint("player_id", "year", "week", name="uq_player_projection_week"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    player_id: Mapped[str] = mapped_column(String, ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    week: Mapped[int] = mapped_column(Integer, nullable=False)
    stats: Mapped[dict] = mapped_column(JSON, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
