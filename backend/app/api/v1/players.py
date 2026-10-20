from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_
from app.core.database import get_db
from app.models.player import Player
from app.models.league import League
from app.models.team import Team
from app.models.user import User
from app.api.deps import can_view_rosters, get_current_user_optional, require_league_read
from app.services import espn_news_service
from app.schemas.player import PlayerRead
from app.services.draft_manager import build_rank_by_id, get_rank_score
from app.services.sleeper_sync import sleeper_avatar_url, headline_stats, effective_season_stats
from app.services.scoring_engine import calculate_player_score, DEFAULT_SCORING
from app.services.roster_guard import rostered_player_ids

router = APIRouter(prefix="/players", tags=["players"])

SKILL_POSITIONS = {"QB", "RB", "WR", "TE"}

# sort_by values GET /players accepts, each with a fixed, obviously-correct
# direction (best/highest first) -- deliberately no separate asc/desc
# control, this is a casual sort dropdown, not a power-user filter builder.
SORT_VALUES = {"rank", "points", "yards", "touchdowns", "projected"}


def _yards(stats: dict | None) -> float:
    stats = stats or {}
    return (stats.get("rush_yd") or 0) + (stats.get("rec_yd") or 0) + (stats.get("pass_yd") or 0)


def _touchdowns(stats: dict | None) -> float:
    stats = stats or {}
    return (stats.get("rush_td") or 0) + (stats.get("rec_td") or 0) + (stats.get("pass_td") or 0)


def _sort_players(players: list[Player], sort_by: str, scoring_config: dict) -> list[Player]:
    """Sort an already-filtered player list in Python -- cheap pure
    arithmetic over already-fetched rows (same "not an I/O-bound N+1"
    reasoning draft_manager.build_rank_by_id documents), not a second
    query. scoring_config falls back to DEFAULT_SCORING (standard, not
    any one league's custom rules) when no league_id was supplied,
    matching build_rank_by_id's own existing convention elsewhere.

    Every case tie-breaks on the real search_rank-based rank
    (build_rank_by_id/get_rank_score), not just the primary key alone --
    without this, sort_by=projected in particular degraded to effectively
    arbitrary DB-insertion order: with no real Sleeper projections synced
    yet this preseason (confirmed directly against the live API -- see
    nfl_projections_service.py), virtually every player ties at the exact
    same 0, and Python's stable sort just preserves whatever order the
    query happened to return them in -- surfacing random deep-bench names
    above real stars, a real reported bug, not a hypothetical edge case."""
    config = scoring_config or DEFAULT_SCORING
    rank_by_id = build_rank_by_id(players, config)

    def _rank(p: Player) -> int:
        return get_rank_score(p, rank_by_id)

    if sort_by == "rank":
        return sorted(players, key=_rank)
    if sort_by == "points":
        return sorted(
            players,
            key=lambda p: (-calculate_player_score(p.last_season_stats or {}, config, p.position), _rank(p)),
        )
    if sort_by == "yards":
        return sorted(players, key=lambda p: (-_yards(p.last_season_stats), _rank(p)))
    if sort_by == "touchdowns":
        return sorted(players, key=lambda p: (-_touchdowns(p.last_season_stats), _rank(p)))
    if sort_by == "projected":
        # projected_stats is Sleeper's raw PER-GAME projection (see
        # Player model + nfl_projections_service.py) -- Sleeper exposes no
        # season-aggregate projection endpoint, so this is honestly a
        # per-game figure, not a fabricated season total. Players with no
        # synced projection yet (projected_stats is None) sort last, not
        # excluded -- still browsable/filterable by position, just with
        # no projection info to show.
        return sorted(
            players,
            key=lambda p: (-calculate_player_score(p.projected_stats or {}, config, p.position), _rank(p)),
        )
    return players


def _serialize_player(p: Player, scoring_config: dict | None = None) -> dict:
    # effective_season_stats picks current-season live data if the season
    # has actually started and synced anything yet, else falls back to the
    # archived last-season reference -- used for headline_stats/stats too
    # now (not just season_points below), so a player's compact stat line
    # isn't just blank for the entire preseason the way it used to be.
    stats, stats_year = effective_season_stats(p)
    data = {
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
        "headline_stats": headline_stats(p.position, stats),
        "stats": stats,
        # Raw last-season yards/touchdowns -- the "most important stats
        # from the previous year" sort_by=yards/touchdowns is built on
        # (see _sort_players above), surfaced here too so the UI can show
        # the actual number next to a player, not just use it to order them.
        "last_season_yards": _yards(p.last_season_stats),
        "last_season_touchdowns": _touchdowns(p.last_season_stats),
        # Sleeper's own synced per-GAME projection (Player.projected_stats,
        # see nfl_projections_service.py) -- there's no season-aggregate
        # projections endpoint, so this is honestly a per-game figure, not
        # a fabricated season total. None until a real sync has run for
        # this player. DEFAULT_SCORING fallback so it's still populated
        # for callers browsing without a specific league_id.
        "projected_points": (
            calculate_player_score(p.projected_stats, scoring_config or DEFAULT_SCORING, p.position)
            if p.projected_stats else None
        ),
    }
    # season_points is league-scoped (scoring rules differ per league), so
    # it's only computed when a scoring_config is supplied -- callers that
    # don't pass league_id skip this and get season_points: None.
    # season_points_year says which of current-season-live vs. archived
    # last-season `stats` actually backs it, so the frontend can label it
    # correctly instead of presenting a possibly-stale number as if live.
    if scoring_config is not None:
        data["season_points"] = calculate_player_score(stats, scoring_config, p.position)
        data["season_points_year"] = stats_year
    return data


async def _get_scoring_config(league_id: str | None, db: AsyncSession) -> dict | None:
    if not league_id:
        return None
    result = await db.execute(select(League).where(League.id == league_id))
    league = result.scalar_one_or_none()
    return (league.scoring_config or {}) if league else None


MAX_IDS = 400


@router.get("", response_model=list[PlayerRead])
async def list_players(
    position: str = None,
    team: str = None,
    search: str = None,
    limit: int = 100,
    league_id: str = None,
    sort_by: str = None,
    ids: str = None,
    available_in_league: str = None,
    db: AsyncSession = Depends(get_db),
    viewer: User | None = Depends(get_current_user_optional),
):
    """available_in_league: only free agents in that league -- anyone on
    any team's roster there is left out (roster_guard.rostered_player_ids,
    the same check waiver grants and draft picks use). The waiver page's
    "search free agents" box used to search every player, so rostered ones
    (Lamar Jackson on the searcher's own team, QA 2026-10-20) showed up as
    addable.

    ids: comma-separated player ids (max MAX_IDS) -- one batched lookup
    for pages that need names for a whole league's rosters (the trades
    page used to fire one GET per rostered player and showed raw UUIDs
    until every one returned; QA 2026-10-19 BUG I).

    sort_by: rank (real data-driven overall rank, replacing the old
    static tier list -- see draft_manager.build_rank_by_id), points (last
    season's fantasy points), yards / touchdowns (last season's raw
    totals), or projected (Sleeper's synced per-game projection). Each
    has a fixed best-first direction. Omitted: unsorted (DB order), same
    as before this param existed."""
    query = select(Player)
    if ids is not None:
        id_list = list(dict.fromkeys(i.strip() for i in ids.split(",") if i.strip()))
        if len(id_list) > MAX_IDS:
            raise HTTPException(status_code=422, detail=f"At most {MAX_IDS} ids per request")
        if not id_list:
            return []
        query = query.where(Player.id.in_(id_list))
        limit = len(id_list)
    if available_in_league:
        avail_league = await db.get(League, available_in_league)
        if avail_league is None:
            raise HTTPException(status_code=404, detail="League not found")
        # The free-agent pool is the inverse of the rosters: same rule.
        if not await can_view_rosters(avail_league, viewer, db):
            await require_league_read(avail_league, viewer, db)
        rostered = await rostered_player_ids(db, available_in_league)
        if rostered:
            query = query.where(~Player.id.in_(rostered))
    if position:
        query = query.where(Player.position == position.upper())
    if team:
        query = query.where(Player.team == team.upper())
    if search:
        # Multi-word queries ("Josh Allen") used to be matched as one
        # substring against first_name OR last_name separately, so a full
        # name never matched either column. Now every word must match the
        # first or last name. Also rank-order the results (search_rank,
        # nulls last) so "allen" surfaces Josh Allen ahead of long-retired
        # namesakes instead of arbitrary DB order cutting him off at limit.
        tokens = [t for t in search.split() if t]
        query = query.where(and_(*[
            or_(Player.first_name.ilike(f"%{t}%"), Player.last_name.ilike(f"%{t}%"))
            for t in tokens
        ]))
        query = query.order_by(Player.search_rank.is_(None), Player.search_rank)

    scoring_config = await _get_scoring_config(league_id, db)

    if sort_by in SORT_VALUES:
        # Sorting happens in Python over the full filtered set, then
        # trimmed to limit -- the DB can't rank by a computed fantasy
        # score, and this is cheap pure-Python arithmetic over already-
        # fetched rows (same reasoning build_rank_by_id documents), not an
        # I/O-bound N+1. No DB-level limit here on purpose: capping before
        # sorting would silently drop the actual best players whenever a
        # position/team/search filter narrows the set unevenly.
        result = await db.execute(query)
        players = list(result.scalars().all())
        players = _sort_players(players, sort_by, scoring_config)[:limit]
    else:
        result = await db.execute(query.limit(limit))
        players = result.scalars().all()

    return [_serialize_player(p, scoring_config) for p in players]


@router.get("/top-prospects")
async def top_prospects(limit: int = 100, db: AsyncSession = Depends(get_db)):
    """Top fantasy-relevant (skill-position) players by the same real,
    data-driven rank sort_by=rank on the main list_players endpoint uses
    (draft_manager.build_rank_by_id) -- kept as its own thin route since
    the dashboard and the players page's default view both already call
    it by name, but it's the same one ranking code path, not a second one."""
    result = await db.execute(select(Player).where(Player.position.in_(SKILL_POSITIONS)))
    players = list(result.scalars().all())
    rank_by_id = build_rank_by_id(players, DEFAULT_SCORING)
    players.sort(key=lambda p: get_rank_score(p, rank_by_id))

    return [
        {"rank": get_rank_score(p, rank_by_id), **_serialize_player(p)}
        for p in players[:limit]
    ]


@router.get("/{player_id}", response_model=PlayerRead)
async def get_player(player_id: str, league_id: str = None, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Player).where(Player.id == player_id))
    player = result.scalar_one_or_none()
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    scoring_config = await _get_scoring_config(league_id, db)
    return _serialize_player(player, scoring_config)


@router.get("/{player_id}/detail")
async def get_player_detail(
    player_id: str,
    league_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Everything the /players/[id] page shows, in one public read:
    the normal player payload (bio, Sleeper headshot, status, season
    stats), season + per-week fantasy points (league_id's scoring if
    given, else DEFAULT_SCORING), Sleeper's per-game projection if
    synced, and the last 30 days of real news (player_news). Only for a
    logged-in viewer, `rostered_by` lists which teams in the viewer's
    own leagues roster this player -- None (not []) when logged out, so
    the UI can tell "not logged in" from "nobody has him"."""
    result = await db.execute(select(Player).where(Player.id == player_id))
    player = result.scalar_one_or_none()
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    scoring_config = (await _get_scoring_config(league_id, db)) or DEFAULT_SCORING
    data = _serialize_player(player, scoring_config)
    data["number"] = player.number
    data["scoring"] = "league" if league_id else "default"

    weekly = []
    if player.stats_year and player.week_stats:
        for wk, wstats in sorted(player.week_stats.items(), key=lambda kv: int(kv[0])):
            if not wstats:
                continue
            weekly.append({
                "week": int(wk),
                "points": round(calculate_player_score(wstats, scoring_config, player.position), 2),
            })
    data["weekly_points"] = weekly
    data["weekly_points_year"] = player.stats_year if weekly else None
    data["projected_week"] = player.projected_week
    data["projected_year"] = player.projected_year

    recent = await espn_news_service.recent_news_for_players([player.id], db, days=30, limit=10)
    data["news"] = [espn_news_service.serialize(n, p) for n, p in recent]

    data["rostered_by"] = None
    if current_user is not None:
        my_teams = await db.execute(
            select(Team.league_id).where((Team.owner_id == current_user.id) | (Team.co_owner_id == current_user.id))
        )
        league_ids = {lid for (lid,) in my_teams.all()}
        # Commissioner / co-commissioner leagues count too (co_commissioner_ids
        # is a JSON list, so that membership check happens in Python).
        for lid, commish_id, co_ids in (await db.execute(
            select(League.id, League.commissioner_id, League.co_commissioner_ids)
        )).all():
            if commish_id == current_user.id or current_user.id in (co_ids or []):
                league_ids.add(lid)
        rostered = []
        if league_ids:
            rows = await db.execute(
                select(Team, League.name, League.created_at).join(League, League.id == Team.league_id).where(
                    Team.league_id.in_(league_ids), League.is_mock == False  # noqa: E712
                )
            )
            for team, league_name, league_created_at in rows.all():
                if player.id in (team.roster or []):
                    rostered.append({
                        "team_id": team.id, "team_name": team.name,
                        "league_id": team.league_id, "league_name": league_name,
                        "league_created_at": league_created_at,
                        "is_mine": current_user.id in {team.owner_id, team.co_owner_id},
                    })
        data["rostered_by"] = rostered
    return data
