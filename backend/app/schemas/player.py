from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List


class PlayerRead(BaseModel):
    id: str
    sleeper_id: str
    first_name: str
    last_name: str
    position: str
    team: Optional[str] = None
    bye_week: Optional[int] = None
    injury_status: Optional[str] = None
    fantasy_positions: Optional[list] = None
    age: Optional[int] = None
    avatar_url: Optional[str] = None
    headline_stats: Optional[dict] = None
    stats: Optional[dict] = None
    season_points: Optional[float] = None
    season_points_year: Optional[int] = None
    # "most important stats from the previous year" (raw sums, not scoring-
    # config-dependent) + Sleeper's synced per-game projection -- see
    # api/v1/players.py's _serialize_player / SORT_VALUES for how these
    # back the new sort_by=yards/touchdowns/projected options.
    last_season_yards: Optional[float] = None
    last_season_touchdowns: Optional[float] = None
    projected_points: Optional[float] = None

    class Config:
        from_attributes = True
