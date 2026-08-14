from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from app.core.database import get_db
from app.core.limiter import limiter
from app.models.notification import Notification
from app.models.user import User
from app.api.deps import get_current_user

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _serialize(n: Notification) -> dict:
    return {
        "id": n.id,
        "type": n.type.value,
        "message": n.message,
        "link": n.link,
        "league_id": n.league_id,
        "is_read": n.is_read,
        "created_at": n.created_at.isoformat(),
    }


@router.get("")
async def list_notifications(
    limit: int = 25,
    unread_only: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Current user's own notifications, newest first. unread_count is
    always the TRUE total (not capped by `limit`), so a bell badge can
    show "12" even if only the most recent 25 are being displayed."""
    query = select(Notification).where(Notification.user_id == current_user.id)
    if unread_only:
        query = query.where(Notification.is_read == False)  # noqa: E712
    query = query.order_by(Notification.created_at.desc()).limit(limit)
    result = await db.execute(query)
    items = result.scalars().all()

    count_result = await db.execute(
        select(func.count()).select_from(Notification).where(
            Notification.user_id == current_user.id, Notification.is_read == False  # noqa: E712
        )
    )
    unread_count = count_result.scalar_one()

    return {"notifications": [_serialize(n) for n in items], "unread_count": unread_count}


@router.post("/{notification_id}/read")
@limiter.limit("100/hour")
async def mark_read(
    request: Request,
    notification_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Notification).where(Notification.id == notification_id, Notification.user_id == current_user.id)
    )
    notification = result.scalar_one_or_none()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.is_read = True
    await db.commit()
    return {"status": "ok"}


@router.post("/read-all")
@limiter.limit("60/hour")
async def mark_all_read(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await db.execute(
        update(Notification)
        .where(Notification.user_id == current_user.id, Notification.is_read == False)  # noqa: E712
        .values(is_read=True)
    )
    await db.commit()
    return {"status": "ok"}
