from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.models.league import League
from app.models.team import Team
from app.models.transaction import Transaction, TransactionType, TransactionStatus
from app.models.score_adjustment import ScoreAdjustment
from app.models.user import User
from app.schemas.commissioner import (
    ScoreAdjustmentCreate, ScoreAdjustmentRead,
    TradeReview, TradeRead, DraftOrderUpdate,
)
from app.api.deps import get_current_user, require_commissioner

router = APIRouter(prefix="/leagues/{league_id}/commissioner", tags=["commissioner"])


# ─── Helpers ───

async def _get_league(league_id: str, db: AsyncSession) -> League:
    result = await db.execute(select(League).where(League.id == league_id))
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    return league


# ═══════════════════════════════════════════════
#  1. POINTS ADJUSTMENTS
# ═══════════════════════════════════════════════

@router.post("/adjustments", status_code=201)
async def create_adjustment(
    league_id: str,
    data: ScoreAdjustmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a manual points adjustment to a team's weekly score."""
    league = await _get_league(league_id, db)
    require_commissioner(league, current_user)

    # Verify team belongs to league
    result = await db.execute(
        select(Team).where(Team.id == data.team_id, Team.league_id == league_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Team not found in this league")

    adj = ScoreAdjustment(
        league_id=league_id,
        team_id=data.team_id,
        week=data.week,
        year=data.year,
        amount=data.amount,
        reason=data.reason,
        created_by=current_user.id,
    )
    db.add(adj)
    await db.commit()
    await db.refresh(adj)
    return adj


@router.get("/adjustments")
async def list_adjustments(
    league_id: str,
    week: int | None = None,
    team_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List score adjustments for a league, optionally filtered by week or team."""
    query = select(ScoreAdjustment).where(ScoreAdjustment.league_id == league_id)
    if week is not None:
        query = query.where(ScoreAdjustment.week == week)
    if team_id is not None:
        query = query.where(ScoreAdjustment.team_id == team_id)
    query = query.order_by(ScoreAdjustment.created_at.desc())

    result = await db.execute(query)
    adjustments = result.scalars().all()
    return adjustments


@router.delete("/adjustments/{adjustment_id}")
async def delete_adjustment(
    league_id: str,
    adjustment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a score adjustment."""
    league = await _get_league(league_id, db)
    require_commissioner(league, current_user)

    result = await db.execute(
        select(ScoreAdjustment).where(
            ScoreAdjustment.id == adjustment_id,
            ScoreAdjustment.league_id == league_id,
        )
    )
    adj = result.scalar_one_or_none()
    if not adj:
        raise HTTPException(status_code=404, detail="Adjustment not found")

    await db.delete(adj)
    await db.commit()
    return {"status": "deleted"}


# ═══════════════════════════════════════════════
#  2. TRADE VETO POWER
# ═══════════════════════════════════════════════

@router.get("/trades")
async def list_pending_trades(
    league_id: str,
    status_filter: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List transactions for a league, optionally filtered by status."""
    query = select(Transaction).where(
        Transaction.league_id == league_id,
        Transaction.type == TransactionType.TRADE,
    )
    if status_filter:
        try:
            status_enum = TransactionStatus(status_filter.lower())
            query = query.where(Transaction.status == status_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status_filter}")
    query = query.order_by(Transaction.processed_at.desc())

    result = await db.execute(query)
    return result.scalars().all()


@router.post("/trades/{trade_id}/review")
async def review_trade(
    league_id: str,
    trade_id: str,
    data: TradeReview,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Approve or deny a pending trade."""
    league = await _get_league(league_id, db)
    require_commissioner(league, current_user)

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

    if trade.status != TransactionStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Trade already {trade.status.value}")

    if data.action == "approve":
        details = trade.details or {}
        target_team_id = details.get("target_team_id")
        offered_ids = set(details.get("offered_player_ids") or [])
        requested_ids = set(details.get("requested_player_ids") or [])

        proposer_result = await db.execute(select(Team).where(Team.id == trade.team_id))
        proposer = proposer_result.scalar_one_or_none()
        target_result = await db.execute(select(Team).where(Team.id == target_team_id))
        target = target_result.scalar_one_or_none()
        if not proposer or not target:
            raise HTTPException(status_code=404, detail="One of the trading teams no longer exists")

        proposer_roster = set(proposer.roster or [])
        target_roster = set(target.roster or [])

        if not offered_ids.issubset(proposer_roster):
            raise HTTPException(
                status_code=400,
                detail=f"Offered players are no longer on {proposer.name}'s roster: {sorted(offered_ids - proposer_roster)}",
            )
        if not requested_ids.issubset(target_roster):
            raise HTTPException(
                status_code=400,
                detail=f"Requested players are no longer on {target.name}'s roster: {sorted(requested_ids - target_roster)}",
            )

        proposer.roster = list((proposer_roster - offered_ids) | requested_ids)
        target.roster = list((target_roster - requested_ids) | offered_ids)

        trade.status = TransactionStatus.APPROVED
    elif data.action == "deny":
        trade.status = TransactionStatus.DENIED
    else:
        raise HTTPException(status_code=400, detail="Action must be 'approve' or 'deny'")

    trade.reviewed_by = current_user.id
    await db.commit()
    await db.refresh(trade)
    return trade


# ═══════════════════════════════════════════════
#  3. DRAFT ORDER
# ═══════════════════════════════════════════════

@router.get("/draft-order")
async def get_draft_order(league_id: str, db: AsyncSession = Depends(get_db)):
    """Get the current draft order for a league."""
    league = await _get_league(league_id, db)

    # Get all team IDs
    result = await db.execute(
        select(Team).where(Team.league_id == league_id).order_by(Team.created_at)
    )
    teams = result.scalars().all()
    team_map = {t.id: t.name for t in teams}

    # Use stored draft_order or default to team creation order
    order = league.draft_order if league.draft_order else [t.id for t in teams]
    return {
        "draft_status": league.draft_status.value,
        "current_order": [{"id": tid, "name": team_map.get(tid, "Unknown")} for tid in order],
        "all_teams": [{"id": t.id, "name": t.name} for t in teams],
        "is_locked": league.draft_status.value != "not_started",
    }


@router.put("/draft-order")
async def set_draft_order(
    league_id: str,
    data: DraftOrderUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Set a custom draft order. Only allowed before draft starts."""
    league = await _get_league(league_id, db)
    require_commissioner(league, current_user)

    if league.draft_status.value != "not_started":
        raise HTTPException(status_code=400, detail="Draft order is locked once the draft starts")

    # Verify all team IDs exist in this league
    result = await db.execute(select(Team).where(Team.league_id == league_id))
    league_team_ids = {t.id for t in result.scalars().all()}

    if set(data.team_order) != league_team_ids:
        raise HTTPException(
            status_code=400,
            detail="Team order must include exactly all league teams, no duplicates or extras"
        )

    league.draft_order = data.team_order
    await db.commit()
    return {"status": "ok", "draft_order": data.team_order}


@router.post("/draft-order/randomize")
async def randomize_draft_order(
    league_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Randomize the draft order. Only allowed before draft starts."""
    league = await _get_league(league_id, db)
    require_commissioner(league, current_user)

    if league.draft_status.value != "not_started":
        raise HTTPException(status_code=400, detail="Draft order is locked once the draft starts")

    import random
    result = await db.execute(select(Team).where(Team.league_id == league_id))
    team_ids = [t.id for t in result.scalars().all()]
    random.shuffle(team_ids)

    league.draft_order = team_ids
    await db.commit()
    return {"status": "ok", "draft_order": team_ids}
