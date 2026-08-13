import copy
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, asc, desc
from app.core.database import get_db
from app.models.league import League, LeagueVisibility, LeagueType
from app.models.team import Team
from app.models.user import User
from app.schemas.league import LeagueCreate, LeagueRead, LeagueUpdate
from app.services.scoring_engine import DEFAULT_SCORING, DEFAULT_ROSTER_SLOTS
from app.services.playoff_service import DEFAULT_PLAYOFF_SETTINGS, get_playoff_settings
from app.models.league_invite import LeagueInvite, InviteStatus
from app.models.league_join_request import LeagueJoinRequest, JoinRequestStatus
from app.api.deps import get_current_user, get_current_user_optional, require_commissioner, user_can_join_league
from pydantic import BaseModel

router = APIRouter(prefix="/leagues", tags=["leagues"])


class ScoringConfigUpdate(BaseModel):
    scoring_config: dict


class CommissionerUpdate(BaseModel):
    action: str  # "add_co_commish", "remove_co_commish", "transfer"
    user_id: str


@router.post("", response_model=LeagueRead, status_code=status.HTTP_201_CREATED)
async def create_league(
    league_data: LeagueCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # New leagues default to standard PPR scoring, not an empty config.
    # standings_service.calculate_week reads league.scoring_config directly
    # (no defaults merge -- that merge only happens in the GET /scoring
    # display endpoint), so a league whose commissioner never visits the
    # scoring settings page would otherwise score every player 0, all
    # season, with no error anywhere. Deep copy, not a shared reference --
    # see the DEFAULT_SCORING mutation bug fixed elsewhere in this file.
    league = League(
        name=league_data.name,
        description=league_data.description,
        commissioner_id=current_user.id,
        league_type=league_data.league_type,
        scoring_config=league_data.scoring_config or copy.deepcopy(DEFAULT_SCORING),
        roster_slots=copy.deepcopy(DEFAULT_ROSTER_SLOTS),
        max_teams=league_data.max_teams,
        draft_type=league_data.draft_type,
        co_commissioner_ids=[],
        visibility=league_data.visibility,
    )
    db.add(league)
    await db.commit()
    await db.refresh(league)
    return league


_VALID_SORTS = {"newest", "open_spots", "name", "size"}


@router.get("", response_model=list[LeagueRead])
async def list_leagues(
    mine: bool = False,
    visibility: LeagueVisibility | None = None,
    league_type: LeagueType | None = None,
    open_only: bool = False,
    wanted_board_only: bool = False,
    sort: str = "newest",
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    if sort not in _VALID_SORTS:
        raise HTTPException(status_code=422, detail=f"sort must be one of {sorted(_VALID_SORTS)}")

    query = select(
        League,
        func.count(Team.id).label("team_count")
    ).outerjoin(Team, Team.league_id == League.id).where(League.is_mock == False)  # noqa: E712

    if mine:
        if not current_user:
            raise HTTPException(status_code=401, detail="Not authenticated")
        my_league_ids = select(Team.league_id).where(
            or_(Team.owner_id == current_user.id, Team.co_owner_id == current_user.id)
        )
        query = query.where(
            or_(League.commissioner_id == current_user.id, League.id.in_(my_league_ids))
        )
    else:
        # The actual privacy gate -- previously every league was 100%
        # publicly listable regardless of any setting, since visibility
        # didn't exist. A user's OWN leagues (including Private ones they
        # belong to) still show via the `mine` branch above; this only
        # restricts the general/discovery listing.
        query = query.where(League.visibility != LeagueVisibility.PRIVATE)

    if wanted_board_only:
        # Overrides/ignores a conflicting visibility=private param --
        # the Wanted Board is never allowed to surface a Private league
        # regardless of what the caller asked for.
        query = query.where(League.visibility != LeagueVisibility.PRIVATE, League.wanted_board_hidden == False)  # noqa: E712
    elif visibility is not None:
        query = query.where(League.visibility == visibility)

    if league_type is not None:
        query = query.where(League.league_type == league_type)

    query = query.group_by(League.id)

    # team_count is the aggregate from the group_by above -- needs HAVING,
    # not WHERE, which can't reference an aggregated column.
    if open_only or wanted_board_only:
        query = query.having(func.count(Team.id) < League.max_teams)

    if sort == "newest":
        query = query.order_by(desc(League.created_at))
    elif sort == "open_spots":
        query = query.order_by(desc(League.max_teams - func.count(Team.id)))
    elif sort == "name":
        query = query.order_by(asc(League.name))
    elif sort == "size":
        query = query.order_by(asc(League.max_teams))

    result = await db.execute(query)
    rows = result.all()
    leagues = []
    for league, team_count in rows:
        league_dict = LeagueRead.model_validate(league)
        league_dict.team_count = team_count
        leagues.append(league_dict)
    return leagues


# ─── Scoring Config (must be BEFORE /{league_id} to avoid greedy param) ─


@router.get("/{league_id}/scoring")
async def get_league_scoring(league_id: str, db: AsyncSession = Depends(get_db)):
    """Get the scoring config for a league, or return defaults."""
    result = await db.execute(select(League).where(League.id == league_id))
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    config = league.scoring_config if league.scoring_config else {}
    # Merge with defaults so missing keys are filled in. Must be a DEEP copy:
    # {**DEFAULT_SCORING} only copies the outer dict, so merged["passing"] was
    # the *same object* as DEFAULT_SCORING["passing"], and merged[category]
    # .update(rules) below mutated that shared global in place -- one league
    # customizing its scoring silently corrupted the "defaults" template
    # served to every other league for the rest of the process's uptime.
    merged = copy.deepcopy(DEFAULT_SCORING)
    for category, rules in config.items():
        if isinstance(rules, dict) and category in merged:
            merged[category].update(rules)
        else:
            merged[category] = rules
    return merged


@router.put("/{league_id}/scoring")
async def update_league_scoring(
    league_id: str,
    data: ScoringConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update the scoring config for a league."""
    result = await db.execute(select(League).where(League.id == league_id))
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    require_commissioner(league, current_user)
    league.scoring_config = data.scoring_config
    await db.commit()
    return {"status": "ok", "scoring_config": league.scoring_config}


@router.get("/{league_id}/roster-slots")
async def get_league_roster_slots(league_id: str, db: AsyncSession = Depends(get_db)):
    """Get the starting-lineup slot counts for a league, or defaults.
    Same defaults-merge shape as GET .../scoring above, same reasoning:
    a league that never visited this settings page (or was created before
    roster_slots existed) should still get a complete, usable config back,
    not a partial one the caller has to guess how to fill in."""
    result = await db.execute(select(League).where(League.id == league_id))
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    merged = dict(DEFAULT_ROSTER_SLOTS)
    merged.update(league.roster_slots or {})
    return merged


class RosterSlotsUpdate(BaseModel):
    roster_slots: dict


@router.put("/{league_id}/roster-slots")
async def update_league_roster_slots(
    league_id: str,
    data: RosterSlotsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update the starting-lineup slot counts for a league."""
    result = await db.execute(select(League).where(League.id == league_id))
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    require_commissioner(league, current_user)
    for key, value in data.roster_slots.items():
        if not isinstance(value, int) or value < 0:
            raise HTTPException(status_code=422, detail=f"roster_slots['{key}'] must be a non-negative integer")
    league.roster_slots = data.roster_slots
    await db.commit()
    return {"status": "ok", "roster_slots": league.roster_slots}


@router.get("/{league_id}/playoff-settings")
async def get_league_playoff_settings(league_id: str, db: AsyncSession = Depends(get_db)):
    """Get the playoff config for a league, or defaults (disabled)."""
    result = await db.execute(select(League).where(League.id == league_id))
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    return get_playoff_settings(league)


class PlayoffSettingsUpdate(BaseModel):
    playoff_settings: dict


_VALID_SEEDING_METHODS = {"wins", "points"}
_VALID_CONFERENCE_MODES = {"combined", "separate"}


@router.put("/{league_id}/playoff-settings")
async def update_league_playoff_settings(
    league_id: str,
    data: PlayoffSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update the playoff config for a league."""
    result = await db.execute(select(League).where(League.id == league_id))
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    require_commissioner(league, current_user)

    merged = dict(DEFAULT_PLAYOFF_SETTINGS)
    merged.update(data.playoff_settings)

    if not isinstance(merged.get("enabled"), bool):
        raise HTTPException(status_code=422, detail="playoff_settings.enabled must be a boolean")
    if not isinstance(merged.get("regular_season_weeks"), int) or not (1 <= merged["regular_season_weeks"] <= 17):
        raise HTTPException(status_code=422, detail="playoff_settings.regular_season_weeks must be an integer between 1 and 17")
    if not isinstance(merged.get("num_teams"), int) or merged["num_teams"] < 2:
        raise HTTPException(status_code=422, detail="playoff_settings.num_teams must be an integer of at least 2")
    if merged.get("seeding_method") not in _VALID_SEEDING_METHODS:
        raise HTTPException(status_code=422, detail=f"playoff_settings.seeding_method must be one of {sorted(_VALID_SEEDING_METHODS)}")
    if merged.get("conference_bracket_mode") not in _VALID_CONFERENCE_MODES:
        raise HTTPException(status_code=422, detail=f"playoff_settings.conference_bracket_mode must be one of {sorted(_VALID_CONFERENCE_MODES)}")

    league.playoff_settings = merged
    await db.commit()
    return {"status": "ok", "playoff_settings": league.playoff_settings}


@router.patch("/{league_id}", response_model=LeagueRead)
async def update_league(
    league_id: str,
    update_data: LeagueUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update league settings (commissioner only)."""
    result = await db.execute(
        select(
            League,
            func.count(Team.id).label("team_count")
        ).outerjoin(Team, Team.league_id == League.id)
        .where(League.id == league_id)
        .group_by(League.id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="League not found")
    league, team_count = row
    require_commissioner(league, current_user)

    if update_data.name is not None:
        league.name = update_data.name
    if update_data.description is not None:
        league.description = update_data.description
    if update_data.max_teams is not None:
        if update_data.max_teams < team_count:
            raise HTTPException(status_code=400, detail=f"Cannot reduce max teams below current count ({team_count})")
        league.max_teams = update_data.max_teams
    if update_data.draft_type is not None:
        league.draft_type = update_data.draft_type
    if update_data.visibility is not None:
        league.visibility = update_data.visibility
    if update_data.wanted_board_hidden is not None:
        league.wanted_board_hidden = update_data.wanted_board_hidden

    await db.commit()
    await db.refresh(league)
    league_dict = LeagueRead.model_validate(league)
    league_dict.team_count = team_count
    return league_dict


@router.post("/{league_id}/commissioner")
async def manage_commissioners(
    league_id: str,
    req: CommissionerUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manage commissioner rights: add/remove co-commissioners, transfer ownership. Owner only."""
    result = await db.execute(select(League).where(League.id == league_id))
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    if current_user.id != league.commissioner_id:
        raise HTTPException(status_code=403, detail="Only the league owner can manage commissioner rights")

    # Verify user exists
    user_result = await db.execute(select(User).where(User.id == req.user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Ensure co_commissioner_ids is initialized
    if league.co_commissioner_ids is None:
        league.co_commissioner_ids = []

    if req.action == "add_co_commish":
        if req.user_id == league.commissioner_id:
            raise HTTPException(status_code=400, detail="Commissioner is already the league owner")
        if req.user_id in league.co_commissioner_ids:
            raise HTTPException(status_code=400, detail="User is already a co-commissioner")
        league.co_commissioner_ids.append(req.user_id)

    elif req.action == "remove_co_commish":
        if req.user_id not in league.co_commissioner_ids:
            raise HTTPException(status_code=400, detail="User is not a co-commissioner")
        league.co_commissioner_ids.remove(req.user_id)

    elif req.action == "transfer":
        if req.user_id == league.commissioner_id:
            raise HTTPException(status_code=400, detail="Already the commissioner")
        # Make target the commissioner, current becomes co-commissioner
        old_commish = league.commissioner_id
        league.commissioner_id = req.user_id
        if old_commish not in league.co_commissioner_ids:
            league.co_commissioner_ids.append(old_commish)

    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {req.action}")

    await db.commit()
    await db.refresh(league)
    return {
        "commissioner_id": league.commissioner_id,
        "co_commissioner_ids": league.co_commissioner_ids or [],
    }


async def _compute_viewer_join_status(db: AsyncSession, league: League, user: User) -> str:
    """One of "commissioner"|"member"|"eligible"|"requested"|"invited"|
    "blocked" -- drives the league detail page's claim-button region
    (Step 7). Priority order matters: a commissioner who also happens to
    have a stray pending join request should still see "commissioner",
    not "requested".
    """
    if user.id in {league.commissioner_id, *(league.co_commissioner_ids or [])}:
        return "commissioner"

    member_result = await db.execute(
        select(Team.id).where(
            Team.league_id == league.id,
            (Team.owner_id == user.id) | (Team.co_owner_id == user.id),
        )
    )
    if member_result.first() is not None:
        return "member"

    # Covers OPEN outright, plus INVITE_ONLY/PRIVATE with an accepted
    # invite or approved join request already on file -- same check
    # claim_team/claim_co_owner enforce (Step 6), so this can't drift out
    # of sync with what actually gets a claim through.
    if await user_can_join_league(db, league, user):
        return "eligible"

    pending_request = await db.execute(
        select(LeagueJoinRequest.id).where(
            LeagueJoinRequest.league_id == league.id,
            LeagueJoinRequest.requested_by_user_id == user.id,
            LeagueJoinRequest.status == JoinRequestStatus.PENDING,
        )
    )
    if pending_request.first() is not None:
        return "requested"

    # Matched by email, not user id -- an invite is sent before the
    # recipient necessarily has an account, so there's no user id to
    # match against yet. Informational only (the league page can point
    # them at their email); accepting still requires the actual token
    # link, per LeagueInvite's token-possession trust model.
    pending_invite = await db.execute(
        select(LeagueInvite.id).where(
            LeagueInvite.league_id == league.id,
            LeagueInvite.invited_email == user.email,
            LeagueInvite.status == InviteStatus.PENDING,
        )
    )
    if pending_invite.first() is not None:
        return "invited"

    return "blocked"


@router.get("/{league_id}", response_model=LeagueRead)
async def get_league(
    league_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    result = await db.execute(
        select(
            League,
            func.count(Team.id).label("team_count")
        ).outerjoin(Team, Team.league_id == League.id)
        .where(League.id == league_id)
        .group_by(League.id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="League not found")
    league, team_count = row
    league_dict = LeagueRead.model_validate(league)
    league_dict.team_count = team_count
    if current_user is not None:
        league_dict.viewer_join_status = await _compute_viewer_join_status(db, league, current_user)
    return league_dict
