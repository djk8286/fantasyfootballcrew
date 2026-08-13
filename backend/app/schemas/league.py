from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List
from app.models.league import LeagueType, DraftType, DraftStatus, LeagueVisibility


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
    visibility: LeagueVisibility = LeagueVisibility.OPEN


class LeagueUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    max_teams: Optional[int] = None
    draft_type: Optional[DraftType] = None
    scoring_config: Optional[dict] = None
    visibility: Optional[LeagueVisibility] = None
    wanted_board_hidden: Optional[bool] = None
    # Display-only conference naming (Phase 3) -- harmless if set on a
    # non-conference league, just never rendered anywhere.
    conference_a_name: Optional[str] = Field(default=None, max_length=40)
    conference_b_name: Optional[str] = Field(default=None, max_length=40)


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
    visibility: LeagueVisibility = LeagueVisibility.OPEN
    wanted_board_hidden: bool = False
    conference_a_name: Optional[str] = None
    conference_b_name: Optional[str] = None
    # Only populated when the caller passes a current_user (see get_league/
    # list_leagues) -- "member"|"commissioner"|"invited"|"requested"|
    # "eligible"|"blocked". None for anonymous/unauthenticated reads.
    viewer_join_status: Optional[str] = None

    class Config:
        from_attributes = True
