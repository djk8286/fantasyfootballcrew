from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List


class PlayerRead(BaseModel):
    id: str
    sleeper_id: str
    first_name: str
    last_name: str
    position: str
    team: Optional[str] = None
    bye_week: Optional[int] = None
    injury_status: Optional[str] = None
    fantasy_positions: Optional[list] = None
    age: Optional[int] = None

    class Config:
        from_attributes = True
