from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from app.core.database import get_db
from app.core.limiter import limiter
from app.services.draft_manager import (
    create_draft,
    start_draft,
    make_pick,
    get_draft_state_encoded,
    run_mock_draft,
    current_pick_slot,
    get_autopick,
    set_autopick,
    get_next_pick_for_team,
    get_team_queue,
    add_to_queue,
    remove_from_queue,
    quickstart_mock_draft,
)
from app.models.draft import Draft, DraftPick, DraftRunStatus
from app.models.league import League
from app.models.team import Team
from app.models.user import User
from app.models.player import Player
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


class QueueMutation(BaseModel):
    team_id: str
    player_id: str


class AutopickUpdate(BaseModel):
    team_id: str
    enabled: bool

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
    for a CPU team -- see _require_pick_access. Pass pick_number to make a
    retried/double-clicked request idempotent (it can't spill onto the
    next pick)."""
    _, league = await _get_draft_and_league_or_404(draft_id, db)
    await _require_pick_access(pick_data.team_id, league, current_user, db)
    try:
        pick = await make_pick(
            db, draft_id, pick_data.team_id, pick_data.player_id, expected_pick_number=pick_data.pick_number,
        )
        player = await db.get(Player, pick.player_id)
        return {
            "id": pick.id,
            "round": pick.round,
            "pick_number": pick.pick_number,
            "team_id": pick.team_id,
            "player_id": pick.player_id,
            "player": f"{player.first_name} {player.last_name}" if player else None,
            "position": player.position if player else None,
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
async def api_draft_state(draft_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Get the full state of a draft including board and picks.

    Served from draft_manager.get_draft_state_encoded's shared cache: one
    build per state change no matter how many viewers poll, pre-encoded
    and pre-gzipped, with an ETag so an unchanged poll is a bodyless 304
    (2026-10-19 slowdown: every poll used to rebuild ~10 MB of JSON)."""
    try:
        enc = await get_draft_state_encoded(db, draft_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    headers = {"ETag": enc.etag, "Cache-Control": "no-cache", "Vary": "Accept-Encoding"}
    if request.headers.get("if-none-match") == enc.etag:
        return Response(status_code=304, headers=headers)
    if "gzip" in (request.headers.get("accept-encoding") or "").lower():
        return Response(content=enc.gzipped, media_type="application/json",
                        headers={**headers, "Content-Encoding": "gzip"})
    return Response(content=enc.body, media_type="application/json", headers=headers)


@router.post("/{draft_id}/mock")
@limiter.limit("60/hour")
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
        draft = (await db.execute(
            select(Draft).where(Draft.id == draft_id).execution_options(populate_existing=True)
        )).scalar_one()
        return {
            "message": f"Mock draft complete with {len(picks)} picks",
            "total_picks": len(picks),
            "status": draft.status.value,
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
    is on the clock). Looks the team up straight from the draft row -- it
    used to build the entire draft state (the full player board) just to
    find that out, which made this take 8-25 s under load."""
    draft, league = await _get_draft_and_league_or_404(draft_id, db)
    if draft.status != DraftRunStatus.IN_PROGRESS:
        raise HTTPException(status_code=400, detail="Draft is not in progress")
    num_teams = int(await db.scalar(select(func.count(Team.id)).where(Team.league_id == draft.league_id)) or 0)
    pick_number, team_id = current_pick_slot(draft, num_teams)
    if not team_id:
        raise HTTPException(status_code=400, detail="No team is on the clock")
    await _require_pick_access(team_id, league, current_user, db)
    try:
        # Queue-first, AI-ranking-fallback -- see get_next_pick_for_team's
        # docstring. Same function the draft watchdog uses.
        player = await get_next_pick_for_team(
            db, draft_id, team_id, current_round=draft.current_round, total_rounds=draft.total_rounds,
        )
        if not player:
            raise HTTPException(status_code=400, detail="No available players to pick")
        pick = await make_pick(db, draft_id, team_id, player.id, expected_pick_number=pick_number)
        return {
            "id": pick.id,
            "round": pick.round,
            "pick_number": pick.pick_number,
            "player": f"{player.first_name} {player.last_name}",
            "position": player.position,
            "team_id": team_id,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{draft_id}/autopick")
async def api_get_autopick(
    draft_id: str,
    team_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """This team's server-persisted Autopick setting for this draft."""
    _, league = await _get_draft_and_league_or_404(draft_id, db)
    await _require_queue_access(team_id, league, current_user, db)
    return {"team_id": team_id, "enabled": await get_autopick(db, draft_id, team_id)}


@router.put("/{draft_id}/autopick")
@limiter.limit("120/hour")
async def api_set_autopick(
    request: Request,
    draft_id: str,
    data: AutopickUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Turn Autopick on/off for one team in this draft. Persisted, so it
    survives reloads and works with no tab open: ON = the server picks for
    this team as soon as it's on the clock (queue first). OFF = it waits
    for the pick clock -- and still autopicks when the clock runs out."""
    _, league = await _get_draft_and_league_or_404(draft_id, db)
    await _require_queue_access(data.team_id, league, current_user, db)
    enabled = await set_autopick(db, draft_id, data.team_id, data.enabled, current_user.id)
    return {"team_id": data.team_id, "enabled": enabled}


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


@router.post("/{draft_id}/pause")
@limiter.limit("60/hour")
async def api_pause_draft(
    request: Request,
    draft_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Pause an in-progress draft (no picks of any kind until resumed). Commissioner only."""
    draft, league = await _get_draft_and_league_or_404(draft_id, db)
    require_commissioner(league, current_user)
    if draft.status.value != "in_progress":
        raise HTTPException(status_code=400, detail="Draft is not in progress")
    draft.is_paused = True
    await db.commit()
    return {"is_paused": True}


@router.post("/{draft_id}/resume")
@limiter.limit("60/hour")
async def api_resume_draft(
    request: Request,
    draft_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Resume a paused draft; the current pick's clock restarts. Commissioner only."""
    draft, league = await _get_draft_and_league_or_404(draft_id, db)
    require_commissioner(league, current_user)
    draft.is_paused = False
    draft.current_pick_started_at = datetime.now(timezone.utc)
    await db.commit()
    return {"is_paused": False}


# ─── Pick queue (2026-09-09) ───────────────────────────────────────────
#
# Server-persisted so a team's queue survives a page refresh -- the old
# version lived only in the draft page's React state, gone the instant
# the tab reloaded. Access mirrors require_team_or_league_access
# directly (not _require_pick_access's CPU-permissive version above): a
# CPU team has no human to queue anything for, so there's nothing for
# any "any participant can nudge a CPU team" exception to apply to here.


async def _require_queue_access(team_id: str, league: League, current_user: User, db: AsyncSession) -> Team:
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    if team.league_id != league.id:
        raise HTTPException(status_code=400, detail="Team does not belong to this draft's league")
    if team.is_cpu:
        raise HTTPException(status_code=400, detail="CPU teams don't have a pick queue")
    require_team_or_league_access(team, league, current_user)
    return team


@router.get("/{draft_id}/queue")
async def api_get_queue(
    draft_id: str,
    team_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """A team's queue, in pick order. Restricted to that team's own
    owner/co-owner or the commissioner -- same visibility as the queue
    itself is used for (nobody else can act on it, so nobody else needs
    to see it)."""
    _, league = await _get_draft_and_league_or_404(draft_id, db)
    await _require_queue_access(team_id, league, current_user, db)
    entries = await get_team_queue(db, draft_id, team_id)
    return {"player_ids": [e.player_id for e in entries]}


@router.post("/{draft_id}/queue/add")
@limiter.limit("120/hour")
async def api_add_to_queue(
    request: Request,
    draft_id: str,
    data: QueueMutation,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Append a player to the end of a team's queue."""
    _, league = await _get_draft_and_league_or_404(draft_id, db)
    await _require_queue_access(data.team_id, league, current_user, db)
    await add_to_queue(db, draft_id, data.team_id, data.player_id)
    entries = await get_team_queue(db, draft_id, data.team_id)
    return {"player_ids": [e.player_id for e in entries]}


@router.post("/{draft_id}/queue/remove")
@limiter.limit("120/hour")
async def api_remove_from_queue(
    request: Request,
    draft_id: str,
    data: QueueMutation,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a player from a team's queue."""
    _, league = await _get_draft_and_league_or_404(draft_id, db)
    await _require_queue_access(data.team_id, league, current_user, db)
    await remove_from_queue(db, draft_id, data.team_id, data.player_id)
    entries = await get_team_queue(db, draft_id, data.team_id)
    return {"player_ids": [e.player_id for e in entries]}
