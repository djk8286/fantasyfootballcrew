from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from app.models.coach import CoachPosition


class CoachCreate(BaseModel):
    name: str
    position: CoachPosition
    bonus_type: Optional[str] = None
    bonus_value: Optional[float] = None


class CoachUpdate(BaseModel):
    name: Optional[str] = None
    position: Optional[CoachPosition] = None
    bonus_type: Optional[str] = None
    bonus_value: Optional[float] = None
    is_active: Optional[bool] = None


class CoachRead(BaseModel):
    id: str
    name: str
    position: CoachPosition
    team_id: str
    bonus_type: Optional[str] = None
    bonus_value: Optional[float] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True
