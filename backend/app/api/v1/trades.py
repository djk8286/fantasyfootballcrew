from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.limiter import limiter
from app.models.league import League, LeagueType
from app.models.team import Team
from app.models.transaction import Transaction, TransactionType, TransactionStatus
from app.models.user import User
from app.models.notification import NotificationType
from app.schemas.trade import TradeProposalCreate, TradeResponse
from app.api.deps import get_current_user, require_league_view
from app.services.cpu_trade_service import evaluate_cpu_response, apply_cpu_verdict, answer_pending_cpu_trades
from app.services.notification_service import create_notification, notify_team_owners
from app.services.trade_writes import write_pending_trade

router = APIRouter(prefix="/leagues/{league_id}/trades", tags=["trades"])


def _managers(team: Team) -> set[str]:
    return {team.owner_id, team.co_owner_id} - {None}


def _dual_squad_pair(league: League, a: Team, b: Team) -> bool:
    return league.league_type == LeagueType.DUAL_SQUAD and a.partner_team_id == b.id


def _refuse_eliminated(*teams: Team) -> None:
    # Same rule as waiver claims. An eliminated Guillotine team is out.
    for team in teams:
        if team.eliminated_week is not None:
            raise HTTPException(status_code=400, detail=f"{team.name} has been eliminated and can no longer trade")


async def _notify_commissioners_to_review(
    db: AsyncSession, league: League, proposer: Team, target: Team, actor_id: str,
) -> set[str]:
    commissioners = {league.commissioner_id, *(league.co_commissioner_ids or [])} - {None}
    for user_id in commissioners - {actor_id}:
        await create_notification(
            db, user_id, NotificationType.TRADE_ACCEPTED,
            f"{target.name} accepted a trade from {proposer.name}. It needs your review.",
            league_id=league.id, link=f"/leagues/{league.id}/commissioner?tab=trades",
        )
    return commissioners


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
    _refuse_eliminated(proposing_team, target_team)

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
    elif _dual_squad_pair(league, proposing_team, target_team) and current_user.id in _managers(target_team):
        # Your own Dual-Squad partner. You already said yes.
        details["recipient_response"] = "accepted"

    trade = Transaction(
        league_id=league_id,
        team_id=data.team_id,
        type=TransactionType.TRADE,
        status=trade_status,
        details=details,
    )
    db.add(trade)
    if trade_status == TransactionStatus.PENDING:
        if "accepted" in {details.get("recipient_response"), details.get("cpu_response")}:
            await _notify_commissioners_to_review(db, league, proposing_team, target_team, current_user.id)
        elif not target_team.is_cpu:
            # Someone on both teams can't answer it, so they get no offer.
            for user_id in _managers(target_team) - _managers(proposing_team):
                await create_notification(
                    db, user_id, NotificationType.TRADE_OFFER,
                    f"{proposing_team.name} sent you a trade offer.",
                    league_id=league_id, link=f"/leagues/{league_id}/trades",
                )
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
        ).with_for_update()  # serialize answers, cancel and review on this trade (Postgres)
    )
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    proposer = await _get_team_in_league(trade.team_id, league_id, db)
    if current_user.id not in {proposer.owner_id, proposer.co_owner_id}:
        raise HTTPException(status_code=403, detail="Only the proposing team can cancel this trade")
    if trade.status != TransactionStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Trade already {trade.status.value}")
    await write_pending_trade(
        db, trade, status=TransactionStatus.DENIED,
        details={**(trade.details or {}), "cancelled_by_proposer": True},
    )
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
    league = (await db.execute(select(League).where(League.id == league_id))).scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    result = await db.execute(
        select(Transaction).where(
            Transaction.id == trade_id,
            Transaction.league_id == league_id,
            Transaction.type == TransactionType.TRADE,
        ).with_for_update()  # serialize answers, cancel and review on this trade (Postgres)
    )
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    details = trade.details or {}
    target = await _get_team_in_league(details.get("target_team_id") or "", league_id, db)
    proposer = await _get_team_in_league(trade.team_id, league_id, db)
    if current_user.id not in _managers(target):
        raise HTTPException(status_code=403, detail="Only the team receiving this offer can answer it")
    if current_user.id in _managers(proposer) and not _dual_squad_pair(league, proposer, target):
        raise HTTPException(status_code=403, detail="You manage both teams in this trade, so you can't answer it")
    if trade.status != TransactionStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Trade already {trade.status.value}")
    if details.get("recipient_response") or details.get("cpu_response"):
        raise HTTPException(status_code=400, detail="This offer was already answered")

    accepted = data.action == "accept"
    new_details = {**details, "recipient_response": "accepted" if accepted else "declined"}
    trades_link = f"/leagues/{league_id}/trades"
    if accepted:
        await write_pending_trade(db, trade, unanswered=True, details=new_details)
        commissioners = await _notify_commissioners_to_review(db, league, proposer, target, current_user.id)
        for user_id in _managers(proposer) - commissioners:
            await create_notification(
                db, user_id, NotificationType.TRADE_ACCEPTED,
                f"{target.name} accepted your trade offer. It now goes to the commissioner.",
                league_id=league_id, link=trades_link,
            )
    else:
        await write_pending_trade(
            db, trade, unanswered=True, details=new_details, status=TransactionStatus.DENIED,
        )
        await notify_team_owners(
            db, proposer, NotificationType.TRADE_DENIED, f"{target.name} declined your trade offer.",
            league_id=league_id, link=trades_link,
        )
    await db.commit()
    await db.refresh(trade)
    return trade
