from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.limiter import limiter
from app.models.league import League
from app.models.team import Team
from app.models.player import Player
from app.models.transaction import Transaction, TransactionType, TransactionStatus
from app.models.user import User
from app.schemas.waiver import WaiverClaimCreate
from app.api.deps import get_current_user, require_commissioner
from app.services.draft_manager import build_rank_by_id, get_rank_score, FANTASY_POSITIONS
from app.services.sleeper_sync import sleeper_avatar_url, effective_season_stats
from app.services.scoring_engine import calculate_player_score
from app.services.waiver_service import _priority_order, process_league_waivers
from app.services.best_ball_service import get_best_ball_settings, is_window_open

router = APIRouter(prefix="/leagues/{league_id}/waivers", tags=["waivers"])

# Display order for grouping the free-agent list, matching the frontend's
# PositionBadge.POSITION_ORDER convention.
POSITION_DISPLAY_ORDER = ["QB", "RB", "WR", "TE", "K", "DEF"]


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


@router.get("/free-agents")
async def list_free_agents(
    league_id: str,
    limit_per_position: int = 25,
    db: AsyncSession = Depends(get_db),
):
    """
    Best available (unrostered) free agents for this league, ranked by the
    same tier system the draft room uses, grouped by position and capped
    per position. Capped rather than returning every unrostered player
    because early in a season that's most of the player pool -- nobody
    browsing waivers needs the 300th-ranked free agent WR, and an
    unbounded list here would reintroduce the exact payload-bloat problem
    fixed in the draft room (see get_draft_state).
    """
    league = await _get_league(league_id, db)
    scoring_config = league.scoring_config or {}

    teams_result = await db.execute(select(Team).where(Team.league_id == league_id))
    teams = teams_result.scalars().all()
    rostered_ids = set()
    for t in teams:
        rostered_ids.update(t.roster or [])

    players_result = await db.execute(
        select(Player).where(
            Player.position.in_(FANTASY_POSITIONS),
            ~Player.id.in_(rostered_ids),
        )
    )
    free_agents = players_result.scalars().all()

    # Real, data-driven rank (see draft_manager.build_rank_by_id) --
    # replaces the old static tier/name-list lookup.
    rank_by_id = build_rank_by_id(free_agents, scoring_config)

    ranked_by_position: dict[str, list[tuple[int, Player]]] = {pos: [] for pos in POSITION_DISPLAY_ORDER}
    for p in free_agents:
        rank = get_rank_score(p, rank_by_id)
        ranked_by_position.setdefault(p.position, []).append((rank, p))

    def _season_points_fields(p: Player) -> dict:
        stats, year = effective_season_stats(p)
        return {
            "season_points": calculate_player_score(stats, scoring_config, p.position),
            "season_points_year": year,
        }

    result: dict[str, list[dict]] = {}
    for pos in POSITION_DISPLAY_ORDER:
        entries = sorted(ranked_by_position.get(pos, []), key=lambda e: e[0])
        result[pos] = [
            {
                "id": p.id,
                "first_name": p.first_name,
                "last_name": p.last_name,
                "position": p.position,
                "team": p.team,
                "avatar_url": sleeper_avatar_url(p.sleeper_id),
                "sleeper_id": p.sleeper_id,
                "injury_status": p.injury_status,
                "rank": rank,
                "pos_rank": i + 1,
                **_season_points_fields(p),
            }
            for i, (rank, p) in enumerate(entries[:limit_per_position])
        ]

    return result


@router.post("/claims", status_code=201)
@limiter.limit("30/hour")
async def submit_claim(
    request: Request,
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

    if team.eliminated_week is not None:
        raise HTTPException(status_code=400, detail="This team has been eliminated and can no longer make waiver claims")

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
@limiter.limit("30/hour")
async def cancel_claim(
    request: Request,
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
@limiter.limit("10/hour")
async def process_waivers(
    request: Request,
    league_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Commissioner-only. Walks pending claims in priority order, resolving
    conflicts -- core logic lives in waiver_service.process_league_waivers,
    shared with Best-Ball's auto-process-on-window-reopen scheduler pass."""
    league = await _get_league(league_id, db)
    require_commissioner(league, current_user)

    # Best-Ball (Phase 6): claim CREATION stays always-open, but GRANTING a
    # claim is gated by the management window exactly like trade approval --
    # manual processing included, not just the automatic scheduler pass.
    bb_settings = get_best_ball_settings(league)
    if bb_settings["enabled"] and not is_window_open(datetime.now(timezone.utc), bb_settings):
        raise HTTPException(
            status_code=400,
            detail="This league's management window is currently closed -- waiver processing resumes once it reopens.",
        )

    return await process_league_waivers(league, db, reviewed_by=current_user.id)
