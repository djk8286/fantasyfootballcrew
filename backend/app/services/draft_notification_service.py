"""
Who gets emailed about a draft, and the three send points (scheduled,
reminder, live) -- shared by the schedule/start endpoints in drafts.py
and scheduler.py's periodic auto-start/reminder check, so all four
places that can trigger one of these sends go through the same
participant list and the same email content.

INCIDENT (2026-09-09): the first version of this awaited these sends
inline on the CALLER's own db session -- e.g. api_start_draft held its
one request-scoped connection checked out for the entire sequential
loop of per-recipient Resend calls before ever returning a response.
For a league with more than a handful of real owners, that's several
seconds per recipient held on ONE connection out of the pool's 15
(5 base + 10 overflow). During an actual live draft (many concurrent
/state polls, each needing their own connection), that was enough to
exhaust the pool -- every other request queued for a connection until
Railway's proxy hit its 30s timeout, which is exactly what production
logs showed (`QueuePool limit of size 5 overflow 10 reached... timeout
30.00`) uniformly across p50-p99 latency while CPU/memory sat idle.

Fix: every notify_* function here opens its OWN short-lived session
(fetching the league/draft fresh, since the caller's ORM objects belong
to a different session) and is meant to be fired via
asyncio.create_task -- never awaited inline in a request handler or the
scheduler's per-draft loop. See fire_and_forget_notify below for the
one place that actually schedules the task (keeps a reference so it
isn't garbage-collected mid-flight, and logs a failure instead of
letting an unretrieved exception vanish silently).
"""
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import async_session
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

# Keeps strong references to in-flight background tasks -- asyncio only
# holds a weak reference otherwise, so a task can be garbage-collected
# mid-execution with nothing to show for it. Discarded once done via
# the done-callback below.
_background_tasks: set[asyncio.Task] = set()


def fire_and_forget_notify(coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)

    def _on_done(t: asyncio.Task) -> None:
        _background_tasks.discard(t)
        exc = t.exception() if not t.cancelled() else None
        if exc:
            print(f"[draft_notification] Background notify failed: {exc}", flush=True)

    task.add_done_callback(_on_done)


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


def _draft_link(draft_id: str) -> str:
    return f"{settings.FRONTEND_URL}/draft/{draft_id}"


async def notify_draft_scheduled(league_id: str, draft_id: str) -> None:
    """Opens its own session -- run this via fire_and_forget_notify,
    never awaited directly in a request handler. See module docstring."""
    async with async_session() as db:
        league = (await db.execute(select(League).where(League.id == league_id))).scalar_one_or_none()
        draft = (await db.execute(select(Draft).where(Draft.id == draft_id))).scalar_one_or_none()
        if not league or not draft or not draft.scheduled_for:
            return
        link = _draft_link(draft_id)
        for user in await get_league_participant_users(db, league_id):
            await send_draft_scheduled_email(user.email, league.name, draft.scheduled_for, link, db)


async def notify_draft_reminder(league_id: str, draft_id: str) -> None:
    async with async_session() as db:
        league = (await db.execute(select(League).where(League.id == league_id))).scalar_one_or_none()
        draft = (await db.execute(select(Draft).where(Draft.id == draft_id))).scalar_one_or_none()
        if not league or not draft or not draft.scheduled_for:
            return
        link = _draft_link(draft_id)
        for user in await get_league_participant_users(db, league_id):
            await send_draft_reminder_email(user.email, league.name, draft.scheduled_for, link, db)


async def notify_draft_live(league_id: str, draft_id: str) -> None:
    async with async_session() as db:
        league = (await db.execute(select(League).where(League.id == league_id))).scalar_one_or_none()
        if not league:
            return
        link = _draft_link(draft_id)
        for user in await get_league_participant_users(db, league_id):
            await send_draft_live_email(user.email, league.name, link, db)
