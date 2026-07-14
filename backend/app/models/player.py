import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, func, ForeignKey
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class Player(Base):
    __tablename__ = "players"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    sleeper_id: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    first_name: Mapped[str] = mapped_column(String, nullable=False)
    last_name: Mapped[str] = mapped_column(String, nullable=False)
    position: Mapped[str] = mapped_column(String, nullable=False)  # QB, RB, WR, TE, K, DEF
    team: Mapped[str | None] = mapped_column(String, nullable=True)  # NFL team abbreviation
    bye_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    injury_status: Mapped[str | None] = mapped_column(String, nullable=True)
    fantasy_positions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    stats: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)  # career/non-weekly stats
    week_stats: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)  # {week_number: {stat_key: value}}
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
