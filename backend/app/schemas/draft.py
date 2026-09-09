"""Draft schemas for FantasyFootballCrew."""
from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class DraftCreate(BaseModel):
    league_id: str
    total_rounds: int = 15


class MockDraftQuickstart(BaseModel):
    """No real league needed -- auto-provisions a scratch league + CPU
    teams + a started draft, all in one call. See
    POST /drafts/mock/quickstart."""
    num_teams: int = 10
    total_rounds: int = 15
    draft_position: Optional[int] = None  # 1-indexed; None = random slot


class DraftRead(BaseModel):
    id: str
    league_id: str
    status: str
    draft_type: str
    current_round: int
    current_pick: int
    total_rounds: int
    team_order: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class DraftPickCreate(BaseModel):
    team_id: str
    player_id: str


class DraftPickRead(BaseModel):
    id: str
    league_id: str
    team_id: str
    player_id: str
    round: int
    pick_number: int
    drafted_at: datetime

    class Config:
        from_attributes = True


class DraftState(BaseModel):
    """Full state of a draft for the frontend."""
    draft: DraftRead
    picks: list[dict]  # All picks made so far
    current_team_id: Optional[str] = None
    available_players: list[dict]  # Players not yet drafted (paginated)
    is_mock: bool = False
