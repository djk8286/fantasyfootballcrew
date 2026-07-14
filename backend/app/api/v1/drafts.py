from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.core.database import get_db
from app.services.draft_manager import (
    create_draft,
    start_draft,
    make_pick,
    get_draft_state,
    run_mock_draft,
    get_ai_mock_pick,
)
from app.models.draft import Draft, DraftPick, DraftRunStatus
from app.schemas.draft import DraftCreate, DraftRead, DraftPickCreate, DraftPickRead, DraftState
from pydantic import BaseModel


class TimerUpdate(BaseModel):
    timer_seconds: int


class MockDraftRequest(BaseModel):
    """Request to run a (potentially hybrid) mock draft.
    Teams in skip_team_ids will NOT get auto-picked — they stay open for manual drafting."""
    skip_team_ids: list[str] = []

router = APIRouter(prefix="/drafts", tags=["drafts"])


@router.post("/", status_code=status.HTTP_201_CREATED)
async def api_create_draft(draft_data: DraftCreate, db: AsyncSession = Depends(get_db)):
    """Create a new draft for a league with randomized snake order."""
    try:
        draft = await create_draft(db, draft_data.league_id, draft_data.total_rounds)
        return {"id": draft.id, "league_id": draft.league_id, "status": draft.status.value, "total_rounds": draft.total_rounds}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{draft_id}/start")
async def api_start_draft(draft_id: str, db: AsyncSession = Depends(get_db)):
    """Start a pending draft."""
    try:
        draft = await start_draft(db, draft_id)
        return {"id": draft.id, "status": draft.status.value, "current_round": draft.current_round}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{draft_id}/pick")
async def api_make_pick(
    draft_id: str,
    pick_data: DraftPickCreate,
    db: AsyncSession = Depends(get_db),
):
    """Make a draft pick."""
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
async def api_run_mock(draft_id: str, req: MockDraftRequest, db: AsyncSession = Depends(get_db)):
    """Run a full or hybrid mock draft with AI auto-picks.
    
    If skip_team_ids is provided, those teams' picks are left open for manual drafting.
    """
    try:
        picks = await run_mock_draft(db, draft_id, skip_team_ids=req.skip_team_ids)
        return {
            "message": f"Mock draft complete with {len(picks)} picks",
            "total_picks": len(picks),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{draft_id}/auto-pick")
async def api_auto_pick(draft_id: str, db: AsyncSession = Depends(get_db)):
    """Auto-pick for whoever is currently on the clock (CPU teams)."""
    try:
        # Get current draft state to find who's picking
        state = await get_draft_state(db, draft_id)
        if not state["current_team_id"]:
            raise HTTPException(status_code=400, detail="No team is on the clock")
        if state["draft"]["status"] != "in_progress":
            raise HTTPException(status_code=400, detail="Draft is not in progress")
        
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
async def api_set_timer(draft_id: str, timer_data: TimerUpdate, db: AsyncSession = Depends(get_db)):
    """Set the countdown timer duration for draft picks."""
    if timer_data.timer_seconds < 0 or timer_data.timer_seconds > 600:
        raise HTTPException(status_code=400, detail="Timer must be between 0 and 600 seconds")
    
    result = await db.execute(select(Draft).where(Draft.id == draft_id))
    draft = result.scalar_one_or_none()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    draft.timer_seconds = timer_data.timer_seconds
    await db.commit()
    return {"timer_seconds": draft.timer_seconds}
