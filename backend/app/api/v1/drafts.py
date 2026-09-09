from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.core.database import get_db
from app.core.limiter import limiter
from app.services.draft_manager import (
    create_draft,
    start_draft,
    make_pick,
    get_draft_state,
    run_mock_draft,
    get_ai_mock_pick,
    quickstart_mock_draft,
)
from app.models.draft import Draft, DraftPick, DraftRunStatus
from app.models.league import League
from app.models.team import Team
from app.models.user import User
from app.schemas.draft import DraftCreate, DraftRead, DraftPickCreate, DraftPickRead, DraftState, MockDraftQuickstart
from app.api.deps import (
    get_current_user,
    require_commissioner,
    require_team_or_league_access,
    require_league_participant,
)
from pydantic import BaseModel


class TimerUpdate(BaseModel):
    timer_seconds: int


class MockDraftRequest(BaseModel):
    """Request to run a (potentially hybrid) mock draft.
    Teams in skip_team_ids will NOT get auto-picked — they stay open for manual drafting."""
    skip_team_ids: list[str] = []

router = APIRouter(prefix="/drafts", tags=["drafts"])


# Every route below except the two GETs mutates draft/roster state, and
# until this pass, none of them (besides /mock/quickstart) checked who was
# calling at all -- api_make_pick took team_id straight from the request
# body with nothing stopping any caller from picking for a team that
# wasn't theirs, in a league they had no relationship to. See the helpers
# below and app/api/deps.py's require_commissioner/require_team_or_league_
# access/require_league_participant for what's actually enforced now.


async def _get_league_or_404(league_id: str, db: AsyncSession) -> League:
    result = await db.execute(select(League).where(League.id == league_id))
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    return league


async def _get_draft_and_league_or_404(draft_id: str, db: AsyncSession) -> tuple[Draft, League]:
    result = await db.execute(select(Draft).where(Draft.id == draft_id))
    draft = result.scalar_one_or_none()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    league = await _get_league_or_404(draft.league_id, db)
    return draft, league


async def _require_pick_access(team_id: str, league: League, current_user: User, db: AsyncSession) -> Team:
    """Who's allowed to make/trigger a pick for `team_id`, and the Team
    itself (callers need it either way, so return it rather than re-query).

    CPU teams have no human on the other end to protect, so any real
    participant in the league (any team owner/co-owner, or the
    commissioner) can nudge one forward -- this is what the frontend
    already relies on: any connected viewer's browser fires auto-pick
    when a CPU team is on the clock, not just the commissioner's. Real,
    human-owned teams are restricted to that team's own owner/co-owner or
    the commissioner (e.g. to unstick an AFK team), same as team-level
    access is checked everywhere else in the app.
    """
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    if team.league_id != league.id:
        raise HTTPException(status_code=400, detail="Team does not belong to this draft's league")
    if team.is_cpu:
        await require_league_participant(league, current_user, db)
    else:
        require_team_or_league_access(team, league, current_user)
    return team


@router.post("", status_code=status.HTTP_201_CREATED)
@limiter.limit("10/hour")
async def api_create_draft(
    request: Request,
    draft_data: DraftCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new draft for a league with randomized snake order. Commissioner only."""
    league = await _get_league_or_404(draft_data.league_id, db)
    require_commissioner(league, current_user)
    try:
        draft = await create_draft(db, draft_data.league_id, draft_data.total_rounds)
        return {"id": draft.id, "league_id": draft.league_id, "status": draft.status.value, "total_rounds": draft.total_rounds}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# Static-prefix route -- must come before /{draft_id}/... below, or a
# dynamic segment could shadow it depending on match order.
@router.post("/mock/quickstart", status_code=status.HTTP_201_CREATED)
@limiter.limit("10/hour")
async def api_quickstart_mock_draft(
    request: Request,
    data: MockDraftQuickstart,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """No real league needed -- provisions a scratch league + CPU teams and
    starts a draft immediately. Powers the standalone /mock-draft page."""
    try:
        draft, my_team_id = await quickstart_mock_draft(
            db,
            current_user.id,
            num_teams=data.num_teams,
            total_rounds=data.total_rounds,
            draft_position=data.draft_position,
        )
        # This draft starts immediately (never sits PENDING), so the
        # frontend's own claim-a-team screen never gets a chance to run --
        # team_id is how it finds out which row is the user's without it.
        return {"draft_id": draft.id, "league_id": draft.league_id, "team_id": my_team_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{draft_id}/start")
@limiter.limit("10/hour")
async def api_start_draft(
    request: Request,
    draft_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Start a pending draft. Commissioner only."""
    _, league = await _get_draft_and_league_or_404(draft_id, db)
    require_commissioner(league, current_user)
    try:
        draft = await start_draft(db, draft_id)
        return {"id": draft.id, "status": draft.status.value, "current_round": draft.current_round}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{draft_id}/pick")
@limiter.limit("300/hour")  # deliberately generous -- a real live draft legitimately fires many rapid sequential picks; breaking that would be worse than the abuse case being guarded against
async def api_make_pick(
    request: Request,
    draft_id: str,
    pick_data: DraftPickCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Make a draft pick. Restricted to the picking team's own owner/
    co-owner (or the commissioner) for a real team; any league participant
    for a CPU team -- see _require_pick_access."""
    _, league = await _get_draft_and_league_or_404(draft_id, db)
    await _require_pick_access(pick_data.team_id, league, current_user, db)
    try:
        pick = await make_pick(db, draft_id, pick_data.team_id, pick_data.player_id)
        return {
            "id": pick.id,
            "round": pick.round,
            "pick_number": pick.pick_number,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/find")
async def api_get_draft_by_league(league_id: str, db: AsyncSession = Depends(get_db)):
    """Get the active draft for a league."""
    result = await db.execute(
        select(Draft).where(Draft.league_id == league_id).order_by(Draft.created_at.desc())
    )
    draft = result.scalars().first()
    if not draft:
        raise HTTPException(status_code=404, detail="No draft found for this league")
    return {"id": draft.id, "league_id": draft.league_id, "status": draft.status.value}


@router.get("/{draft_id}/state")
async def api_draft_state(draft_id: str, db: AsyncSession = Depends(get_db)):
    """Get the full state of a draft including board and picks."""
    try:
        state = await get_draft_state(db, draft_id)
        return state
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{draft_id}/mock")
@limiter.limit("10/hour")
async def api_run_mock(
    request: Request,
    draft_id: str,
    req: MockDraftRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Run a full or hybrid mock draft with AI auto-picks. Commissioner
    only -- unlike a single pick or nudging one CPU team forward, this
    can fill every remaining pick in the draft at once.

    If skip_team_ids is provided, those teams' picks are left open for manual drafting.
    """
    _, league = await _get_draft_and_league_or_404(draft_id, db)
    require_commissioner(league, current_user)
    try:
        picks = await run_mock_draft(db, draft_id, skip_team_ids=req.skip_team_ids)
        return {
            "message": f"Mock draft complete with {len(picks)} picks",
            "total_picks": len(picks),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{draft_id}/auto-pick")
@limiter.limit("300/hour")  # deliberately generous -- same reasoning as /{draft_id}/pick
async def api_auto_pick(
    request: Request,
    draft_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Auto-pick for whoever is currently on the clock. Same access rule
    as a manual pick (_require_pick_access, checked against whichever team
    current_team_id turns out to be) -- covers both a team owner
    auto-picking for themselves when their own timer runs out, and any
    league participant nudging a CPU team forward."""
    try:
        # Get current draft state to find who's picking
        state = await get_draft_state(db, draft_id)
        if not state["current_team_id"]:
            raise HTTPException(status_code=400, detail="No team is on the clock")
        if state["draft"]["status"] != "in_progress":
            raise HTTPException(status_code=400, detail="Draft is not in progress")

        _, league = await _get_draft_and_league_or_404(draft_id, db)
        await _require_pick_access(state["current_team_id"], league, current_user, db)

        # Get AI pick
        player = await get_ai_mock_pick(db, draft_id, state["current_team_id"])
        if not player:
            raise HTTPException(status_code=400, detail="No available players to pick")

        # Make the pick
        pick = await make_pick(db, draft_id, state["current_team_id"], player.id)
        return {
            "id": pick.id,
            "round": pick.round,
            "pick_number": pick.pick_number,
            "player": f"{player.first_name} {player.last_name}",
            "position": player.position,
            "team_id": state["current_team_id"],
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{draft_id}/timer")
@limiter.limit("30/hour")
async def api_set_timer(
    request: Request,
    draft_id: str,
    timer_data: TimerUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Set the countdown timer duration for draft picks. Commissioner only."""
    if timer_data.timer_seconds < 0 or timer_data.timer_seconds > 600:
        raise HTTPException(status_code=400, detail="Timer must be between 0 and 600 seconds")

    draft, league = await _get_draft_and_league_or_404(draft_id, db)
    require_commissioner(league, current_user)

    draft.timer_seconds = timer_data.timer_seconds
    await db.commit()
    return {"timer_seconds": draft.timer_seconds}
