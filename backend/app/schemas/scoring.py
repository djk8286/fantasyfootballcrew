from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Dict, Any, List


class ScoringCalculatorInput(BaseModel):
    """Input for the scoring calculator endpoint."""
    stats: Dict[str, Any]
    scoring_config: Dict[str, Any]
    position: Optional[str] = None


class ScoringCalculatorResult(BaseModel):
    """Single player scoring calculation result."""
    total_score: float
    breakdown: Dict[str, float]
    bonuses: Dict[str, float]
    custom_points: float


class LineupSlotInput(BaseModel):
    """A single player in a lineup for weekly scoring."""
    player_id: str
    stats: Dict[str, Any]
    position: str
    name: Optional[str] = None


class WeeklyScoringInput(BaseModel):
    """Input for weekly lineup scoring."""
    lineup: List[LineupSlotInput]
    scoring_config: Dict[str, Any]


class PlayerBreakdown(BaseModel):
    """Per-player scoring breakdown."""
    player_id: str
    name: Optional[str] = None
    score: float
    stats: Dict[str, Any]
    position: str


class WeeklyScoringResult(BaseModel):
    """Weekly lineup scoring result."""
    total: float
    breakdown: Dict[str, PlayerBreakdown]
    player_count: int


class OptimalLineupInput(BaseModel):
    """Input for optimal lineup calculation."""
    roster: Dict[str, Dict[str, Any]]
    scoring_config: Dict[str, Any]
    n_qb: int = 1
    n_rb: int = 2
    n_wr: int = 2
    n_te: int = 1
    n_flex: int = 1
    n_superflex: int = 0
    n_k: int = 1
    n_def: int = 1


class OptimalLineupSlot(BaseModel):
    """A single slot in the optimal lineup."""
    player_id: str
    name: Optional[str] = None
    score: float
    position: str
    slot: str


class OptimalLineupResult(BaseModel):
    """Optimal lineup result."""
    optimal_score: float
    lineup: List[OptimalLineupSlot]
    benched: List[OptimalLineupSlot]


class SleeperWeeklyScoringInput(BaseModel):
    """Input for Sleeper weekly scoring."""
    year: int = 2024
    week: int = 1
    player_ids: List[str]
    scoring_config: Dict[str, Any]
