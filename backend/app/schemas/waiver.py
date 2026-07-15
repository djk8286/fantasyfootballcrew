from pydantic import BaseModel
from typing import Optional


class WaiverClaimCreate(BaseModel):
    team_id: str
    add_player_id: str
    drop_player_id: Optional[str] = None
