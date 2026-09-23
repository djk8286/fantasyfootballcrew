"""
Shared account-deletion cleanup -- extracted (2026-09-22) from
users.delete_me so the new admin-triggered deletion (DELETE
/admin/users/{user_id}) runs the EXACT same cleanup, not a
hand-duplicated second copy of an ~80-line, easy-to-get-wrong routine.

Permanently and irreversibly deletes a User (hard-delete, not a soft/
anonymize -- see the Production Quality Hardening plan's account-
deletion research: zero soft-delete precedent anywhere in this
codebase, and hard-delete gets session invalidation for free via
get_current_user's existing "user row is gone -> 401" check).

Callers are responsible for their own authorization (a password check
for self-service, admin-gate for the admin endpoint) and for
committing -- this function only stages deletes/updates inside the
caller's own transaction, so a block (409) below leaves nothing
persisted either way.
"""
from fastapi import HTTPException
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.league import League
from app.models.team import Team
from app.models.league_invite import LeagueInvite
from app.models.league_join_request import LeagueJoinRequest
from app.models.notification import Notification
from app.models.password_reset_token import PasswordResetToken
from app.models.email_verification_token import EmailVerificationToken
from app.models.commissioner_digest import CommissionerDigest


async def delete_user_account(db: AsyncSession, user: User) -> None:
    """Pre-cleanup order matters: leagues/teams are resolved BEFORE the
    User row is deleted, all inside this one call's (uncommitted)
    transaction, so a block (409) below leaves nothing staged."""
    # 1. Leagues this user commissions: auto-transfer to another real
    #    (non-CPU) team owner if one exists. If they're the sole real
    #    member, block rather than silently orphaning the league -- the
    #    caller (a self-service user, or an admin) needs to transfer
    #    commissioner rights or delete the league first (admins: via
    #    DELETE /admin/leagues/{id}).
    result = await db.execute(select(League).where(League.commissioner_id == user.id))
    for league in result.scalars().all():
        teams_result = await db.execute(
            select(Team).where(
                Team.league_id == league.id,
                Team.is_cpu == False,  # noqa: E712
                Team.owner_id != user.id,
            )
        )
        successor = teams_result.scalars().first()
        if not successor:
            raise HTTPException(
                status_code=409,
                detail=(
                    f'{user.username} is the sole real member of "{league.name}" -- '
                    "transfer commissioner rights to someone else or delete the "
                    "league before deleting this account."
                ),
            )
        league.commissioner_id = successor.owner_id

    # 2. Co-commissioner rights are a plain JSON list on League, not an
    #    FK -- no RESTRICT risk, but a stale user_id left behind would be
    #    a silent correctness bug (e.g. still showing up in commissioner
    #    tooling). Scrub it everywhere, not just leagues they own.
    all_leagues_result = await db.execute(select(League))
    for league in all_leagues_result.scalars().all():
        if league.co_commissioner_ids and user.id in league.co_commissioner_ids:
            league.co_commissioner_ids.remove(user.id)

    # 3. Teams owned/co-owned: null the ownership (same nullable columns
    #    claim_team already relies on), flip back to a CPU team -- the
    #    identical shape bulk_add_cpu_teams already produces -- once no
    #    real owner is left on either side.
    teams_result = await db.execute(
        select(Team).where((Team.owner_id == user.id) | (Team.co_owner_id == user.id))
    )
    for team in teams_result.scalars().all():
        if team.owner_id == user.id:
            team.owner_id = None
        if team.co_owner_id == user.id:
            team.co_owner_id = None
        if team.owner_id is None and team.co_owner_id is None:
            team.is_cpu = True

    # 4. Everything else pointing at users.id: null attribution on rows
    #    that outlive the account (invites/join-decisions/digests --
    #    other people's data, not this account's own), hard-delete rows
    #    that ARE this account's own (their pending join requests,
    #    notifications, auth tokens).
    await db.execute(
        update(LeagueInvite).where(LeagueInvite.invited_by_user_id == user.id)
        .values(invited_by_user_id=None)
    )
    await db.execute(
        update(LeagueInvite).where(LeagueInvite.accepted_by_user_id == user.id)
        .values(accepted_by_user_id=None)
    )
    await db.execute(
        update(LeagueJoinRequest).where(LeagueJoinRequest.decided_by_user_id == user.id)
        .values(decided_by_user_id=None)
    )
    await db.execute(
        update(CommissionerDigest).where(CommissionerDigest.generated_by == user.id)
        .values(generated_by=None)
    )
    await db.execute(delete(LeagueJoinRequest).where(LeagueJoinRequest.requested_by_user_id == user.id))
    await db.execute(delete(Notification).where(Notification.user_id == user.id))
    await db.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
    await db.execute(delete(EmailVerificationToken).where(EmailVerificationToken.user_id == user.id))

    # 5. The account itself. get_current_user 401s on the very next
    #    request for any token tied to this id -- no separate session-
    #    invalidation step needed.
    await db.delete(user)
