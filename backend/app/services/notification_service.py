"""
Minimal notification creation -- a single helper every caller (trade
review, waiver processing, weekly matchup results) goes through, so the
"what does a notification actually look like" shape lives in one place.

Deliberately fire-and-forget within the caller's existing transaction:
create_notification just adds the row (doesn't commit) -- callers commit
it together with whatever state change triggered it, so a notification
can never exist for something that didn't actually happen (partial
commit), and never silently vanish if the notification write itself
somehow failed after the real state change already committed.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.notification import Notification, NotificationType


async def create_notification(
    db: AsyncSession,
    user_id: str,
    type: NotificationType,
    message: str,
    league_id: str | None = None,
    link: str | None = None,
) -> Notification:
    notification = Notification(
        user_id=user_id, league_id=league_id, type=type, message=message, link=link,
    )
    db.add(notification)
    return notification


async def notify_team_owners(
    db: AsyncSession,
    team,  # app.models.team.Team -- typed loosely to avoid a circular import
    type: NotificationType,
    message: str,
    league_id: str | None = None,
    link: str | None = None,
) -> None:
    """Same notification to both a team's owner and co-owner (if any) --
    trades/waivers/matchup results all affect the team, not one specific
    person on it."""
    for user_id in {team.owner_id, team.co_owner_id}:
        if user_id:
            await create_notification(db, user_id, type, message, league_id=league_id, link=link)
