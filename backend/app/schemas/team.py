from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime
from typing import Optional, List


class TeamCreate(BaseModel):
    # Unknown fields (including co_owner_id) are rejected with a 422 rather
    # than silently ignored. Co-owners are added after creation through
    # claim-co-owner or the commissioner's assign-co-owner.
    model_config = ConfigDict(extra="forbid")

    name: str
    league_id: str
    avatar_url: Optional[str] = None


class TeamUpdate(BaseModel):
    # No co_owner_id: co-owners change only through claim-co-owner and the
    # commissioner's assign-co-owner / remove-co-owner, which apply the
    # league's 2-Man and join rules. Unknown fields get a 422.
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    avatar_url: Optional[str] = None
    conference: Optional[str] = None
    # Guillotine (Phase 4) -- only settable once the team is actually
    # eliminated, enforced in update_team, not here.
    last_words: Optional[str] = Field(None, max_length=280)


class TeamRead(BaseModel):
    id: str
    name: str
    owner_id: Optional[str] = None
    co_owner_id: Optional[str] = None
    partner_team_id: Optional[str] = None
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
