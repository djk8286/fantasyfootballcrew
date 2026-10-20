"""Read endpoints for the team page and league feeds:
GET /teams/{id}/roster and GET /leagues/{id}/activity."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    can_view_lineups,
    can_view_rosters,
    get_current_user,
    get_current_user_optional,
    require_commissioner,
    require_league_read,
)
from app.api.v1.lineups import (
    _current_lineup,
    _get_team_league_or_404,
    _player_states,
    _resolve_roster,
    _serialize_roster_player,
    load_week_games,
)
from app.core.database import get_db
from app.models.league import League
from app.models.team import Team
from app.models.user import User
from app.services.league_home_service import league_home
from app.services.lineup_slots import lineup_issues
from app.services.season_weeks import league_start_week
from app.services.team_activity_service import league_activity, team_record

router = APIRouter(tags=["team-hub"])


async def _usernames(ids: list[str | None], db: AsyncSession) -> dict[str, str]:
    ids = [i for i in ids if i]
    if not ids:
        return {}
    rows = await db.execute(select(User.id, User.username).where(User.id.in_(ids)))
    return {uid: name for uid, name in rows.all()}


@router.get("/teams/{team_id}/roster")
async def get_team_roster(
    team_id: str,
    week: int = Query(..., ge=1, le=18),
    year: int = Query(..., ge=2020, le=2030),
    db: AsyncSession = Depends(get_db),
    viewer: User | None = Depends(get_current_user_optional),
):
    """One call for the team page: the team with owner usernames, its
    record from standings (Team.points_for is never written), the league's
    first week, and the roster rows GET /lineup returns, each with the
    slot he fills this week ("BN" on the bench).

    Visibility (deps.can_view_rosters / can_view_lineups): PRIVATE league
    -> members only (401 guest, 403 non-member). Guests on other leagues
    get the roster without lineup data: slots, issues, has_lineup_set are
    null, and each row's slot and is_starter are null."""
    team, league = await _get_team_league_or_404(team_id, db)
    if not await can_view_rosters(league, viewer, db):
        await require_league_read(league, viewer, db)  # raises 401/403
    show_lineup = await can_view_lineups(league, viewer, db)
    teams = (await db.execute(select(Team).where(Team.league_id == league.id))).scalars().all()
    roster = await _resolve_roster(team, db)
    games = await load_week_games(year, week, db)
    current = await _current_lineup(team, league, roster, week, year, db)
    slot_of = {e["player_id"]: e["slot"] for e in current.slots if e.get("player_id")}
    scoring = league.scoring_config or {}
    names = await _usernames([team.owner_id, team.co_owner_id], db)

    rows = []
    for p in roster:
        row = _serialize_roster_player(p, p.id in slot_of, scoring, games, week, year)
        row["slot"] = slot_of.get(p.id, "BN") if show_lineup else None
        if not show_lineup:
            row["is_starter"] = None
        rows.append(row)

    return {
        "team": {
            "id": team.id,
            "name": team.name,
            "league_id": league.id,
            "avatar_url": team.avatar_url,
            "is_cpu": team.is_cpu,
            "owner_id": team.owner_id,
            "co_owner_id": team.co_owner_id,
            "owner_username": names.get(team.owner_id or ""),
            "co_owner_username": names.get(team.co_owner_id or ""),
        },
        "record": await team_record(league, team, list(teams), db),
        "week": week,
        "year": year,
        "league_start_week": await league_start_week(league.id, year, db),
        "lineup_visible": show_lineup,
        "has_lineup_set": current.has_lineup_set if show_lineup else None,
        "slots": current.slots if show_lineup else None,
        "issues": lineup_issues(current.slots, _player_states(roster, games), current.unplaced) if show_lineup else None,
        "roster": rows,
    }


@router.get("/leagues/{league_id}/activity")
async def get_league_activity(
    league_id: str,
    team_id: str | None = None,
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    viewer: User | None = Depends(get_current_user_optional),
):
    """League feed, newest first: finished trades, waiver adds, the draft
    and weekly results, with team and player names resolved. team_id
    narrows it to one team. Pending and declined moves only appear for the
    managers of a team involved; cancel is set on the viewer's own pending
    ones (POST .../trades/{id}/cancel or DELETE .../waivers/claims/{id})."""
    league = (await db.execute(select(League).where(League.id == league_id))).scalar_one_or_none()
    if league is None:
        raise HTTPException(status_code=404, detail="League not found")
    teams = (await db.execute(select(Team).where(Team.league_id == league_id))).scalars().all()
    if team_id and team_id not in {t.id for t in teams}:
        raise HTTPException(status_code=404, detail="Team not found in this league")
    items = await league_activity(league, list(teams), db, viewer_id=viewer.id if viewer else None,
                                  team_id=team_id, limit=limit)
    return {"league_id": league_id, "items": items}


@router.get("/leagues/{league_id}/home")
async def get_league_home(
    league_id: str,
    week: int = Query(..., ge=1, le=18),
    year: int = Query(..., ge=2020, le=2030),
    db: AsyncSession = Depends(get_db),
    viewer: User | None = Depends(get_current_user_optional),
):
    """The league home page in one call.

    my_matchup: the viewer's game this week, both sides with score (null
    before kickoff) and projected (null without projections).
    top_issue / issue_count: what's wrong with the viewer's lineup now.
    last_week: the viewer's last finished game, with optimal_score and
    bench_points (best legal lineup from that week's roster minus what
    scored). scoreboard: every game this week, the viewer's marked mine.
    standings: compact rows with rank and streak. activity: the 8 newest
    feed items. Viewer-specific fields are null for guests."""
    league = (await db.execute(select(League).where(League.id == league_id))).scalar_one_or_none()
    if league is None:
        raise HTTPException(status_code=404, detail="League not found")
    if not await can_view_rosters(league, viewer, db):
        await require_league_read(league, viewer, db)  # raises 401/403
    return await league_home(league, week, year, db, viewer.id if viewer else None,
                             show_projections=await can_view_lineups(league, viewer, db))


@router.get("/leagues/{league_id}/members")
async def get_league_members(
    league_id: str,
    db: AsyncSession = Depends(get_db),
    viewer: User = Depends(get_current_user),
):
    """Who runs the league and who manages each team, by username.
    Commissioners and co-commissioners only. `viewer_is_owner` is true
    for the commissioner, who alone can add or remove co-commissioners."""
    league = (await db.execute(select(League).where(League.id == league_id))).scalar_one_or_none()
    if league is None:
        raise HTTPException(status_code=404, detail="League not found")
    require_commissioner(league, viewer)
    teams = list((await db.execute(select(Team).where(Team.league_id == league_id).order_by(Team.name))).scalars().all())
    co_ids = list(league.co_commissioner_ids or [])
    ids = {league.commissioner_id, *co_ids} | {t.owner_id for t in teams if t.owner_id} | {t.co_owner_id for t in teams if t.co_owner_id}
    users = {u.id: u for u in (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all()} if ids else {}

    def person(uid: str | None) -> dict | None:
        if not uid or uid not in users:
            return None
        u = users[uid]
        return {"user_id": u.id, "username": u.username or u.email.split("@")[0]}

    team_of: dict[str, list[str]] = {}
    for t in teams:
        for uid in (t.owner_id, t.co_owner_id):
            if uid in users:
                team_of.setdefault(uid, []).append(t.name)
    return {
        "viewer_is_owner": viewer.id == league.commissioner_id,
        "commissioner": person(league.commissioner_id),
        "co_commissioners": [p for p in (person(c) for c in co_ids) if p],
        "teams": [{
            "team_id": t.id,
            "name": t.name,
            "owner": person(t.owner_id),
            "co_owner": person(t.co_owner_id),
        } for t in teams],
        "members": sorted(
            ({**person(uid), "teams": names} for uid, names in team_of.items()),
            key=lambda m: m["username"].lower(),
        ),
    }
