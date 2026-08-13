from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.core.database import get_db
from app.core.config import settings
from app.core.limiter import limiter
from app.models.team import Team
from app.models.league import League
from app.models.player import Player
from app.models.coach import Coach
from app.models.transaction import Transaction, TransactionType
from app.models.user import User
from app.services.ai_service import AIService
from app.services.standings_service import get_standings
from app.services.salary_cap_service import get_salary_cap_settings, team_cap_summary
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


async def _coach_summary(team: Team, db: AsyncSession) -> list[dict]:
    """A team's active coaching staff, for threading into AI prompt
    context (Phase 2 Step 3, "Front-Office finish-out") -- lets the AI
    factor a team's win_bonus/flat_weekly coaches into its commentary."""
    result = await db.execute(
        select(Coach).where(Coach.team_id == team.id, Coach.is_active == True)  # noqa: E712
    )
    return [
        {"position": c.position.value, "name": c.name, "bonus_type": c.bonus_type, "bonus_value": c.bonus_value}
        for c in result.scalars().all()
    ]


async def _salary_summary(team: Team, league: League, db: AsyncSession) -> dict:
    """A team's cap situation, for threading into AI prompt context
    (Phase 5, "Salary-Cap + Contract Leagues") -- lets the AI factor cap
    space/contract obligations into its lineup/trade commentary. No-ops
    to {} for a non-cap league, same house style as _coach_summary
    returning [] for a team with no coaches."""
    if not league or not get_salary_cap_settings(league)["enabled"]:
        return {}
    return await team_cap_summary(team, league, db)


class LineupAnalysisRequest(BaseModel):
    team_id: str


class TradeAnalysisRequest(BaseModel):
    trade_id: str


class BetAnalysisRequest(BaseModel):
    prompt: str


@router.post("/lineup")
@limiter.limit("10/hour")
async def analyze_lineup(
    request: Request,
    body: LineupAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get AI lineup/start-sit analysis for a team's current roster.
    Rate-limited (unlike everything else in this router before this) --
    each call is a real LLM API request once a key is configured, so an
    unlimited endpoint is a real cost/abuse surface, not just a
    theoretical one."""
    result = await db.execute(select(Team).where(Team.id == body.team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    if current_user.id not in {team.owner_id, team.co_owner_id}:
        raise HTTPException(status_code=403, detail="You do not own this team")

    league_result = await db.execute(select(League).where(League.id == team.league_id))
    league = league_result.scalar_one_or_none()
    scoring = (league.scoring_config if league else None) or {}

    roster = await _roster_summary(team, db)
    coaching_staff = await _coach_summary(team, db)
    salary_context = await _salary_summary(team, league, db)

    service = _get_ai_service()
    analysis = await service.analyze_lineup(
        roster=roster, opponent_roster={}, matchups={}, scoring=scoring,
        coaching_staff=coaching_staff, salary_context=salary_context,
    )
    return {"analysis": analysis}


@router.post("/trade")
@limiter.limit("10/hour")
async def analyze_trade(
    request: Request,
    body: TradeAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get AI evaluation of a proposed trade."""
    result = await db.execute(
        select(Transaction).where(
            Transaction.id == body.trade_id,
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
    team_a_coaching = await _coach_summary(proposer, db)
    team_b_coaching = await _coach_summary(target, db)
    team_a_salary = await _salary_summary(proposer, league, db)
    team_b_salary = await _salary_summary(target, league, db)

    service = _get_ai_service()
    analysis = await service.analyze_trade(
        team_a_players=offered, team_b_players=requested, scoring=scoring, standings={"standings": standings},
        team_a_coaching=team_a_coaching, team_b_coaching=team_b_coaching,
        team_a_salary=team_a_salary, team_b_salary=team_b_salary,
    )
    return {"analysis": analysis}


@router.post("/bet")
@limiter.limit("10/hour")
async def analyze_bet(
    request: Request,
    body: BetAnalysisRequest,
    current_user: User = Depends(get_current_user),
):
    """Freeform betting-angle analysis. No live odds/weather data source exists yet,
    so this passes the user's own description straight to the LLM."""
    service = _get_ai_service()
    analysis = await service.analyze_bet(matchup={"description": body.prompt}, lines={})
    return {"analysis": analysis}
