from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.core.database import get_db
from app.core.config import settings
from app.models.team import Team
from app.models.league import League
from app.models.player import Player
from app.models.transaction import Transaction, TransactionType
from app.models.user import User
from app.services.ai_service import AIService
from app.services.standings_service import get_standings
from app.api.deps import get_current_user

router = APIRouter(prefix="/ai", tags=["ai"])


def _get_ai_service() -> AIService:
    if settings.OPENAI_API_KEY:
        return AIService(api_key=settings.OPENAI_API_KEY, provider="openai")
    if settings.ANTHROPIC_API_KEY:
        return AIService(api_key=settings.ANTHROPIC_API_KEY, provider="anthropic")
    return AIService(api_key=None)


async def _roster_summary(team: Team, db: AsyncSession) -> dict:
    if not team.roster:
        return {}
    result = await db.execute(select(Player).where(Player.id.in_(team.roster)))
    players = result.scalars().all()
    return {
        p.id: {"name": f"{p.first_name} {p.last_name}", "position": p.position, "team": p.team}
        for p in players
    }


class LineupAnalysisRequest(BaseModel):
    team_id: str


class TradeAnalysisRequest(BaseModel):
    trade_id: str


class BetAnalysisRequest(BaseModel):
    prompt: str


@router.post("/lineup")
async def analyze_lineup(
    request: LineupAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get AI lineup/start-sit analysis for a team's current roster."""
    result = await db.execute(select(Team).where(Team.id == request.team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    if current_user.id not in {team.owner_id, team.co_owner_id}:
        raise HTTPException(status_code=403, detail="You do not own this team")

    league_result = await db.execute(select(League).where(League.id == team.league_id))
    league = league_result.scalar_one_or_none()
    scoring = (league.scoring_config if league else None) or {}

    roster = await _roster_summary(team, db)

    service = _get_ai_service()
    analysis = await service.analyze_lineup(
        roster=roster, opponent_roster={}, matchups={}, scoring=scoring
    )
    return {"analysis": analysis}


@router.post("/trade")
async def analyze_trade(
    request: TradeAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get AI evaluation of a proposed trade."""
    result = await db.execute(
        select(Transaction).where(
            Transaction.id == request.trade_id,
            Transaction.type == TransactionType.TRADE,
        )
    )
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    details = trade.details or {}
    target_team_id = details.get("target_team_id")

    proposer_result = await db.execute(select(Team).where(Team.id == trade.team_id))
    proposer = proposer_result.scalar_one_or_none()
    target_result = await db.execute(select(Team).where(Team.id == target_team_id))
    target = target_result.scalar_one_or_none()
    if not proposer or not target:
        raise HTTPException(status_code=404, detail="One of the trading teams no longer exists")

    if current_user.id not in {proposer.owner_id, proposer.co_owner_id, target.owner_id, target.co_owner_id}:
        raise HTTPException(status_code=403, detail="You are not part of this trade")

    league_result = await db.execute(select(League).where(League.id == trade.league_id))
    league = league_result.scalar_one_or_none()
    scoring = (league.scoring_config if league else None) or {}

    offered_ids = details.get("offered_player_ids") or []
    requested_ids = details.get("requested_player_ids") or []
    players_result = await db.execute(
        select(Player).where(Player.id.in_(offered_ids + requested_ids))
    )
    player_map = {p.id: {"name": f"{p.first_name} {p.last_name}", "position": p.position} for p in players_result.scalars().all()}
    offered = [player_map.get(pid, {"name": pid}) for pid in offered_ids]
    requested = [player_map.get(pid, {"name": pid}) for pid in requested_ids]

    standings = await get_standings(trade.league_id, db)

    service = _get_ai_service()
    analysis = await service.analyze_trade(
        team_a_players=offered, team_b_players=requested, scoring=scoring, standings={"standings": standings}
    )
    return {"analysis": analysis}


@router.post("/bet")
async def analyze_bet(
    request: BetAnalysisRequest,
    current_user: User = Depends(get_current_user),
):
    """Freeform betting-angle analysis. No live odds/weather data source exists yet,
    so this passes the user's own description straight to the LLM."""
    service = _get_ai_service()
    analysis = await service.analyze_bet(matchup={"description": request.prompt}, lines={})
    return {"analysis": analysis}
