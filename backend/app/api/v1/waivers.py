from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.league import League
from app.models.team import Team
from app.models.transaction import Transaction, TransactionType, TransactionStatus
from app.models.user import User
from app.schemas.waiver import WaiverClaimCreate
from app.api.deps import get_current_user, require_commissioner

router = APIRouter(prefix="/leagues/{league_id}/waivers", tags=["waivers"])


async def _get_league(league_id: str, db: AsyncSession) -> League:
    result = await db.execute(select(League).where(League.id == league_id))
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    return league


async def _get_team_in_league(team_id: str, league_id: str, db: AsyncSession) -> Team:
    result = await db.execute(select(Team).where(Team.id == team_id, Team.league_id == league_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail=f"Team {team_id} not found in this league")
    return team


async def _priority_order(league: League, league_id: str, db: AsyncSession) -> list[str]:
    """Current waiver priority, defaulting to team creation order if never set."""
    if league.waiver_priority:
        return league.waiver_priority
    result = await db.execute(
        select(Team).where(Team.league_id == league_id).order_by(Team.created_at)
    )
    return [t.id for t in result.scalars().all()]


@router.post("/claims", status_code=201)
async def submit_claim(
    league_id: str,
    data: WaiverClaimCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Submit a waiver claim to add a free agent (optionally dropping a roster player)."""
    await _get_league(league_id, db)
    team = await _get_team_in_league(data.team_id, league_id, db)

    if current_user.id not in {team.owner_id, team.co_owner_id}:
        raise HTTPException(status_code=403, detail="You do not own this team")

    if data.drop_player_id and data.drop_player_id not in (team.roster or []):
        raise HTTPException(status_code=400, detail="Drop player is not on your roster")

    # The add target must currently be a free agent (not on any roster in the league)
    all_teams_result = await db.execute(select(Team).where(Team.league_id == league_id))
    for other in all_teams_result.scalars().all():
        if data.add_player_id in (other.roster or []):
            raise HTTPException(status_code=400, detail="Player is already rostered in this league")

    claim = Transaction(
        league_id=league_id,
        team_id=data.team_id,
        type=TransactionType.WAIVER,
        status=TransactionStatus.PENDING,
        details={"add_player_id": data.add_player_id, "drop_player_id": data.drop_player_id},
    )
    db.add(claim)
    await db.commit()
    await db.refresh(claim)
    return claim


@router.get("/claims")
async def list_claims(
    league_id: str,
    team_id: str | None = None,
    status_filter: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(Transaction).where(
        Transaction.league_id == league_id,
        Transaction.type == TransactionType.WAIVER,
    )
    if team_id:
        query = query.where(Transaction.team_id == team_id)
    if status_filter:
        try:
            query = query.where(Transaction.status == TransactionStatus(status_filter.lower()))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status_filter}")
    query = query.order_by(Transaction.processed_at.asc())

    result = await db.execute(query)
    return result.scalars().all()


@router.delete("/claims/{claim_id}")
async def cancel_claim(
    league_id: str,
    claim_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Transaction).where(
            Transaction.id == claim_id,
            Transaction.league_id == league_id,
            Transaction.type == TransactionType.WAIVER,
        )
    )
    claim = result.scalar_one_or_none()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    if claim.status != TransactionStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Claim already {claim.status.value}")

    team = await _get_team_in_league(claim.team_id, league_id, db)
    if current_user.id not in {team.owner_id, team.co_owner_id}:
        raise HTTPException(status_code=403, detail="You do not own this team")

    await db.delete(claim)
    await db.commit()
    return {"status": "cancelled"}


@router.get("/priority")
async def get_priority(league_id: str, db: AsyncSession = Depends(get_db)):
    league = await _get_league(league_id, db)
    order = await _priority_order(league, league_id, db)

    result = await db.execute(select(Team).where(Team.league_id == league_id))
    team_map = {t.id: t.name for t in result.scalars().all()}
    return {"priority": [{"id": tid, "name": team_map.get(tid, "Unknown")} for tid in order]}


@router.post("/process")
async def process_waivers(
    league_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Commissioner-only. Walks pending claims in priority order, resolving conflicts."""
    league = await _get_league(league_id, db)
    require_commissioner(league, current_user)

    order = await _priority_order(league, league_id, db)

    teams_result = await db.execute(select(Team).where(Team.league_id == league_id))
    teams_by_id = {t.id: t for t in teams_result.scalars().all()}

    claims_result = await db.execute(
        select(Transaction).where(
            Transaction.league_id == league_id,
            Transaction.type == TransactionType.WAIVER,
            Transaction.status == TransactionStatus.PENDING,
        ).order_by(Transaction.processed_at.asc())
    )
    all_pending = claims_result.scalars().all()

    # Each team's single earliest pending claim is considered this run.
    earliest_claim_by_team: dict[str, Transaction] = {}
    for claim in all_pending:
        if claim.team_id not in earliest_claim_by_team:
            earliest_claim_by_team[claim.team_id] = claim

    granted_players: set[str] = set()
    granted: list[dict] = []
    denied: list[dict] = []
    new_priority = list(order)

    for team_id in order:
        claim = earliest_claim_by_team.get(team_id)
        if not claim:
            continue

        details = claim.details or {}
        add_id = details.get("add_player_id")
        drop_id = details.get("drop_player_id")
        team = teams_by_id.get(team_id)

        if not team or not add_id or add_id in granted_players:
            claim.status = TransactionStatus.DENIED
            denied.append({"team_id": team_id, "add_player_id": add_id})
            continue

        roster = set(team.roster or [])
        if drop_id and drop_id not in roster:
            claim.status = TransactionStatus.DENIED
            denied.append({"team_id": team_id, "add_player_id": add_id, "reason": "drop player no longer on roster"})
            continue

        if drop_id:
            roster.discard(drop_id)
        roster.add(add_id)
        team.roster = list(roster)

        claim.status = TransactionStatus.APPROVED
        claim.reviewed_by = current_user.id
        granted_players.add(add_id)
        granted.append({"team_id": team_id, "add_player_id": add_id, "drop_player_id": drop_id})

        # Move this team to the back of the priority queue
        new_priority.remove(team_id)
        new_priority.append(team_id)

    league.waiver_priority = new_priority
    await db.commit()

    return {
        "granted": granted,
        "denied": denied,
        "updated_priority": new_priority,
    }
