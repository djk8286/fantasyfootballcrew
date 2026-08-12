from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.core.database import get_db
from app.models.league import League
from app.models.team import Team
from app.models.player import Player
from app.models.transaction import Transaction, TransactionType, TransactionStatus
from app.models.user import User
from app.schemas.waiver import WaiverClaimCreate
from app.api.deps import get_current_user, require_commissioner
from app.services.draft_manager import get_player_rank_from_list, FANTASY_POSITIONS
from app.services.sleeper_sync import sleeper_avatar_url, effective_season_stats
from app.services.scoring_engine import calculate_player_score
from app.services.notification_service import notify_team_owners
from app.models.notification import NotificationType

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


async def _priority_order(league: League, league_id: str, db: AsyncSession) -> list[str]:
    """Current waiver priority, defaulting to team creation order if never set."""
    if league.waiver_priority:
        return league.waiver_priority
    result = await db.execute(
        select(Team).where(Team.league_id == league_id).order_by(Team.created_at)
    )
    return [t.id for t in result.scalars().all()]


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

    ranked_by_position: dict[str, list[tuple[int, Player]]] = {pos: [] for pos in POSITION_DISPLAY_ORDER}
    for p in free_agents:
        rank = get_player_rank_from_list(f"{p.first_name} {p.last_name}")
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
                "rank": rank if rank < 1000 else None,
                "pos_rank": i + 1,
                **_season_points_fields(p),
            }
            for i, (rank, p) in enumerate(entries[:limit_per_position])
        ]

    return result


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
    skipped: list[dict] = []
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

        # Atomic, conditional roster write -- same roster_version
        # compare-and-swap commissioner.review_trade uses, and for the same
        # reason: this endpoint's roster read (teams_by_id, above) and this
        # write are two separate points in time with no lock between them.
        # Confirmed locally: a trade approved for this team while waivers
        # were processing landed cleanly (status=="approved"), but the
        # trade's roster change was silently overwritten a moment later by
        # this write, which was still computing off the pre-trade roster --
        # the traded-away player stayed on the roster and the received
        # player never arrived, with no error anywhere. On a CAS miss here,
        # leave the claim PENDING (not denied) and report it skipped -- the
        # next "Process Waivers" run picks it back up with a fresh read,
        # rather than failing the whole batch over one contested team.
        cas_result = await db.execute(
            update(Team)
            .where(Team.id == team.id, Team.roster_version == team.roster_version)
            .values(roster=list(roster), roster_version=Team.roster_version + 1)
        )
        if cas_result.rowcount == 0:
            skipped.append({
                "team_id": team_id, "add_player_id": add_id,
                "reason": "roster changed concurrently (e.g. a trade was just approved) -- will retry on next processing run",
            })
            continue

        claim.status = TransactionStatus.APPROVED
        claim.reviewed_by = current_user.id
        granted_players.add(add_id)
        granted.append({"team_id": team_id, "add_player_id": add_id, "drop_player_id": drop_id})

        # Move this team to the back of the priority queue
        new_priority.remove(team_id)
        new_priority.append(team_id)

    league.waiver_priority = new_priority

    # Notify affected teams -- granted/denied are final outcomes worth
    # telling someone about; skipped isn't (it just means "will retry
    # next run", not resolved yet). One batched player-name lookup rather
    # than a query per notification.
    waiver_link = f"/leagues/{league_id}/waivers"
    notify_player_ids = {e["add_player_id"] for e in granted + denied if e.get("add_player_id")}
    player_names: dict[str, str] = {}
    if notify_player_ids:
        presult = await db.execute(select(Player).where(Player.id.in_(notify_player_ids)))
        player_names = {p.id: f"{p.first_name} {p.last_name}" for p in presult.scalars().all()}

    for entry in granted:
        team = teams_by_id.get(entry["team_id"])
        if team:
            pname = player_names.get(entry["add_player_id"], "a player")
            await notify_team_owners(db, team, NotificationType.WAIVER_APPROVED,
                                      f"Your waiver claim for {pname} was approved.", league_id, waiver_link)
    for entry in denied:
        team = teams_by_id.get(entry["team_id"])
        if team and entry.get("add_player_id"):
            pname = player_names.get(entry["add_player_id"], "a player")
            await notify_team_owners(db, team, NotificationType.WAIVER_DENIED,
                                      f"Your waiver claim for {pname} was denied.", league_id, waiver_link)

    await db.commit()

    return {
        "granted": granted,
        "skipped": skipped,
        "denied": denied,
        "updated_priority": new_priority,
    }
