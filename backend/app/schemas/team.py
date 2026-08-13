from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List


class TeamCreate(BaseModel):
    name: str
    league_id: str
    co_owner_id: Optional[str] = None
    avatar_url: Optional[str] = None


class TeamUpdate(BaseModel):
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    co_owner_id: Optional[str] = None
    conference: Optional[str] = None
    # Guillotine (Phase 4) -- only settable once the team is actually
    # eliminated, enforced in update_team, not here.
    last_words: Optional[str] = Field(None, max_length=280)


class TeamRead(BaseModel):
    id: str
    name: str
    owner_id: Optional[str] = None
    co_owner_id: Optional[str] = None
    league_id: str
    avatar_url: Optional[str] = None
    is_cpu: bool = False
    conference: Optional[str] = None
    roster: Optional[list] = None
    wins: int
    losses: int
    ties: int
    points_for: float
    points_against: float
    eliminated_week: Optional[int] = None
    last_words: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
