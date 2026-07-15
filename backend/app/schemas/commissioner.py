from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class ScoreAdjustmentCreate(BaseModel):
    team_id: str
    week: int
    year: int
    amount: float
    reason: str


class ScoreAdjustmentRead(BaseModel):
    id: str
    league_id: str
    team_id: str
    week: int
    year: int
    amount: float
    reason: str
    created_by: str
    created_at: datetime

    class Config:
        from_attributes = True


class ScoreAdjustmentUpdate(BaseModel):
    amount: Optional[float] = None
    reason: Optional[str] = None


class TradeReview(BaseModel):
    action: str  # "approve" or "deny"


class TradeRead(BaseModel):
    id: str
    league_id: str
    team_id: str
    type: str
    status: str
    details: Optional[dict] = None
    reviewed_by: Optional[str] = None
    processed_at: datetime

    class Config:
        from_attributes = True


class DraftOrderUpdate(BaseModel):
    team_order: list[str]  # Array of team IDs in desired order
