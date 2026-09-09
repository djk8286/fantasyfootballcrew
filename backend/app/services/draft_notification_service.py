"""
Who gets emailed about a draft, and the three send points (scheduled,
reminder, live) -- shared by the schedule/start endpoints in drafts.py
and scheduler.py's periodic auto-start/reminder check, so all four
places that can trigger one of these sends go through the same
participant list and the same email content.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import settings
from app.models.team import Team
from app.models.league import League
from app.models.draft import Draft
from app.models.user import User
from app.services.email_service import (
    send_draft_scheduled_email,
    send_draft_reminder_email,
    send_draft_live_email,
)


async def get_league_participant_users(db: AsyncSession, league_id: str) -> list[User]:
    """Every distinct real (non-CPU) owner/co-owner across every team in
    the league -- not the commissioner specifically, whoever's actually
    going to be drafting. A commissioner who also owns a team is
    included via that team, not double-counted (this is deduped by
    user id, not by role)."""
    result = await db.execute(
        select(Team.owner_id, Team.co_owner_id).where(Team.league_id == league_id)
    )
    user_ids: set[str] = set()
    for owner_id, co_owner_id in result.all():
        if owner_id:
            user_ids.add(owner_id)
        if co_owner_id:
            user_ids.add(co_owner_id)
    if not user_ids:
        return []
    users_result = await db.execute(select(User).where(User.id.in_(user_ids)))
    return list(users_result.scalars().all())


def _draft_link(draft: Draft) -> str:
    return f"{settings.FRONTEND_URL}/draft/{draft.id}"


async def notify_draft_scheduled(db: AsyncSession, league: League, draft: Draft) -> None:
    link = _draft_link(draft)
    for user in await get_league_participant_users(db, league.id):
        await send_draft_scheduled_email(user.email, league.name, draft.scheduled_for, link, db)


async def notify_draft_reminder(db: AsyncSession, league: League, draft: Draft) -> None:
    link = _draft_link(draft)
    for user in await get_league_participant_users(db, league.id):
        await send_draft_reminder_email(user.email, league.name, draft.scheduled_for, link, db)


async def notify_draft_live(db: AsyncSession, league: League, draft: Draft) -> None:
    link = _draft_link(draft)
    for user in await get_league_participant_users(db, league.id):
        await send_draft_live_email(user.email, league.name, link, db)
