from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from app.core.database import get_db
from app.core.limiter import limiter
from app.models.league import League
from app.models.team import Team
from app.models.transaction import Transaction, TransactionType, TransactionStatus
from app.models.score_adjustment import ScoreAdjustment
from app.models.user import User
from app.services.best_ball_service import get_best_ball_settings, is_window_open
from app.schemas.commissioner import (
    ScoreAdjustmentCreate, ScoreAdjustmentRead,
    TradeReview, TradeRead, DraftOrderUpdate,
)
from app.api.deps import get_current_user, require_commissioner
from app.services.notification_service import notify_team_owners
from app.models.notification import NotificationType
from app.models.contract import Contract
from app.services.salary_cap_service import get_salary_cap_settings, team_cap_summary
from app.services.commissioner_digest_service import generate_and_save_digest, get_digest
from app.services.trade_review_service import generate_and_save_trade_review
from app.services.league_health_service import compute_league_health
from app.services.insights_service import compute_scoring_insights
from app.services.schedule_insights_service import compute_strength_of_schedule

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

    details = trade.details or {}
    target_team_id = details.get("target_team_id")

    if data.action == "approve":
        # Best-Ball (Phase 6): only the APPROVAL action is gated by the
        # management window -- denial isn't a "grant," so there's no
        # fairness/window concern, and blocking it would just trap a
        # proposer's players in limbo longer than necessary.
        bb_settings = get_best_ball_settings(league)
        if bb_settings["enabled"] and not is_window_open(datetime.now(timezone.utc), bb_settings):
            raise HTTPException(
                status_code=400,
                detail="This league's management window is currently closed -- trade approvals resume once it reopens.",
            )

        offered_ids = set(details.get("offered_player_ids") or [])
        requested_ids = set(details.get("requested_player_ids") or [])

        # Lock both teams' rows in a fixed order (not proposer-then-target)
        # so that two trades between the same pair of teams in opposite
        # roles can't deadlock each waiting on the other's lock. Real lock
        # on Postgres (production); no-op on SQLite (local dev) -- see the
        # compare-and-swap note below for why locking alone isn't the full
        # correctness guarantee.
        locked_teams = {}
        for tid in sorted({trade.team_id, target_team_id}):
            row = await db.execute(select(Team).where(Team.id == tid).with_for_update())
            team_obj = row.scalar_one_or_none()
            if team_obj:
                locked_teams[tid] = team_obj

        proposer = locked_teams.get(trade.team_id)
        target = locked_teams.get(target_team_id)
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

        new_proposer_roster = list((proposer_roster - offered_ids) | requested_ids)
        new_target_roster = list((target_roster - requested_ids) | offered_ids)

        # Salary-Cap (Phase 5): checked against the same freshly-locked
        # rosters re-validated just above, before either CAS write lands.
        # offered_contracts/requested_contracts are captured here (not
        # re-queried after the CAS writes) so the contract-transfer step
        # below operates on exactly the rows this check just reasoned
        # about -- no window for them to drift in between.
        cap_settings = get_salary_cap_settings(league)
        offered_contracts: dict[str, Contract] = {}
        requested_contracts: dict[str, Contract] = {}
        if cap_settings["enabled"]:
            proposer_summary = await team_cap_summary(proposer, league, db)
            target_summary = await team_cap_summary(target, league, db)
            if offered_ids:
                result = await db.execute(select(Contract).where(
                    Contract.team_id == proposer.id, Contract.player_id.in_(offered_ids), Contract.is_active == True  # noqa: E712
                ))
                offered_contracts = {c.player_id: c for c in result.scalars().all()}
            if requested_ids:
                result = await db.execute(select(Contract).where(
                    Contract.team_id == target.id, Contract.player_id.in_(requested_ids), Contract.is_active == True  # noqa: E712
                ))
                requested_contracts = {c.player_id: c for c in result.scalars().all()}
            # Grandfather gap: a player rostered before salary_cap_settings
            # was ever enabled has no Contract row -- treated as $0 toward
            # cap until traded/dropped-and-resigned, same "not solved this
            # phase" limitation roster_slots changes already have (never
            # retroactive).
            offered_salary = sum(c.salary for c in offered_contracts.values())
            requested_salary = sum(c.salary for c in requested_contracts.values())
            new_proposer_total = round(proposer_summary["cap_used"] - offered_salary + requested_salary, 2)
            new_target_total = round(target_summary["cap_used"] - requested_salary + offered_salary, 2)
            if new_proposer_total > cap_settings["cap_total"]:
                raise HTTPException(status_code=400, detail=(
                    f"{proposer.name} would exceed the salary cap by this trade "
                    f"(${round(new_proposer_total - cap_settings['cap_total'], 2)} over)"
                ))
            if new_target_total > cap_settings["cap_total"]:
                raise HTTPException(status_code=400, detail=(
                    f"{target.name} would exceed the salary cap by this trade "
                    f"(${round(new_target_total - cap_settings['cap_total'], 2)} over)"
                ))
            if len(new_proposer_roster) > cap_settings["max_roster_size"] or len(new_target_roster) > cap_settings["max_roster_size"]:
                raise HTTPException(status_code=400, detail="This trade would put a roster over its size limit")

        # Atomic, conditional roster swap -- only succeeds if each team's
        # roster_version still matches what was just observed above (i.e.
        # nothing else committed a roster change to it in between). Without
        # this, two pending trades that both touch one team's roster,
        # approved concurrently (a commissioner clearing a backlog fast, or
        # a double-click), silently lose one trade's player movement while
        # BOTH end up marked status=="approved" -- confirmed locally: with
        # an artificial delay inserted between the read and the write here,
        # two concurrent approvals reproduced the lost update every time.
        # with_for_update() above makes this the non-racing common path on
        # Postgres; this version check is what actually guarantees
        # correctness, including on SQLite where the lock is a no-op.
        proposer_cas = await db.execute(
            update(Team)
            .where(Team.id == proposer.id, Team.roster_version == proposer.roster_version)
            .values(roster=new_proposer_roster, roster_version=Team.roster_version + 1)
        )
        target_cas = await db.execute(
            update(Team)
            .where(Team.id == target.id, Team.roster_version == target.roster_version)
            .values(roster=new_target_roster, roster_version=Team.roster_version + 1)
        )
        if proposer_cas.rowcount == 0 or target_cas.rowcount == 0:
            raise HTTPException(
                status_code=409,
                detail="One of the trading teams' rosters changed since this review started "
                       "(likely another trade for the same team was just approved). Please retry.",
            )

        # Salary-Cap (Phase 5): contracts travel with the trade -- salary/
        # contract_years/signed_year are preserved exactly as signed, only
        # team_id moves. No dead money on a trade (that's specifically an
        # early-*release* penalty; trading a player transfers the
        # league's cap obligation for them, it doesn't shed it).
        for contract in offered_contracts.values():
            contract.team_id = target.id
        for contract in requested_contracts.values():
            contract.team_id = proposer.id

        trade.status = TransactionStatus.APPROVED
        trade_link = f"/leagues/{league_id}/trades"
        await notify_team_owners(db, proposer, NotificationType.TRADE_APPROVED,
                                  f"Your trade with {target.name} was approved.", league_id, trade_link)
        await notify_team_owners(db, target, NotificationType.TRADE_APPROVED,
                                  f"Your trade with {proposer.name} was approved.", league_id, trade_link)
    elif data.action == "deny":
        trade.status = TransactionStatus.DENIED
        result = await db.execute(select(Team).where(Team.id.in_({trade.team_id, target_team_id})))
        teams_by_id = {t.id: t for t in result.scalars().all()}
        proposer = teams_by_id.get(trade.team_id)
        target = teams_by_id.get(target_team_id)
        trade_link = f"/leagues/{league_id}/trades"
        if proposer:
            other_name = target.name if target else "the other team"
            await notify_team_owners(db, proposer, NotificationType.TRADE_DENIED,
                                      f"Your trade with {other_name} was denied.", league_id, trade_link)
        if target:
            other_name = proposer.name if proposer else "the other team"
            await notify_team_owners(db, target, NotificationType.TRADE_DENIED,
                                      f"Your trade with {other_name} was denied.", league_id, trade_link)
    else:
        raise HTTPException(status_code=400, detail="Action must be 'approve' or 'deny'")

    trade.reviewed_by = current_user.id
    await db.commit()
    await db.refresh(trade)
    return trade


@router.post("/trades/{trade_id}/analyze")
@limiter.limit("10/hour")
async def analyze_trade_for_review(
    request: Request,
    league_id: str,
    trade_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Smart Trade Review Assistant (AI Co-Commissioner v1) -- AI
    fairness/league-impact/collusion-pattern analysis for a pending
    trade, with a clear recommendation, to help the commissioner decide
    whether to approve it. Rate-limited (real LLM spend), commissioner-
    only. Never touches trade.status/reviewed_by -- review_trade's own
    approve/deny flow is completely unaffected by whether this was
    ever called."""
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
        raise HTTPException(status_code=400, detail="Only a pending trade can be analyzed")

    target_team_id = (trade.details or {}).get("target_team_id")
    proposer_result = await db.execute(select(Team).where(Team.id == trade.team_id))
    proposer = proposer_result.scalar_one_or_none()
    target_result = await db.execute(select(Team).where(Team.id == target_team_id))
    target = target_result.scalar_one_or_none()
    if not proposer or not target:
        raise HTTPException(status_code=404, detail="One of the trading teams no longer exists")

    review = await generate_and_save_trade_review(trade, league, proposer, target, current_user.id, db)
    return review


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


# ═══════════════════════════════════════════════
# AI COMMISSIONER DIGEST (Phase 8, "AI-Assisted Commissioner Tools")
# ═══════════════════════════════════════════════
# Commissioner-triggered on demand only -- no scheduler integration.
# The generate endpoint is the only one that spends real LLM API money,
# so it's rate-limited the same way /ai/lineup and /ai/trade already
# are; the GET is a plain cached read, unlimited like every other read
# in this router.

# AI Co-Commissioner v1: per-generation tone/length -- see
# ai_service.py's TONE_INSTRUCTIONS/LENGTH_INSTRUCTIONS for the actual
# prompt phrasing each value maps to.
_VALID_TONES = {"professional", "casual", "hype", "sarcastic", "dry"}
_VALID_LENGTHS = {"short", "full"}


@router.post("/digest/generate")
@limiter.limit("10/hour")
async def generate_digest(
    request: Request,
    league_id: str,
    week: int,
    year: int,
    tone: str = "professional",
    length: str = "full",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if tone not in _VALID_TONES:
        raise HTTPException(status_code=422, detail=f"tone must be one of {sorted(_VALID_TONES)}")
    if length not in _VALID_LENGTHS:
        raise HTTPException(status_code=422, detail=f"length must be one of {sorted(_VALID_LENGTHS)}")

    league = await _get_league(league_id, db)
    require_commissioner(league, current_user)
    digest = await generate_and_save_digest(league, week, year, current_user.id, db, tone=tone, length=length)
    return {
        "week": digest.week, "year": digest.year, "content": digest.content,
        "created_at": digest.created_at, "tone": digest.tone, "length": digest.length,
    }


@router.get("/digest")
async def get_digest_route(
    league_id: str,
    week: int,
    year: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    league = await _get_league(league_id, db)
    require_commissioner(league, current_user)
    digest = await get_digest(league_id, week, year, db)
    if not digest:
        raise HTTPException(status_code=404, detail="No digest generated for this week yet")
    return {
        "week": digest.week, "year": digest.year, "content": digest.content,
        "created_at": digest.created_at, "tone": digest.tone, "length": digest.length,
    }


# ═══════════════════════════════════════════════
#  5. LEAGUE HEALTH DASHBOARD (AI Co-Commissioner v1)
# ═══════════════════════════════════════════════
# Pure computation, zero LLM calls -- see league_health_service.py.
# Cheap and deterministic, so no rate limit and no persistence:
# recomputed fresh on every request.

@router.get("/health")
async def get_league_health(
    league_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    league = await _get_league(league_id, db)
    require_commissioner(league, current_user)
    return await compute_league_health(league, db)


# ═══════════════════════════════════════════════
#  6. SCORING & RULE INSIGHTS (AI Co-Commissioner v1, Phase 2)
# ═══════════════════════════════════════════════
# Pure computation, zero LLM calls -- see insights_service.py. Cheap
# and deterministic, same shape as Section 5: no rate limit, no
# persistence, recomputed fresh on every request.

@router.get("/insights")
async def get_scoring_insights(
    league_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    league = await _get_league(league_id, db)
    require_commissioner(league, current_user)
    return await compute_scoring_insights(league, db)


# ═══════════════════════════════════════════════
#  7. SCHEDULE INSIGHTS (AI Co-Commissioner v1, Phase 2)
# ═══════════════════════════════════════════════
# Pure computation, zero LLM calls -- see schedule_insights_service.py.
# No rate limit, no persistence, recomputed fresh on every request.

@router.get("/schedule-insights")
async def get_schedule_insights(
    league_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    league = await _get_league(league_id, db)
    require_commissioner(league, current_user)
    return await compute_strength_of_schedule(league, db)
