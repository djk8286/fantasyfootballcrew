import re
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.core.database import get_db
from app.core.config import settings
from app.core.limiter import limiter
from app.models.team import Team
from app.models.league import League, LeagueType
from app.models.player import Player
from app.models.coach import Coach
from app.models.transaction import Transaction, TransactionType
from app.models.user import User
from app.services.ai_service import AIService
from app.services.standings_service import get_standings, get_combined_standings
from app.services.salary_cap_service import get_salary_cap_settings, team_cap_summary
from app.api.deps import get_current_user

router = APIRouter(prefix="/ai", tags=["ai"])


def _get_ai_service() -> AIService:
    if settings.OPENAI_API_KEY:
        return AIService(api_key=settings.OPENAI_API_KEY, provider="openai")
    if settings.ANTHROPIC_API_KEY:
        return AIService(api_key=settings.ANTHROPIC_API_KEY, provider="anthropic")
    return AIService(api_key=None)


# Two-or-three consecutive Capitalized words -- "Justin Fields", "Odell
# Beckham Jr" -- as a lightweight, no-NLP-dependency way to spot likely
# player names in a Bet tab's free-text prompt (the ONLY AI Analysis
# feature with zero structured input, see analyze_bet below). Deliberately
# loose: false positives (matching a phrase that isn't actually a player)
# just mean the DB lookup below finds nothing and it's silently dropped;
# there's no cost to over-triggering here, only to under-triggering.
_NAME_CANDIDATE_RE = re.compile(r"\b[A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+){1,2}\b")


async def _verified_players_from_text(text: str, db: AsyncSession) -> list[dict]:
    """Extract candidate player names from free text and look each up
    against this app's own synced Player data (real current team/
    position/injury_status from Sleeper, not the LLM's training
    memory) -- see analyze_bet's docstring for why this exists.

    A regex match can be 2-3 capitalized words, and the FIRST word isn't
    reliably the first name -- a sentence-initial capital ("Is Puka
    Nacua a good start?") gets swept into the same match as a real name,
    and a suffix ("Odell Beckham Jr") puts the real last name in the
    middle, not last. Rather than guess which word is which, try every
    consecutive 2-word window inside each match as a (first, last)
    candidate pair -- cheap (matches are short) and side-effect-free
    (an extra wrong pairing just finds zero rows in the DB and is
    silently dropped, same as any other false positive here)."""
    seen_ids: set[str] = set()
    verified: list[dict] = []
    for candidate in set(_NAME_CANDIDATE_RE.findall(text)):
        words = candidate.split()
        for i in range(len(words) - 1):
            first, last = words[i], words[i + 1]
            result = await db.execute(
                select(Player).where(Player.first_name.ilike(first), Player.last_name.ilike(last))
            )
            for p in result.scalars().all():
                if p.id in seen_ids:
                    continue
                seen_ids.add(p.id)
                verified.append({
                    "name": f"{p.first_name} {p.last_name}",
                    "position": p.position,
                    "current_team": p.team or "Free Agent",
                    "injury_status": p.injury_status or "none reported",
                })
    return verified


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


async def _partner_summary(team: Team, league: League, db: AsyncSession) -> dict:
    """A team's linked-pair context, for threading into AI prompt
    context (Phase 7, "Dual-Squad/Mirror") -- lets the AI factor a
    manager's OTHER team's record into lineup/trade commentary (e.g.
    "your pair is already locked into 1st combined, this trade is
    low-stakes"). No-ops to {} for a non-paired team/league, same house
    style as _salary_summary returning {} for a non-cap league."""
    if not league or league.league_type != LeagueType.DUAL_SQUAD or not team.partner_team_id:
        return {}
    combined = await get_combined_standings(league.id, db)
    row = next((r for r in combined if team.id in r["team_ids"]), None)
    return row or {}


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
    partner_context = await _partner_summary(team, league, db)

    service = _get_ai_service()
    analysis = await service.analyze_lineup(
        roster=roster, opponent_roster={}, matchups={}, scoring=scoring,
        coaching_staff=coaching_staff, salary_context=salary_context,
        partner_context=partner_context,
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
    team_a_partner = await _partner_summary(proposer, league, db)
    team_b_partner = await _partner_summary(target, league, db)

    service = _get_ai_service()
    analysis = await service.analyze_trade(
        team_a_players=offered, team_b_players=requested, scoring=scoring, standings={"standings": standings},
        team_a_coaching=team_a_coaching, team_b_coaching=team_b_coaching,
        team_a_salary=team_a_salary, team_b_salary=team_b_salary,
        team_a_partner=team_a_partner, team_b_partner=team_b_partner,
    )
    return {"analysis": analysis}


@router.post("/bet")
@limiter.limit("10/hour")
async def analyze_bet(
    request: Request,
    body: BetAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Freeform betting-angle analysis. When OpenAI is the configured
    provider, this does REAL live web research (current odds, injury
    reports, snap counts) via AIService._call_openai_search -- not just
    training memory + whatever the user typed. Any player names
    mentioned also get looked up against this app's own synced roster
    data first (see _verified_players_from_text) as a fast, free
    cross-check alongside that search, so the model has real current
    team/position/injury data to ground against too. Falls back to a
    no-search, honestly-hedged prompt for any other/no configured
    provider -- see ai_service.py's BET_ANALYSIS_PROMPT vs.
    BET_ANALYSIS_SEARCH_SYSTEM_PROMPT."""
    verified_players = await _verified_players_from_text(body.prompt, db)
    service = _get_ai_service()
    analysis = await service.analyze_bet(
        matchup={"description": body.prompt}, lines={}, verified_players=verified_players,
    )
    return {"analysis": analysis}
