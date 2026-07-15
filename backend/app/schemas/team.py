from pydantic import BaseModel
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


class TeamRead(BaseModel):
    id: str
    name: str
    owner_id: str
    co_owner_id: Optional[str] = None
    league_id: str
    avatar_url: Optional[str] = None
    is_cpu: bool = False
    roster: Optional[list] = None
    wins: int
    losses: int
    ties: int
    points_for: float
    points_against: float
    created_at: datetime

    class Config:
        from_attributes = True
