from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List
from app.models.league import LeagueType, DraftType, DraftStatus


class ScoringConfigSchema(BaseModel):
    category: str
    stat_name: str
    points_per_unit: float
    is_active: bool = True


class LeagueCreate(BaseModel):
    name: str
    description: Optional[str] = None
    league_type: LeagueType = LeagueType.STANDARD
    scoring_config: Optional[dict] = None
    max_teams: int = 12
    draft_type: DraftType = DraftType.SNAKE
    auto_fill_cpu: bool = True


class LeagueUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    max_teams: Optional[int] = None
    draft_type: Optional[DraftType] = None
    scoring_config: Optional[dict] = None


class LeagueRead(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    commissioner_id: str
    league_type: LeagueType
    scoring_config: Optional[dict] = None
    max_teams: int
    draft_status: DraftStatus
    draft_type: DraftType
    co_commissioner_ids: Optional[list] = None
    created_at: datetime
    team_count: Optional[int] = None

    class Config:
        from_attributes = True
