"""
Read-only dev/management dashboard for David and anyone he grants
is_admin to (see User.is_admin, deps.require_admin). Deliberately
read-only -- no delete/edit endpoints here. The 2026-09-08 incident this
exists to prevent wasn't a bad delete so much as a delete made without
knowing who was actually using the app; the fix for that is visibility,
not a more convenient delete button. Destructive league/user cleanup
stays a deliberate one-off script against prod, same as it's always
been -- see [[ffc-beta-draft-readiness]] in project memory.
"""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.models.user import User
from app.models.league import League, DraftStatus
from app.models.team import Team
from app.models.draft import Draft, DraftPick, DraftRunStatus
from app.models.ai_usage_event import AIUsageEvent
from app.models.email_send_log import EmailSendLog
from app.api.deps import require_admin

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


@router.get("/users")
async def list_users(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Every account, newest first. Includes email -- this endpoint is
    already admin-gated, unlike the public-facing UserPublic schema
    (GET /users/{id}) that deliberately withholds it."""
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "provider": u.provider,
            "email_verified": u.email_verified,
            "is_admin": u.is_admin,
            "created_at": u.created_at,
        }
        for u in users
    ]


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
