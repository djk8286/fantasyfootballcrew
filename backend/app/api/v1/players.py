from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from app.core.database import get_db
from app.models.player import Player
from app.schemas.player import PlayerRead
from app.services.draft_manager import get_tier_names, build_sequential_ranking
from app.services.sleeper_sync import sleeper_avatar_url, headline_stats

router = APIRouter(prefix="/players", tags=["players"])

SKILL_POSITIONS = {"QB", "RB", "WR", "TE"}


def _serialize_player(p: Player) -> dict:
    return {
        "id": p.id,
        "sleeper_id": p.sleeper_id,
        "first_name": p.first_name,
        "last_name": p.last_name,
        "position": p.position,
        "team": p.team,
        "bye_week": p.bye_week,
        "injury_status": p.injury_status,
        "fantasy_positions": p.fantasy_positions,
        "age": p.age,
        "avatar_url": sleeper_avatar_url(p.sleeper_id),
        "headline_stats": headline_stats(p.position, p.stats),
        "stats": p.stats,
    }


@router.get("", response_model=list[PlayerRead])
async def list_players(
    position: str = None,
    team: str = None,
    search: str = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    query = select(Player)
    if position:
        query = query.where(Player.position == position.upper())
    if team:
        query = query.where(Player.team == team.upper())
    if search:
        query = query.where(
            or_(
                Player.first_name.ilike(f"%{search}%"),
                Player.last_name.ilike(f"%{search}%"),
            )
        )
    query = query.limit(limit)
    result = await db.execute(query)
    players = result.scalars().all()
    return [_serialize_player(p) for p in players]


@router.get("/top-prospects")
async def top_prospects(limit: int = 100, db: AsyncSession = Depends(get_db)):
    """Top fantasy-relevant players by the same tiered ranking the draft room's
    mock-AI uses (backend/app/services/draft_manager.py), cross-referenced
    against real synced player records."""
    sequential_rankings = build_sequential_ranking(get_tier_names())

    result = await db.execute(select(Player).where(Player.position.in_(SKILL_POSITIONS)))
    all_players = result.scalars().all()
    by_name = [(f"{p.first_name} {p.last_name}".lower(), p) for p in all_players]

    matched: list[dict] = []
    seen_ids: set[str] = set()
    for rank, ranked_name in sequential_rankings:
        if len(matched) >= limit:
            break
        name_lower = ranked_name.lower()
        for full_name, player in by_name:
            if player.id in seen_ids:
                continue
            if name_lower in full_name or full_name in name_lower:
                seen_ids.add(player.id)
                matched.append({
                    "rank": rank,
                    **_serialize_player(player),
                })
                break

    return matched


@router.get("/{player_id}", response_model=PlayerRead)
async def get_player(player_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Player).where(Player.id == player_id))
    player = result.scalar_one_or_none()
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    return _serialize_player(player)
