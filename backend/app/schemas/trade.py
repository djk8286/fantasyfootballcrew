from typing import Literal

from pydantic import BaseModel


class TradeProposalCreate(BaseModel):
    team_id: str  # proposing team
    target_team_id: str
    offered_player_ids: list[str]
    requested_player_ids: list[str]


class TradeResponse(BaseModel):
    action: Literal["accept", "decline"]
