from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.league import League
from app.models.team import Team
from app.models.transaction import Transaction, TransactionType, TransactionStatus
from app.models.user import User
from app.schemas.trade import TradeProposalCreate
from app.api.deps import get_current_user

router = APIRouter(prefix="/leagues/{league_id}/trades", tags=["trades"])


async def _get_team_in_league(team_id: str, league_id: str, db: AsyncSession) -> Team:
    result = await db.execute(select(Team).where(Team.id == team_id, Team.league_id == league_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail=f"Team {team_id} not found in this league")
    return team


@router.post("", status_code=201)
async def propose_trade(
    league_id: str,
    data: TradeProposalCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Propose a trade between two teams. Goes straight to the commissioner's review queue."""
    league_result = await db.execute(select(League).where(League.id == league_id))
    league = league_result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")

    if data.team_id == data.target_team_id:
        raise HTTPException(status_code=400, detail="Cannot trade with your own team")

    proposing_team = await _get_team_in_league(data.team_id, league_id, db)
    target_team = await _get_team_in_league(data.target_team_id, league_id, db)

    if current_user.id not in {proposing_team.owner_id, proposing_team.co_owner_id}:
        raise HTTPException(status_code=403, detail="You do not own the proposing team")

    proposing_roster = set(proposing_team.roster or [])
    target_roster = set(target_team.roster or [])

    missing_offered = set(data.offered_player_ids) - proposing_roster
    if missing_offered:
        raise HTTPException(status_code=400, detail=f"Players not on your roster: {sorted(missing_offered)}")

    missing_requested = set(data.requested_player_ids) - target_roster
    if missing_requested:
        raise HTTPException(status_code=400, detail=f"Players not on target team's roster: {sorted(missing_requested)}")

    trade = Transaction(
        league_id=league_id,
        team_id=data.team_id,
        type=TransactionType.TRADE,
        status=TransactionStatus.PENDING,
        details={
            "target_team_id": data.target_team_id,
            "offered_player_ids": data.offered_player_ids,
            "requested_player_ids": data.requested_player_ids,
        },
    )
    db.add(trade)
    await db.commit()
    await db.refresh(trade)
    return trade


@router.get("")
async def list_team_trades(
    league_id: str,
    team_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List trades for a league, optionally filtered to those involving a given team (as proposer or target)."""
    result = await db.execute(
        select(Transaction).where(
            Transaction.league_id == league_id,
            Transaction.type == TransactionType.TRADE,
        ).order_by(Transaction.processed_at.desc())
    )
    trades = result.scalars().all()

    if team_id:
        trades = [
            t for t in trades
            if t.team_id == team_id or (t.details or {}).get("target_team_id") == team_id
        ]

    return trades
