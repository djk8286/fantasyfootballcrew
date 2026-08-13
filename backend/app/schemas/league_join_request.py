from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Literal


class JoinRequestCreate(BaseModel):
    message: Optional[str] = Field(default=None, max_length=1000)


class JoinRequestRead(BaseModel):
    id: str
    league_id: str
    requested_by_user_id: str
    requester_username: str
    message: Optional[str] = None
    status: str
    created_at: datetime
    decided_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class JoinRequestDecision(BaseModel):
    action: Literal["approve", "deny"]
