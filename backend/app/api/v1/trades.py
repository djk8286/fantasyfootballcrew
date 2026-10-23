from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.limiter import limiter
from app.models.league import League
from app.models.team import Team
from app.models.transaction import Transaction, TransactionType, TransactionStatus
from app.models.user import User
from app.models.notification import NotificationType
from app.schemas.trade import TradeProposalCreate, TradeResponse
from app.api.deps import get_current_user, require_league_view
from app.services.cpu_trade_service import evaluate_cpu_response, apply_cpu_verdict, answer_pending_cpu_trades
from app.services.notification_service import notify_team_owners

router = APIRouter(prefix="/leagues/{league_id}/trades", tags=["trades"])


async def _get_team_in_league(team_id: str, league_id: str, db: AsyncSession) -> Team:
    result = await db.execute(select(Team).where(Team.id == team_id, Team.league_id == league_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail=f"Team {team_id} not found in this league")
    return team


@router.post("", status_code=201)
@limiter.limit("20/hour")
async def propose_trade(
    request: Request,
    league_id: str,
    data: TradeProposalCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Propose a trade. The target team answers first (CPU teams at once,
    humans via /respond). Only an accepted trade reaches commissioner review."""
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

    details = {
        "target_team_id": data.target_team_id,
        "offered_player_ids": data.offered_player_ids,
        "requested_player_ids": data.requested_player_ids,
    }
    trade_status = TransactionStatus.PENDING
    # CPU teams answer immediately (they used to leave offers pending
    # forever). Declined -> closed now; accepted -> normal commissioner review.
    if target_team.is_cpu:
        verdict = await evaluate_cpu_response(db, data.offered_player_ids, data.requested_player_ids)
        trade_status = apply_cpu_verdict(details, verdict)
    elif current_user.id in {target_team.owner_id, target_team.co_owner_id}:
        # Dual-Squad: both squads are yours, so you already said yes.
        details["recipient_response"] = "accepted"

    trade = Transaction(
        league_id=league_id,
        team_id=data.team_id,
        type=TransactionType.TRADE,
        status=trade_status,
        details=details,
    )
    db.add(trade)
    await db.commit()
    await db.refresh(trade)
    return trade


@router.get("", dependencies=[Depends(require_league_view)])
async def list_team_trades(
    league_id: str,
    team_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List trades for a league, optionally filtered to those involving a given team (as proposer or target)."""
    # Any offer still waiting on a CPU team gets its answer before we read
    # (see cpu_trade_service.answer_pending_cpu_trades).
    if await answer_pending_cpu_trades(db, league_id):
        await db.commit()
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


@router.post("/{trade_id}/cancel")
@limiter.limit("30/hour")
async def cancel_trade(
    request: Request,
    league_id: str,
    trade_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The proposer withdraws a still-pending trade."""
    result = await db.execute(
        select(Transaction).where(
            Transaction.id == trade_id,
            Transaction.league_id == league_id,
            Transaction.type == TransactionType.TRADE,
        )
    )
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    proposer = await _get_team_in_league(trade.team_id, league_id, db)
    if current_user.id not in {proposer.owner_id, proposer.co_owner_id}:
        raise HTTPException(status_code=403, detail="Only the proposing team can cancel this trade")
    if trade.status != TransactionStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Trade already {trade.status.value}")
    trade.status = TransactionStatus.DENIED
    trade.details = {**(trade.details or {}), "cancelled_by_proposer": True}
    await db.commit()
    await db.refresh(trade)
    return trade


@router.post("/{trade_id}/respond")
@limiter.limit("30/hour")
async def respond_to_trade(
    request: Request,
    league_id: str,
    trade_id: str,
    data: TradeResponse,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The target team's owner or co-owner accepts or declines a pending
    offer. Decline closes it. Accept sends it to commissioner review."""
    result = await db.execute(
        select(Transaction).where(
            Transaction.id == trade_id,
            Transaction.league_id == league_id,
            Transaction.type == TransactionType.TRADE,
        )
    )
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    details = trade.details or {}
    target = await _get_team_in_league(details.get("target_team_id") or "", league_id, db)
    if current_user.id not in {target.owner_id, target.co_owner_id}:
        raise HTTPException(status_code=403, detail="Only the team receiving this offer can answer it")
    if trade.status != TransactionStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Trade already {trade.status.value}")
    if details.get("recipient_response") or details.get("cpu_response"):
        raise HTTPException(status_code=400, detail="This offer was already answered")

    accepted = data.action == "accept"
    trade.details = {**details, "recipient_response": "accepted" if accepted else "declined"}
    if not accepted:
        trade.status = TransactionStatus.DENIED
        proposer = await _get_team_in_league(trade.team_id, league_id, db)
        await notify_team_owners(
            db, proposer, NotificationType.TRADE_DENIED, f"{target.name} declined your trade offer.",
            league_id=league_id, link=f"/leagues/{league_id}/trades",
        )
    await db.commit()
    await db.refresh(trade)
    return trade
