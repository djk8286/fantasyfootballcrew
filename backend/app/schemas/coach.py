from pydantic import BaseModel
from datetime import datetime
from typing import Literal, Optional
from app.models.coach import CoachPosition

# The set of bonus_type values that actually affect scoring today -- see
# standings_service.py's _coach_bonus_sum. Deliberately a Literal here, not
# a Postgres enum on Coach.bonus_type itself: this set is expected to keep
# growing (the model's own comment already anticipated "yards_bonus"), and
# this codebase's house pattern for a small, growable string set is
# schema-layer Literal validation (see LeagueJoinRequest's
# action: Literal["approve", "deny"]), not a DB enum that needs its own
# migration every time a new value is added. CoachPosition stays a real
# Postgres enum because it's a closed, stable 4-value structural set --
# bonus_type is not that.
BonusType = Literal["flat_weekly", "win_bonus"]


class CoachCreate(BaseModel):
    name: str
    position: CoachPosition
    bonus_type: Optional[BonusType] = None
    bonus_value: Optional[float] = None


class CoachUpdate(BaseModel):
    name: Optional[str] = None
    position: Optional[CoachPosition] = None
    bonus_type: Optional[BonusType] = None
    bonus_value: Optional[float] = None
    is_active: Optional[bool] = None


class CoachRead(BaseModel):
    id: str
    name: str
    position: CoachPosition
    team_id: str
    # Stays a plain Optional[str] (not BonusType) on read -- a row written
    # before this validation existed, or by some future value, should
    # still round-trip on GET without erroring.
    bonus_type: Optional[str] = None
    bonus_value: Optional[float] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True
