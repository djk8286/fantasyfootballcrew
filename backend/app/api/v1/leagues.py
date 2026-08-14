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
from app.services.standings_service import DEFAULT_RIVALRY_WEEK_SETTINGS, get_rivalry_week_settings
from app.services.salary_cap_service import DEFAULT_SALARY_CAP_SETTINGS, get_salary_cap_settings, compute_waiver_salary
from app.services.best_ball_service import DEFAULT_BEST_BALL_SETTINGS, get_best_ball_settings, is_window_open, describe_window
from app.models.player import Player
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
    # Dual-Squad (Phase 7): teams only ever come in pairs, so max_teams
    # must be even and at least 4 (2 pairs). Defensive -- the create-
    # league frontend's slider already forces even/>=4 for every league
    # type, but the API can be hit directly.
    if league_data.league_type == LeagueType.DUAL_SQUAD and (league_data.max_teams < 4 or league_data.max_teams % 2 != 0):
        raise HTTPException(status_code=422, detail="Dual-Squad leagues need an even number of teams, at least 4 (2 pairs)")

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


@router.get("/{league_id}/rivalry-week-settings")
async def get_league_rivalry_week_settings(league_id: str, db: AsyncSession = Depends(get_db)):
    """Get the Rivalry Week config for a league, or defaults (disabled).
    Ungated -- safe to read regardless of league_type, same as
    GET playoff-settings."""
    result = await db.execute(select(League).where(League.id == league_id))
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    return get_rivalry_week_settings(league)


class RivalryWeekSettingsUpdate(BaseModel):
    rivalry_week_settings: dict


@router.put("/{league_id}/rivalry-week-settings")
async def update_league_rivalry_week_settings(
    league_id: str,
    data: RivalryWeekSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update the Rivalry Week config for a league (commissioner only).
    Only meaningful for CONFERENCE leagues (see calculate_week's gate) --
    unlike conference naming, enabling this on a non-conference league
    would look like it succeeded while silently never paying out, so
    it's rejected outright rather than a harmless no-op."""
    result = await db.execute(select(League).where(League.id == league_id))
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    require_commissioner(league, current_user)

    merged = dict(DEFAULT_RIVALRY_WEEK_SETTINGS)
    merged.update(data.rivalry_week_settings)

    if not isinstance(merged.get("enabled"), bool):
        raise HTTPException(status_code=422, detail="rivalry_week_settings.enabled must be a boolean")
    if merged["enabled"]:
        if league.league_type != LeagueType.CONFERENCE:
            raise HTTPException(status_code=400, detail="Rivalry Week can only be enabled for Conference leagues")
        if not isinstance(merged.get("week"), int) or isinstance(merged.get("week"), bool) or merged["week"] < 1:
            raise HTTPException(status_code=422, detail="rivalry_week_settings.week must be a positive integer when enabled")
    if not isinstance(merged.get("bonus_value"), (int, float)) or isinstance(merged.get("bonus_value"), bool) or merged["bonus_value"] < 0:
        raise HTTPException(status_code=422, detail="rivalry_week_settings.bonus_value must be a non-negative number")

    league.rivalry_week_settings = merged
    await db.commit()
    return {"status": "ok", "rivalry_week_settings": league.rivalry_week_settings}


@router.get("/{league_id}/salary-cap-settings")
async def get_league_salary_cap_settings(league_id: str, db: AsyncSession = Depends(get_db)):
    """Get the Salary-Cap config for a league, or defaults (disabled).
    Ungated -- same house style as GET playoff-settings/rivalry-week-settings."""
    result = await db.execute(select(League).where(League.id == league_id))
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    return get_salary_cap_settings(league)


class SalaryCapSettingsUpdate(BaseModel):
    salary_cap_settings: dict


@router.put("/{league_id}/salary-cap-settings")
async def update_league_salary_cap_settings(
    league_id: str,
    data: SalaryCapSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update the Salary-Cap config for a league (commissioner only). A
    bolt-on flag for ANY league_type (not gated to a specific type, since
    cap enforcement is purely a roster-construction-time concern, unlike
    Rivalry Week's scoring-path gate)."""
    result = await db.execute(select(League).where(League.id == league_id))
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    require_commissioner(league, current_user)

    merged = dict(DEFAULT_SALARY_CAP_SETTINGS)
    merged.update(data.salary_cap_settings)

    def _is_number(v):
        return isinstance(v, (int, float)) and not isinstance(v, bool)

    def _is_int(v):
        return isinstance(v, int) and not isinstance(v, bool)

    if not isinstance(merged.get("enabled"), bool):
        raise HTTPException(status_code=422, detail="salary_cap_settings.enabled must be a boolean")
    if not _is_number(merged.get("cap_total")) or merged["cap_total"] <= 0:
        raise HTTPException(status_code=422, detail="salary_cap_settings.cap_total must be a positive number")
    if not _is_int(merged.get("max_roster_size")) or merged["max_roster_size"] < 1:
        raise HTTPException(status_code=422, detail="salary_cap_settings.max_roster_size must be a positive integer")
    if not _is_number(merged.get("top_salary")) or merged["top_salary"] < 0:
        raise HTTPException(status_code=422, detail="salary_cap_settings.top_salary must be a non-negative number")
    if not _is_number(merged.get("bottom_salary")) or merged["bottom_salary"] < 0:
        raise HTTPException(status_code=422, detail="salary_cap_settings.bottom_salary must be a non-negative number")
    if merged["top_salary"] < merged["bottom_salary"]:
        raise HTTPException(status_code=422, detail="salary_cap_settings.top_salary must be >= bottom_salary")
    if not _is_number(merged.get("waiver_salary_pct")) or merged["waiver_salary_pct"] < 0:
        raise HTTPException(status_code=422, detail="salary_cap_settings.waiver_salary_pct must be a non-negative number")
    if not _is_number(merged.get("dead_money_pct")) or not (0 <= merged["dead_money_pct"] <= 1):
        raise HTTPException(status_code=422, detail="salary_cap_settings.dead_money_pct must be between 0 and 1")
    if not _is_int(merged.get("default_contract_years")) or not (1 <= merged["default_contract_years"] <= 4):
        raise HTTPException(status_code=422, detail="salary_cap_settings.default_contract_years must be an integer 1-4")
    if not _is_int(merged.get("waiver_contract_years")) or not (1 <= merged["waiver_contract_years"] <= 4):
        raise HTTPException(status_code=422, detail="salary_cap_settings.waiver_contract_years must be an integer 1-4")

    league.salary_cap_settings = merged
    await db.commit()
    return {"status": "ok", "salary_cap_settings": league.salary_cap_settings}


@router.get("/{league_id}/salary-cap/preview-signing")
async def preview_salary_cap_signing(league_id: str, player_id: str, db: AsyncSession = Depends(get_db)):
    """Estimate what a free-agent/waiver signing WOULD cost, without
    creating a Contract -- lets the waivers page show a real number
    before a claim is submitted. Ungated, works even when the league's
    salary_cap_settings.enabled is False (a harmless preview either way)."""
    league_result = await db.execute(select(League).where(League.id == league_id))
    league = league_result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    player_result = await db.execute(select(Player).where(Player.id == player_id))
    player = player_result.scalar_one_or_none()
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    settings = get_salary_cap_settings(league)
    return {"player_id": player_id, "estimated_salary": compute_waiver_salary(player, settings)}


@router.get("/{league_id}/best-ball-settings")
async def get_league_best_ball_settings(league_id: str, db: AsyncSession = Depends(get_db)):
    """Get the Best-Ball config for a league, or defaults (disabled).
    Ungated -- same house style as GET playoff-settings/salary-cap-settings."""
    result = await db.execute(select(League).where(League.id == league_id))
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    return get_best_ball_settings(league)


class BestBallSettingsUpdate(BaseModel):
    best_ball_settings: dict


@router.put("/{league_id}/best-ball-settings")
async def update_league_best_ball_settings(
    league_id: str,
    data: BestBallSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update the Best-Ball config for a league (commissioner only). A
    bolt-on flag for ANY league_type, mirroring salary-cap-settings
    exactly."""
    result = await db.execute(select(League).where(League.id == league_id))
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    require_commissioner(league, current_user)

    merged = dict(DEFAULT_BEST_BALL_SETTINGS)
    merged.update(data.best_ball_settings)

    def _is_int(v):
        return isinstance(v, int) and not isinstance(v, bool)

    if not isinstance(merged.get("enabled"), bool):
        raise HTTPException(status_code=422, detail="best_ball_settings.enabled must be a boolean")
    if not _is_int(merged.get("lock_weekday")) or not (0 <= merged["lock_weekday"] <= 6):
        raise HTTPException(status_code=422, detail="best_ball_settings.lock_weekday must be an integer 0-6")
    if not _is_int(merged.get("reopen_weekday")) or not (0 <= merged["reopen_weekday"] <= 6):
        raise HTTPException(status_code=422, detail="best_ball_settings.reopen_weekday must be an integer 0-6")
    if not _is_int(merged.get("lock_hour")) or not (0 <= merged["lock_hour"] <= 23):
        raise HTTPException(status_code=422, detail="best_ball_settings.lock_hour must be an integer 0-23")
    if not _is_int(merged.get("reopen_hour")) or not (0 <= merged["reopen_hour"] <= 23):
        raise HTTPException(status_code=422, detail="best_ball_settings.reopen_hour must be an integer 0-23")

    league.best_ball_settings = merged
    await db.commit()
    return {"status": "ok", "best_ball_settings": league.best_ball_settings}


@router.get("/{league_id}/management-window")
async def get_league_management_window(league_id: str, db: AsyncSession = Depends(get_db)):
    """Whether trade approvals / waiver processing are currently allowed
    for this league. Meaningless (always open) outside Best-Ball --
    ungated read, so the frontend can call it unconditionally without
    first checking whether best-ball is enabled."""
    result = await db.execute(select(League).where(League.id == league_id))
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    settings = get_best_ball_settings(league)
    if not settings["enabled"]:
        return {
            "enabled": False, "is_open": True,
            "next_transition_at": None, "next_transition_type": None,
            **{k: v for k, v in settings.items() if k != "enabled"},
        }
    from datetime import datetime, timezone
    description = describe_window(datetime.now(timezone.utc), settings)
    return {"enabled": True, **settings, **description}


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
        if league.league_type == LeagueType.DUAL_SQUAD and (update_data.max_teams < 4 or update_data.max_teams % 2 != 0):
            raise HTTPException(status_code=422, detail="Dual-Squad leagues need an even number of teams, at least 4 (2 pairs)")
        league.max_teams = update_data.max_teams
    if update_data.draft_type is not None:
        league.draft_type = update_data.draft_type
    if update_data.visibility is not None:
        league.visibility = update_data.visibility
    if update_data.wanted_board_hidden is not None:
        league.wanted_board_hidden = update_data.wanted_board_hidden
    if update_data.conference_a_name is not None:
        # Empty string clears it back to "not customized" (None), rather
        # than storing a literal blank -- matches how a cleared display
        # field should read as "use the default", not "named ''".
        league.conference_a_name = update_data.conference_a_name or None
    if update_data.conference_b_name is not None:
        league.conference_b_name = update_data.conference_b_name or None

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
