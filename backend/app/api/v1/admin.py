"""
Dev/management dashboard for David and anyone he grants is_admin to
(see User.is_admin, deps.require_admin). Was deliberately read-only
until 2026-09-22 -- the 2026-09-08 incident this originally existed to
prevent wasn't a bad delete so much as a delete made without knowing
who was actually using the app, and the fix for THAT was visibility,
not a delete button. That reasoning still holds, which is why
get_league_detail below exists at all: an admin can now actually look
at a league's real drafts/teams/scoring before deciding whether it's
dead, instead of deleting blind. Deletion itself is now a real,
explicit admin ask (leagues and unverified/inactive users specifically)
-- delete_league/delete_user_account below are the same one-off-script
logic this docstring used to point at, just reachable from the
dashboard instead of a shell. Every league/user list endpoint here
already IS the visibility check; deletion doesn't skip it, since the
frontend always shows this same data before offering a delete.
"""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_

from app.core.database import get_db
from app.core.config import settings
from app.models.user import User
from app.models.league import League, DraftStatus
from app.models.team import Team
from app.models.draft import Draft, DraftPick, DraftRunStatus
from app.models.ai_usage_event import AIUsageEvent
from app.models.email_send_log import EmailSendLog
from app.api.deps import require_admin
from app.services.league_deletion_service import delete_league as _delete_league
from app.services.account_deletion_service import delete_user_account
from app.services.job_run_service import get_system_health
from app.models.admin_audit_log import AdminAuditLog
from app.api.v1.auth import create_and_send_password_reset_email, _create_and_send_verification_email

router = APIRouter(prefix="/admin", tags=["admin"])

# "Stuck" thresholds -- deliberately generous (a real live draft can
# legitimately sit on one pick for a while if someone's timer is long or
# they're just slow), tuned to flag drafts that look abandoned, not ones
# mid-pick.
STUCK_DRAFT_HOURS = 48
STALE_NOT_STARTED_DAYS = 7


@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Top-line counts -- the "is this actually just me testing" check
    that would have caught the 2026-09-08 incident before it happened."""
    users = (await db.execute(select(func.count(User.id)))).scalar()
    leagues = (await db.execute(select(func.count(League.id)))).scalar()
    teams = (await db.execute(select(func.count(Team.id)))).scalar()
    drafts_in_progress = (
        await db.execute(select(func.count(Draft.id)).where(Draft.status == DraftRunStatus.IN_PROGRESS))
    ).scalar()
    picks_made = (await db.execute(select(func.count(DraftPick.id)))).scalar()
    return {
        "users": users,
        "leagues": leagues,
        "teams": teams,
        "drafts_in_progress": drafts_in_progress,
        "draft_picks_made": picks_made,
    }


def _audit(
    db: AsyncSession,
    admin: User,
    action: str,
    target_type: str,
    target_id: str,
    target_label: str | None = None,
    details: dict | None = None,
) -> None:
    """Stage an AdminAuditLog row in the caller's session -- committed by
    the same db.commit() as the change it describes, never separately."""
    db.add(AdminAuditLog(
        admin_user_id=admin.id,
        admin_username=admin.username,
        action=action,
        target_type=target_type,
        target_id=target_id,
        target_label=target_label,
        details=details,
    ))


def _user_row(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "provider": u.provider,
        "email_verified": u.email_verified,
        "is_admin": u.is_admin,
        "is_suspended": u.is_suspended,
        "suspended_at": u.suspended_at,
        "suspended_reason": u.suspended_reason,
        "has_password": u.hashed_password is not None,
        "created_at": u.created_at,
    }


@router.get("/users")
async def list_users(
    q: str | None = Query(None, max_length=100),
    status: str | None = Query(None, pattern="^(suspended|admin|unverified)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Accounts, newest first, with optional case-insensitive search over
    username/email and a status filter. Paginated -- returns
    {items, total, limit, offset}. Includes email -- this endpoint is
    already admin-gated, unlike the public-facing UserPublic schema
    (GET /users/{id}) that deliberately withholds it."""
    query = select(User)
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        query = query.where(or_(func.lower(User.username).like(like), func.lower(User.email).like(like)))
    if status == "suspended":
        query = query.where(User.is_suspended.is_(True))
    elif status == "admin":
        query = query.where(User.is_admin.is_(True))
    elif status == "unverified":
        query = query.where(User.email_verified.is_(False))
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    result = await db.execute(query.order_by(User.created_at.desc(), User.id).limit(limit).offset(offset))
    return {
        "items": [_user_row(u) for u in result.scalars().all()],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


async def _get_target_user(db: AsyncSession, user_id: str) -> User:
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


class SuspendRequest(BaseModel):
    reason: str | None = Field(None, max_length=500)


@router.post("/users/{user_id}/suspend")
async def suspend_user(
    user_id: str,
    body: SuspendRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Blocks login and every authenticated request (see deps.py), and
    bumps token_version so any session already open dies on its next
    request. Reversible via /unsuspend."""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="You can't suspend your own account")
    user = await _get_target_user(db, user_id)
    if user.is_suspended:
        return _user_row(user)
    user.is_suspended = True
    user.suspended_at = datetime.now(timezone.utc)
    user.suspended_reason = (body.reason or "").strip() or None
    user.token_version += 1
    _audit(db, admin, "user.suspend", "user", user.id, user.username, {"reason": user.suspended_reason})
    await db.commit()
    return _user_row(user)


@router.post("/users/{user_id}/unsuspend")
async def unsuspend_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = await _get_target_user(db, user_id)
    if not user.is_suspended:
        return _user_row(user)
    user.is_suspended = False
    user.suspended_at = None
    user.suspended_reason = None
    _audit(db, admin, "user.unsuspend", "user", user.id, user.username)
    await db.commit()
    return _user_row(user)


@router.post("/users/{user_id}/force-logout")
async def force_logout_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Invalidates every JWT this user currently holds (token_version
    bump -- the same mechanism a password reset uses). They can log
    straight back in; this just kills existing sessions."""
    user = await _get_target_user(db, user_id)
    user.token_version += 1
    _audit(db, admin, "user.force_logout", "user", user.id, user.username)
    await db.commit()
    return {"status": "ok"}


@router.post("/users/{user_id}/send-password-reset")
async def admin_send_password_reset(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Same email/token flow as the self-service POST /auth/forgot-password
    (no rate limit here -- admin-gated). The admin never sees the link;
    it only goes to the account's own email (or the server log when no
    email provider is configured, same as self-service)."""
    user = await _get_target_user(db, user_id)
    if not user.hashed_password:
        raise HTTPException(status_code=400, detail=f"This account signs in with {user.provider} and has no password to reset")
    _audit(db, admin, "user.send_password_reset", "user", user.id, user.username)
    await create_and_send_password_reset_email(user, db)
    return {"status": "ok"}


@router.post("/users/{user_id}/resend-verification")
async def admin_resend_verification(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = await _get_target_user(db, user_id)
    if user.email_verified:
        raise HTTPException(status_code=400, detail="This account's email is already verified")
    _audit(db, admin, "user.resend_verification", "user", user.id, user.username)
    await _create_and_send_verification_email(user, db)
    return {"status": "ok"}


class SetAdminRequest(BaseModel):
    is_admin: bool


@router.post("/users/{user_id}/admin")
async def set_user_admin(
    user_id: str,
    body: SetAdminRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Grant or revoke is_admin. You can't change your own admin flag
    (so nobody locks themselves out by accident), and the last remaining
    admin can never be demoted."""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="You can't change your own admin access")
    user = await _get_target_user(db, user_id)
    if user.is_admin == body.is_admin:
        return _user_row(user)
    if not body.is_admin:
        admin_count = (await db.execute(select(func.count(User.id)).where(User.is_admin.is_(True)))).scalar() or 0
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="Can't remove the last admin")
    user.is_admin = body.is_admin
    _audit(db, admin, "user.grant_admin" if body.is_admin else "user.revoke_admin", "user", user.id, user.username)
    await db.commit()
    return _user_row(user)


@router.get("/audit-log")
async def get_audit_log(
    target_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Every admin mutation, newest first. Optionally scoped to one
    target (user or league id)."""
    query = select(AdminAuditLog)
    if target_id:
        query = query.where(AdminAuditLog.target_id == target_id)
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    rows = (await db.execute(
        query.order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id).limit(limit).offset(offset)
    )).scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "admin_user_id": r.admin_user_id,
                "admin_username": r.admin_username,
                "action": r.action,
                "target_type": r.target_type,
                "target_id": r.target_id,
                "target_label": r.target_label,
                "details": r.details,
                "created_at": r.created_at,
            }
            for r in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/leagues")
async def list_leagues(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Every league, newest first, with who commissions it -- the exact
    "who do I even contact" question that was unanswerable during the
    2026-09-08 wipe. Team.league relationship is lazy="selectin" (see
    League model), so `l.teams` below is already loaded, not an N+1."""
    leagues_result = await db.execute(select(League).order_by(League.created_at.desc()))
    leagues = leagues_result.scalars().all()

    commissioner_ids = {l.commissioner_id for l in leagues}
    users_by_id: dict[str, User] = {}
    if commissioner_ids:
        users_result = await db.execute(select(User).where(User.id.in_(commissioner_ids)))
        users_by_id = {u.id: u for u in users_result.scalars().all()}

    return [
        {
            "id": l.id,
            "name": l.name,
            "commissioner_username": users_by_id[l.commissioner_id].username if l.commissioner_id in users_by_id else None,
            "commissioner_email": users_by_id[l.commissioner_id].email if l.commissioner_id in users_by_id else None,
            "league_type": l.league_type.value,
            "visibility": l.visibility.value,
            "draft_status": l.draft_status.value,
            "team_count": len(l.teams),
            "is_mock": l.is_mock,
            "created_at": l.created_at,
        }
        for l in leagues
    ]


@router.get("/leagues/{league_id}")
async def get_league_detail(
    league_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Everything about one league in a single read-only view: its real
    teams (with owners), drafts (with pick progress), and scoring/
    roster-slot layout -- exactly what an admin needs to tell a real,
    active league apart from a dead shell BEFORE deciding to delete it
    (see module docstring). No write path here -- changing anything
    about a league still only ever happens through the normal
    commissioner endpoints, never this dashboard."""
    result = await db.execute(select(League).where(League.id == league_id))
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")

    teams_result = await db.execute(select(Team).where(Team.league_id == league_id).order_by(Team.name))
    teams = teams_result.scalars().all()

    user_ids = {league.commissioner_id}
    user_ids |= {t.owner_id for t in teams if t.owner_id}
    user_ids |= {t.co_owner_id for t in teams if t.co_owner_id}
    users_by_id: dict[str, User] = {}
    if user_ids:
        users_result = await db.execute(select(User).where(User.id.in_(user_ids)))
        users_by_id = {u.id: u for u in users_result.scalars().all()}

    drafts_result = await db.execute(
        select(Draft).where(Draft.league_id == league_id).order_by(Draft.created_at.desc())
    )
    drafts = drafts_result.scalars().all()
    pick_counts: dict[str, int] = {}
    if drafts:
        pick_count_result = await db.execute(
            select(DraftPick.draft_id, func.count(DraftPick.id))
            .where(DraftPick.draft_id.in_([d.id for d in drafts]))
            .group_by(DraftPick.draft_id)
        )
        pick_counts = dict(pick_count_result.all())

    return {
        "id": league.id,
        "name": league.name,
        "description": league.description,
        "commissioner_username": users_by_id[league.commissioner_id].username if league.commissioner_id in users_by_id else None,
        "commissioner_email": users_by_id[league.commissioner_id].email if league.commissioner_id in users_by_id else None,
        "league_type": league.league_type.value,
        "visibility": league.visibility.value,
        "draft_status": league.draft_status.value,
        "draft_type": league.draft_type.value,
        "max_teams": league.max_teams,
        "is_mock": league.is_mock,
        "created_at": league.created_at,
        "scoring_config": league.scoring_config,
        "roster_slots": league.roster_slots,
        "teams": [
            {
                "id": t.id,
                "name": t.name,
                "owner_username": users_by_id[t.owner_id].username if t.owner_id in users_by_id else None,
                "co_owner_username": users_by_id[t.co_owner_id].username if t.co_owner_id in users_by_id else None,
                "is_cpu": t.is_cpu,
                "wins": t.wins, "losses": t.losses, "ties": t.ties,
                "points_for": t.points_for, "points_against": t.points_against,
                "roster_size": len(t.roster or []),
            }
            for t in teams
        ],
        "drafts": [
            {
                "id": d.id,
                "status": d.status.value,
                "draft_type": d.draft_type,
                "current_round": d.current_round,
                "current_pick": d.current_pick,
                "total_rounds": d.total_rounds,
                "timer_seconds": d.timer_seconds,
                "picks_made": pick_counts.get(d.id, 0),
                "created_at": d.created_at,
            }
            for d in drafts
        ],
    }


@router.delete("/leagues/{league_id}")
async def admin_delete_league(
    league_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Permanently and irreversibly deletes a league and every row
    scoped to it -- see league_deletion_service.delete_league for the
    full cascade. The frontend requires typing the league's exact name
    to confirm before ever calling this; nothing enforces that
    server-side beyond admin gating, same trust level every other admin
    endpoint here already has."""
    result = await db.execute(select(League).where(League.id == league_id))
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    _audit(db, _admin, "league.delete", "league", league.id, league.name)
    await _delete_league(db, league)
    await db.commit()
    return {"status": "ok"}


@router.delete("/users/{user_id}")
async def admin_delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Permanently and irreversibly deletes a user account -- same
    cleanup as the self-service DELETE /users/me (see
    account_deletion_service.delete_user_account), minus the password
    confirmation (the admin isn't the account owner). 409s the same way
    self-service deletion does if this user is the sole real member of
    a league they commission -- delete that league first (see DELETE
    /admin/leagues/{league_id} above) or reassign it."""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Use account settings to delete your own account")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    _audit(db, admin, "user.delete", "user", user.id, user.username, {"email": user.email})
    await delete_user_account(db, user)
    await db.commit()
    return {"status": "ok"}


@router.get("/ai-usage")
async def get_ai_usage(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Real LLM-spend activity (see AIUsageEvent's docstring -- one row
    per digest/trade-review/message-draft/chat/recap/lineup/trade/bet
    call -- the last three of those were completely unrecorded before
    2026-09-09, which is why this previously undercounted real usage).
    Call counts only, not tokens or dollars -- there's no cost data
    captured anywhere yet, this is "how much is this feature being
    used," not "what is this costing us." by_league excludes rows with
    no league_id (bet analysis) -- those only show up in by_user."""
    since_24h = datetime.now(timezone.utc) - timedelta(hours=24)

    total = (await db.execute(select(func.count(AIUsageEvent.id)))).scalar()
    last_24h = (
        await db.execute(select(func.count(AIUsageEvent.id)).where(AIUsageEvent.created_at >= since_24h))
    ).scalar()

    by_endpoint_result = await db.execute(
        select(AIUsageEvent.endpoint, func.count(AIUsageEvent.id))
        .group_by(AIUsageEvent.endpoint)
        .order_by(func.count(AIUsageEvent.id).desc())
    )
    by_endpoint = [{"endpoint": e, "count": c} for e, c in by_endpoint_result.all()]

    by_league_result = await db.execute(
        select(AIUsageEvent.league_id, func.count(AIUsageEvent.id))
        .where(AIUsageEvent.league_id.isnot(None))
        .group_by(AIUsageEvent.league_id)
        .order_by(func.count(AIUsageEvent.id).desc())
        .limit(10)
    )
    league_rows = by_league_result.all()
    league_ids = [lid for lid, _ in league_rows]
    leagues_by_id: dict[str, League] = {}
    if league_ids:
        leagues_result = await db.execute(select(League).where(League.id.in_(league_ids)))
        leagues_by_id = {l.id: l for l in leagues_result.scalars().all()}
    by_league = [
        {
            "league_id": lid,
            "league_name": leagues_by_id[lid].name if lid in leagues_by_id else "(deleted league)",
            "count": count,
        }
        for lid, count in league_rows
    ]

    # Per-user breakdown (2026-09-09) -- only populated for calls made
    # since user_id was added; older rows (all from before the personal
    # AI tools were even tracked) simply have no user_id and are
    # excluded here the same way league-less rows are excluded from
    # by_league above.
    by_user_result = await db.execute(
        select(AIUsageEvent.user_id, func.count(AIUsageEvent.id))
        .where(AIUsageEvent.user_id.isnot(None))
        .group_by(AIUsageEvent.user_id)
        .order_by(func.count(AIUsageEvent.id).desc())
        .limit(10)
    )
    user_rows = by_user_result.all()
    user_ids = [uid for uid, _ in user_rows]
    users_by_id: dict[str, User] = {}
    if user_ids:
        users_result = await db.execute(select(User).where(User.id.in_(user_ids)))
        users_by_id = {u.id: u for u in users_result.scalars().all()}
    by_user = [
        {
            "user_id": uid,
            "username": users_by_id[uid].username if uid in users_by_id else "(deleted user)",
            "count": count,
        }
        for uid, count in user_rows
    ]

    return {
        "total": total, "last_24h": last_24h,
        "by_endpoint": by_endpoint, "by_league": by_league, "by_user": by_user,
    }


@router.get("/ai-cost")
async def get_ai_cost(
    days: int = Query(14, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Estimated AI spend from the model/token/cost fields ai_cost_service
    records per call (see AIUsageEvent). Estimates only -- priced from
    settings.AI_MODEL_PRICING, not the provider's invoice. Rows from
    before cost tracking existed have no cost and are excluded from sums
    (but still counted as calls)."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    since_24h = now - timedelta(hours=24)
    cost = func.coalesce(func.sum(AIUsageEvent.cost_usd), 0.0)

    totals = (await db.execute(
        select(
            func.count(AIUsageEvent.id), cost,
            func.coalesce(func.sum(AIUsageEvent.input_tokens), 0),
            func.coalesce(func.sum(AIUsageEvent.output_tokens), 0),
        ).where(AIUsageEvent.created_at >= since)
    )).one()
    spent_24h = float((await db.execute(select(cost).where(AIUsageEvent.created_at >= since_24h))).scalar() or 0.0)
    errors_24h = (await db.execute(
        select(func.count(AIUsageEvent.id)).where(AIUsageEvent.created_at >= since_24h, AIUsageEvent.error.isnot(None))
    )).scalar() or 0
    capped_24h = (await db.execute(
        select(func.count(AIUsageEvent.id)).where(AIUsageEvent.created_at >= since_24h, AIUsageEvent.error == "daily_spend_cap")
    )).scalar() or 0
    unpriced = (await db.execute(
        select(func.count(AIUsageEvent.id)).where(
            AIUsageEvent.created_at >= since, AIUsageEvent.model.isnot(None), AIUsageEvent.cost_usd.is_(None),
            AIUsageEvent.error.is_(None),
        )
    )).scalar() or 0

    # date() on a timestamptz is UTC on Railway's Postgres (server TZ) and
    # on SQLite's stored UTC strings -- days are UTC days.
    day = func.date(AIUsageEvent.created_at)
    daily_rows = (await db.execute(
        select(day, func.count(AIUsageEvent.id), cost,
               func.coalesce(func.sum(AIUsageEvent.input_tokens), 0),
               func.coalesce(func.sum(AIUsageEvent.output_tokens), 0))
        .where(AIUsageEvent.created_at >= since)
        .group_by(day).order_by(day)
    )).all()
    daily = [
        {"date": str(d), "calls": n, "cost_usd": round(float(c), 6), "input_tokens": int(i), "output_tokens": int(o)}
        for d, n, c, i, o in daily_rows
    ]

    user_rows = (await db.execute(
        select(AIUsageEvent.user_id, func.count(AIUsageEvent.id), cost)
        .where(AIUsageEvent.created_at >= since, AIUsageEvent.user_id.isnot(None))
        .group_by(AIUsageEvent.user_id)
        .order_by(cost.desc(), func.count(AIUsageEvent.id).desc())
        .limit(10)
    )).all()
    names: dict[str, str] = {}
    if user_rows:
        names = dict((await db.execute(
            select(User.id, User.username).where(User.id.in_([u for u, _, _ in user_rows]))
        )).all())
    top_users = [
        {"user_id": uid, "username": names.get(uid, "(deleted user)"), "calls": n, "cost_usd": round(float(c), 6)}
        for uid, n, c in user_rows
    ]

    feature_rows = (await db.execute(
        select(AIUsageEvent.endpoint, func.count(AIUsageEvent.id), cost)
        .where(AIUsageEvent.created_at >= since)
        .group_by(AIUsageEvent.endpoint)
        .order_by(cost.desc(), func.count(AIUsageEvent.id).desc())
    )).all()
    by_feature = [{"endpoint": e, "calls": n, "cost_usd": round(float(c), 6)} for e, n, c in feature_rows]

    model_rows = (await db.execute(
        select(AIUsageEvent.model, func.count(AIUsageEvent.id), cost,
               func.coalesce(func.sum(AIUsageEvent.input_tokens), 0),
               func.coalesce(func.sum(AIUsageEvent.output_tokens), 0))
        .where(AIUsageEvent.created_at >= since, AIUsageEvent.model.isnot(None))
        .group_by(AIUsageEvent.model).order_by(cost.desc())
    )).all()
    by_model = [
        {"model": m, "calls": n, "cost_usd": round(float(c), 6), "input_tokens": int(i), "output_tokens": int(o)}
        for m, n, c, i, o in model_rows
    ]

    cap = settings.AI_DAILY_SPEND_CAP_USD
    return {
        "days": days,
        "calls": totals[0],
        "cost_usd": round(float(totals[1]), 6),
        "input_tokens": int(totals[2]),
        "output_tokens": int(totals[3]),
        "cost_24h_usd": round(spent_24h, 6),
        "errors_24h": errors_24h,
        "unpriced_calls": unpriced,
        "spend_cap": {
            "cap_usd": cap,
            "spent_24h_usd": round(spent_24h, 6),
            "reached": cap is not None and spent_24h >= cap,
            "blocked_calls_24h": capped_24h,
        },
        "daily": daily,
        "top_users": top_users,
        "by_feature": by_feature,
        "by_model": by_model,
        "pricing": settings.AI_MODEL_PRICING,
    }


@router.get("/league-health")
async def get_league_health(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Leagues that likely need a look -- computed, not stored. Three
    independent flags (a league can carry more than one):

      - no_teams: a shell with nobody in it.
      - never_started: created a while ago and still hasn't drafted --
        likely abandoned setup, not "about to draft."
      - stuck_draft: draft_status is in_progress but no pick has landed
        in a while -- likely someone's turn nobody's covering.

    Excludes mock (practice-draft) leagues entirely -- they're meant to
    be short-lived and this would just be noise for every one of them."""
    now = datetime.now(timezone.utc)
    never_started_cutoff = now - timedelta(days=STALE_NOT_STARTED_DAYS)
    stuck_cutoff = now - timedelta(hours=STUCK_DRAFT_HOURS)

    leagues_result = await db.execute(select(League).where(League.is_mock == False))  # noqa: E712
    leagues = leagues_result.scalars().all()

    in_progress_ids = [l.id for l in leagues if l.draft_status == DraftStatus.IN_PROGRESS]
    last_pick_by_league: dict[str, datetime] = {}
    if in_progress_ids:
        last_pick_result = await db.execute(
            select(DraftPick.league_id, func.max(DraftPick.drafted_at))
            .where(DraftPick.league_id.in_(in_progress_ids))
            .group_by(DraftPick.league_id)
        )
        last_pick_by_league = {lid: ts for lid, ts in last_pick_result.all()}

    commissioner_ids = {l.commissioner_id for l in leagues}
    users_by_id: dict[str, User] = {}
    if commissioner_ids:
        users_result = await db.execute(select(User).where(User.id.in_(commissioner_ids)))
        users_by_id = {u.id: u for u in users_result.scalars().all()}

    flagged = []
    for l in leagues:
        team_count = len(l.teams)
        flags = []
        if team_count == 0:
            flags.append("no_teams")
        if l.draft_status == DraftStatus.NOT_STARTED and l.created_at.replace(tzinfo=timezone.utc) < never_started_cutoff:
            flags.append("never_started")
        if l.draft_status == DraftStatus.IN_PROGRESS:
            last_pick = last_pick_by_league.get(l.id)
            reference = last_pick.replace(tzinfo=timezone.utc) if last_pick else l.created_at.replace(tzinfo=timezone.utc)
            if reference < stuck_cutoff:
                flags.append("stuck_draft")
        if flags:
            flagged.append({
                "id": l.id,
                "name": l.name,
                "commissioner_username": users_by_id[l.commissioner_id].username if l.commissioner_id in users_by_id else None,
                "commissioner_email": users_by_id[l.commissioner_id].email if l.commissioner_id in users_by_id else None,
                "draft_status": l.draft_status.value,
                "team_count": team_count,
                "created_at": l.created_at,
                "flags": flags,
            })

    return flagged


@router.get("/email-log")
async def get_email_log(
    status: str | None = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Recent outbound-email attempts, newest first -- see
    EmailSendLog's docstring for why this exists. `status` optionally
    filters to one of "sent" / "failed" / "stubbed"."""
    limit = min(limit, 500)
    query = select(EmailSendLog).order_by(EmailSendLog.created_at.desc()).limit(limit)
    if status:
        query = query.where(EmailSendLog.status == status)
    result = await db.execute(query)
    logs = result.scalars().all()
    return [
        {
            "id": e.id,
            "to_email": e.to_email,
            "email_type": e.email_type,
            "subject": e.subject,
            "status": e.status,
            "error_detail": e.error_detail,
            "created_at": e.created_at,
        }
        for e in logs
    ]


@router.get("/system-health")
async def system_health(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Background job status (last success/failure/error per scheduler
    job), data freshness for the Sleeper/ESPN syncs, and draft timer
    watchdog health. See job_run_service.get_system_health."""
    return await get_system_health(db)
