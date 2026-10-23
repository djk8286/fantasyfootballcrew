from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select, update
from app.core.database import get_db
from app.core.limiter import limiter
from app.models.team import Team
from app.models.league import DraftStatus, League, LeagueType
from app.models.league_invite import InviteStatus, LeagueInvite
from app.models.league_join_request import JoinRequestStatus, LeagueJoinRequest
from app.models.user import User
from app.schemas.team import TeamCreate, TeamRead, TeamUpdate
from app.api.deps import (
    can_view_rosters,
    get_current_user,
    get_current_user_optional,
    league_view_or_raise,
    require_commissioner,
    require_league_participant,
    require_league_view,
    require_team_league_view,
    require_team_or_league_access,
    user_can_join_league,
)
from app.services.standings_service import get_standings
from app.services.salary_cap_service import get_salary_cap_settings, team_cap_summary, release_player
from app.services.team_claim_service import apply_team_claim
from app.services.team_seats import THEIR_SEAT_TAKEN, lock_league_seats, require_one_live_seat
from app.services.team_news_service import get_team_news, generate_and_save_team_news
from app.services import espn_news_service
from app.core.avatars import validate_avatar_url
from pydantic import BaseModel

router = APIRouter(prefix="/teams", tags=["teams"])


async def _next_conference(league: League, league_id: str, db: AsyncSession) -> str | None:
    """Alternate A/B assignment for conference-type leagues, keeping the two
    sides balanced regardless of the order teams are added in. None for
    standard/two_man leagues, where conference is meaningless."""
    if league.league_type != LeagueType.CONFERENCE:
        return None
    result = await db.execute(select(Team).where(Team.league_id == league_id))
    existing = result.scalars().all()
    a_count = sum(1 for t in existing if t.conference == "A")
    b_count = sum(1 for t in existing if t.conference == "B")
    return "A" if a_count <= b_count else "B"


class BulkAddTeamsRequest(BaseModel):
    count: int = 1
    name_prefix: str = "CPU Team"


@router.post("", response_model=TeamRead, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/hour")
async def create_team(
    request: Request,
    team_data: TeamCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Row lock on the league (no-op on SQLite) serializes concurrent
    # creates/bulk-adds in the same league, so the max_teams count below
    # can't be raced past.
    league_result = await db.execute(
        select(League).where(League.id == team_data.league_id).with_for_update(key_share=True)
    )
    league = league_result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    # Same join rules as claim_team/claim_co_owner: OPEN leagues are open
    # to anyone; INVITE_ONLY/PRIVATE need the commissioner role, an
    # accepted invite or an approved join request.
    if not await user_can_join_league(db, league, current_user):
        raise HTTPException(status_code=403, detail="You need an accepted invite or approved join request to join this league")
    # Dual-Squad teams only exist as linked pairs (made by bulk-add), so a
    # lone team here would have no partner.
    if league.league_type == LeagueType.DUAL_SQUAD:
        raise HTTPException(status_code=400, detail="Dual-Squad leagues don't take new teams directly -- claim an open team instead")
    if league.draft_status != DraftStatus.NOT_STARTED:
        raise HTTPException(status_code=400, detail="Draft has started, claim an open team instead")
    await require_one_live_seat(db, league.id, current_user.id)  # under the league lock

    team_count = await db.scalar(select(func.count(Team.id)).where(Team.league_id == league.id))
    if team_count >= league.max_teams:
        raise HTTPException(status_code=400, detail="League is full")

    validate_avatar_url(team_data.avatar_url)
    # No co_owner_id here (TeamCreate forbids it): a co-owner joins through
    # claim_co_owner or the commissioner's assign_co_owner, both of which
    # apply the league's 2-Man and join rules.
    team = Team(
        name=team_data.name,
        owner_id=current_user.id,
        league_id=team_data.league_id,
        avatar_url=team_data.avatar_url,
        roster=[],
        conference=await _next_conference(league, team_data.league_id, db),
    )
    db.add(team)
    await db.commit()
    await db.refresh(team)
    return team


@router.patch("/{team_id}", response_model=TeamRead)
@limiter.limit("30/hour")
async def update_team(
    request: Request,
    team_id: str,
    update_data: TeamUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update team name, avatar_url, conference or last_words. Owner,
    co-owner, or league commissioner only -- except conference, which is
    commissioner-only (letting owners self-assign could be used to dodge a
    tough conference)."""
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    league_result = await db.execute(select(League).where(League.id == team.league_id))
    league = league_result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    require_team_or_league_access(team, league, current_user)

    if update_data.name is not None:
        team.name = update_data.name
    if update_data.avatar_url is not None:
        validate_avatar_url(update_data.avatar_url)
        team.avatar_url = update_data.avatar_url
    if update_data.conference is not None:
        if current_user.id not in {league.commissioner_id, *(league.co_commissioner_ids or [])}:
            raise HTTPException(status_code=403, detail="Commissioner access required to change conference")
        if update_data.conference not in ("A", "B"):
            raise HTTPException(status_code=400, detail="conference must be 'A' or 'B'")
        team.conference = update_data.conference
    if update_data.last_words is not None:
        # Guillotine (Phase 4) -- only an already-eliminated team can
        # leave "last words". require_team_or_league_access above
        # already covers "must be owner/co-owner/commissioner"; this is
        # the only extra gate this field needs.
        if team.eliminated_week is None:
            raise HTTPException(status_code=400, detail="Only an eliminated team can leave last words")
        team.last_words = update_data.last_words

    await db.commit()
    await db.refresh(team)
    return team


class ReleaseRequest(BaseModel):
    player_id: str


@router.post("/{team_id}/release", response_model=TeamRead)
@limiter.limit("30/hour")
async def release_player_route(
    request: Request,
    team_id: str,
    data: ReleaseRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Unilateral drop -- no Transaction/claim record needed (no
    competing claimants), always open. This is a plain roster drop even
    for non-cap leagues too (a real, generically-useful gap this phase
    happens to close, since there was previously no way to drop a
    player without simultaneously adding one) -- release_player itself
    internally no-ops (no active Contract to find) when the league has
    no cap enabled, so this is safe and harmless everywhere. Owner/
    co-owner only."""
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    league_result = await db.execute(select(League).where(League.id == team.league_id))
    league = league_result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")

    if current_user.id not in {team.owner_id, team.co_owner_id}:
        raise HTTPException(status_code=403, detail="You do not own this team")
    if team.eliminated_week is not None:
        raise HTTPException(status_code=400, detail="This team has been eliminated and can no longer make roster moves")
    if data.player_id not in (team.roster or []):
        raise HTTPException(status_code=400, detail="Player is not on your roster")

    new_roster = [p for p in team.roster if p != data.player_id]
    cas_result = await db.execute(
        update(Team)
        .where(Team.id == team.id, Team.roster_version == team.roster_version)
        .values(roster=new_roster, roster_version=Team.roster_version + 1)
    )
    if cas_result.rowcount == 0:
        raise HTTPException(status_code=409, detail="Your roster changed concurrently -- please retry")

    settings = get_salary_cap_settings(league)
    if settings["enabled"]:
        await release_player(db, team, data.player_id, league)

    await db.commit()
    await db.refresh(team)
    return team


@router.post("/{team_id}/claim-co-owner", response_model=TeamRead)
@limiter.limit("20/hour")
async def claim_co_owner(
    request: Request,
    team_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Self-service claim of the co-owner slot -- the second half of a
    2-Man Team. Mirrors claim_team's pattern (no invite link/email needed,
    just needs someone to know the team). Requires the slot to be open and
    the claimant not to already be the owner."""
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    league_result = await db.execute(select(League).where(League.id == team.league_id))
    league = league_result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    await lock_league_seats(db, league.id, team)
    # Visibility gate -- see user_can_join_league's docstring. Without
    # this, INVITE_ONLY/PRIVATE leagues were only "private" in the
    # discovery listing, not in who could actually claim a slot.
    if not await user_can_join_league(db, league, current_user):
        raise HTTPException(status_code=403, detail="You need an accepted invite or approved join request to join this league")

    if league.league_type != LeagueType.TWO_MAN:
        raise HTTPException(status_code=400, detail="Co-owners are only available in 2-Man Team leagues")
    if team.is_cpu:
        raise HTTPException(status_code=400, detail="Claim this team as owner first, not co-owner")
    if team.eliminated_week is not None:
        raise HTTPException(status_code=400, detail="This team has been eliminated and can no longer take a co-owner")
    if team.co_owner_id:
        raise HTTPException(status_code=400, detail="This team already has a co-owner")
    if current_user.id == team.owner_id:
        raise HTTPException(status_code=400, detail="You already own this team")
    await require_one_live_seat(db, league.id, current_user.id, joining=team)

    team.co_owner_id = current_user.id
    await db.commit()
    await db.refresh(team)
    return team


@router.post("/{team_id}/claim", response_model=TeamRead)
@limiter.limit("20/hour")
async def claim_team(
    request: Request,
    team_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Claim a CPU team as the authenticated user."""
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    league_result = await db.execute(select(League).where(League.id == team.league_id))
    league = league_result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    await lock_league_seats(db, league.id, team)
    if not await user_can_join_league(db, league, current_user):
        raise HTTPException(status_code=403, detail="You need an accepted invite or approved join request to join this league")

    if not team.is_cpu:
        raise HTTPException(status_code=400, detail="Team is already owned by a user")

    await apply_team_claim(db, team, league, current_user)
    await db.commit()
    await db.refresh(team)
    return team


class AssignTeamRequest(BaseModel):
    # Username or email -- whichever the commissioner has on hand for
    # the person they're assigning. Same "look up either" convenience
    # as nothing else in this app currently offers (co-commissioner
    # add/remove take a raw user_id instead), but a commissioner
    # assigning teams realistically knows a name or email, not a UUID.
    identifier: str


async def _find_user_by_identifier(db: AsyncSession, identifier: str) -> User | None:
    result = await db.execute(select(User).where((User.username == identifier) | (User.email == identifier)))
    return result.scalar_one_or_none()


async def _get_team_and_league_or_404(team_id: str, db: AsyncSession) -> tuple[Team, League]:
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    league_result = await db.execute(select(League).where(League.id == team.league_id))
    league = league_result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    return team, league


async def _revoke_league_access(db: AsyncSession, league: League, user_id: str, removed_from: Team) -> None:
    """After a commissioner removes someone from a team, withdraw the
    accepted invite / approved join request that let them in, so they
    need a fresh invite (or approval) to join again. Skipped while they
    still hold a seat on another team in the league."""
    other_seat = await db.execute(
        select(Team.id).where(
            Team.league_id == league.id,
            Team.id != removed_from.id,
            (Team.owner_id == user_id) | (Team.co_owner_id == user_id),
        ).limit(1)
    )
    if other_seat.first() is not None:
        return
    await db.execute(
        update(LeagueInvite)
        .where(
            LeagueInvite.league_id == league.id,
            LeagueInvite.accepted_by_user_id == user_id,
            LeagueInvite.status == InviteStatus.ACCEPTED,
        )
        .values(status=InviteStatus.REVOKED)
    )
    await db.execute(
        update(LeagueJoinRequest)
        .where(
            LeagueJoinRequest.league_id == league.id,
            LeagueJoinRequest.requested_by_user_id == user_id,
            LeagueJoinRequest.status == JoinRequestStatus.APPROVED,
        )
        .values(status=JoinRequestStatus.DENIED)
    )


@router.post("/{team_id}/remove-owner", response_model=TeamRead)
@limiter.limit("30/hour")
async def remove_owner(
    request: Request,
    team_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Commissioner-only. If there's a co-owner, they're promoted to
    owner rather than leaving the team ownerless -- flipping back to
    CPU only happens when nobody's left managing it at all. Same
    ownerless-team-becomes-CPU shape self-service account deletion
    already produces elsewhere."""
    team, league = await _get_team_and_league_or_404(team_id, db)
    require_commissioner(league, current_user)
    await lock_league_seats(db, league.id, team)
    await db.refresh(league)  # re-check rights against the locked, current league
    require_commissioner(league, current_user)

    if team.owner_id is None:
        raise HTTPException(status_code=400, detail="This team has no owner to remove")

    removed_user_id = team.owner_id
    if team.co_owner_id:
        team.owner_id = team.co_owner_id
        team.co_owner_id = None
    else:
        team.owner_id = None
        team.is_cpu = True
    await _revoke_league_access(db, league, removed_user_id, team)

    await db.commit()
    await db.refresh(team)
    return team


@router.post("/{team_id}/remove-co-owner", response_model=TeamRead)
@limiter.limit("30/hour")
async def remove_co_owner(
    request: Request,
    team_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Commissioner-only. Leaves the primary owner untouched."""
    team, league = await _get_team_and_league_or_404(team_id, db)
    require_commissioner(league, current_user)
    await lock_league_seats(db, league.id, team)
    await db.refresh(league)  # re-check rights against the locked, current league
    require_commissioner(league, current_user)

    if team.co_owner_id is None:
        raise HTTPException(status_code=400, detail="This team has no co-owner to remove")

    removed_user_id = team.co_owner_id
    team.co_owner_id = None
    await _revoke_league_access(db, league, removed_user_id, team)
    await db.commit()
    await db.refresh(team)
    return team


@router.post("/{team_id}/assign-owner", response_model=TeamRead)
@limiter.limit("30/hour")
async def assign_owner(
    request: Request,
    team_id: str,
    data: AssignTeamRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Commissioner-only equivalent of claim_team, on someone else's
    behalf -- requires the team to currently be CPU (same as self-claim)
    so this can't silently steamroll an existing real owner; remove_owner
    first if that's actually what's wanted. Bypasses user_can_join_league
    entirely -- a commissioner assigning a team is itself the
    authorization, same reasoning accept_invite's auto-claim doesn't
    re-check it either."""
    team, league = await _get_team_and_league_or_404(team_id, db)
    require_commissioner(league, current_user)
    await lock_league_seats(db, league.id, team)

    if not team.is_cpu:
        raise HTTPException(status_code=400, detail="Team is already owned -- remove the current owner first")

    target = await _find_user_by_identifier(db, data.identifier.strip())
    if not target:
        raise HTTPException(status_code=404, detail=f"No user found matching {data.identifier!r}")

    await apply_team_claim(db, team, league, target, THEIR_SEAT_TAKEN)
    await db.commit()
    await db.refresh(team)
    return team


@router.post("/{team_id}/assign-co-owner", response_model=TeamRead)
@limiter.limit("30/hour")
async def assign_co_owner(
    request: Request,
    team_id: str,
    data: AssignTeamRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Commissioner-only equivalent of claim_co_owner, on someone else's
    behalf."""
    team, league = await _get_team_and_league_or_404(team_id, db)
    require_commissioner(league, current_user)
    await lock_league_seats(db, league.id, team)

    if league.league_type != LeagueType.TWO_MAN:
        raise HTTPException(status_code=400, detail="Co-owners are only available in 2-Man Team leagues")
    if team.is_cpu:
        raise HTTPException(status_code=400, detail="Assign this team's owner first, not a co-owner")
    if team.co_owner_id:
        raise HTTPException(status_code=400, detail="This team already has a co-owner -- remove them first")

    target = await _find_user_by_identifier(db, data.identifier.strip())
    if not target:
        raise HTTPException(status_code=404, detail=f"No user found matching {data.identifier!r}")
    if target.id == team.owner_id:
        raise HTTPException(status_code=400, detail="That person already owns this team")
    await require_one_live_seat(db, league.id, target.id, THEIR_SEAT_TAKEN, joining=team)

    team.co_owner_id = target.id
    await db.commit()
    await db.refresh(team)
    return team


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("20/hour")
async def delete_team(
    request: Request,
    team_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a team (league commissioner only)."""
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    league_result = await db.execute(select(League).where(League.id == team.league_id))
    league = league_result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    if current_user.id not in {league.commissioner_id, *(league.co_commissioner_ids or [])}:
        raise HTTPException(status_code=403, detail="Commissioner access required")
    await lock_league_seats(db, league.id, team)
    await db.refresh(league)  # re-check rights against the locked, current league
    require_commissioner(league, current_user)

    # Dual-Squad (Phase 7): clear the partner's pointer first so deleting
    # one half of a pair doesn't leave a dangling partner_team_id (or hit
    # an FK error on Postgres, which has no ondelete configured here,
    # same as every other FK column in this codebase).
    if team.partner_team_id:
        partner_result = await db.execute(select(Team).where(Team.id == team.partner_team_id))
        partner = partner_result.scalar_one_or_none()
        if partner:
            partner.partner_team_id = None

    # Deleting a team removes its managers just like remove-owner does.
    for user_id in {team.owner_id, team.co_owner_id} - {None}:
        await _revoke_league_access(db, league, user_id, team)
    await db.delete(team)
    await db.commit()
    return None


@router.post("/bulk-add/{league_id}", status_code=status.HTTP_201_CREATED)
@limiter.limit("10/hour")
async def bulk_add_cpu_teams(
    request: Request,
    league_id: str,
    req: BulkAddTeamsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fill a league's empty slots with CPU-controlled teams (commissioner only)."""
    # Check league exists and get current team count. Locked like
    # create_team so the two can't both fill the last slot at once.
    result = await db.execute(select(League).where(League.id == league_id).with_for_update(key_share=True))
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    if current_user.id not in {league.commissioner_id, *(league.co_commissioner_ids or [])}:
        raise HTTPException(status_code=403, detail="Commissioner access required")

    result = await db.execute(select(Team).where(Team.league_id == league_id))
    existing = result.scalars().all()
    current_count = len(existing)
    max_teams = league.max_teams
    available_slots = max_teams - current_count

    if available_slots <= 0:
        raise HTTPException(status_code=400, detail=f"League is full ({current_count}/{max_teams})")

    count = min(req.count, available_slots)

    # Dual-Squad (Phase 7): teams only ever come in linked pairs -- an
    # odd leftover slot from a partially-full league is simply left
    # unfilled by this call rather than creating a half-pair (max_teams
    # is already validated even/>=4 for DUAL_SQUAD, see create_league/
    # update_league, so this should be rare in practice).
    is_dual_squad = league.league_type == LeagueType.DUAL_SQUAD
    if is_dual_squad:
        count = count - (count % 2)

    # Track A/B balance locally rather than re-querying per team -- teams
    # created earlier in this same loop aren't committed yet, so a query
    # wouldn't see them.
    is_conference = league.league_type == LeagueType.CONFERENCE
    a_count = sum(1 for t in existing if t.conference == "A")
    b_count = sum(1 for t in existing if t.conference == "B")

    created = []
    i = 0
    while i < count:
        team_num = current_count + i + 1
        conference = None
        if is_conference:
            conference = "A" if a_count <= b_count else "B"
            if conference == "A":
                a_count += 1
            else:
                b_count += 1
        team = Team(
            name=f"{req.name_prefix} {team_num}",
            owner_id=None,
            league_id=league_id,
            roster=[],
            is_cpu=True,
            conference=conference,
        )
        db.add(team)

        if is_dual_squad:
            partner = Team(
                name=f"{req.name_prefix} {team_num + 1}",
                owner_id=None,
                league_id=league_id,
                roster=[],
                is_cpu=True,
                conference=conference,
            )
            db.add(partner)
            # Need real IDs (Team.id's default is a Python-side callable,
            # only populated on flush) before cross-linking.
            await db.flush()
            team.partner_team_id = partner.id
            partner.partner_team_id = team.id
            created.extend([team, partner])
            i += 2
        else:
            created.append(team)
            i += 1

    await db.commit()
    for t in created:
        await db.refresh(t)

    return {
        "message": f"Added {len(created)} CPU teams",
        "teams": [{"id": t.id, "name": t.name, "is_cpu": t.is_cpu} for t in created],
        "total_teams": current_count + len(created),
        "max_teams": max_teams,
    }


async def _with_live_records(teams: list[Team], league_id: str, db: AsyncSession) -> list[TeamRead]:
    """Team.wins/points_for are never written, so the record comes from
    standings. The rows themselves are left untouched."""
    rows = {r["team_id"]: r for r in await get_standings(league_id, db)} if teams else {}
    out = []
    for t in teams:
        read = TeamRead.model_validate(t)
        row = rows.get(t.id)
        if row:
            read = read.model_copy(update={k: row[k] for k in ("wins", "losses", "ties", "points_for", "points_against")})
        out.append(read)
    return out


async def _hide_rosters_unless_visible(reads: list[TeamRead], league_id: str, viewer: User | None,
                                       db: AsyncSession) -> list[TeamRead]:
    """PRIVATE league and the viewer isn't a member: team names and records
    stay readable (invitees need them to pick a team to claim), the roster
    comes back null. See deps.can_view_rosters."""
    league = (await db.execute(select(League).where(League.id == league_id))).scalar_one_or_none()
    if league is None or await can_view_rosters(league, viewer, db):
        return reads
    return [r.model_copy(update={"roster": None}) for r in reads]


async def _team_league_rosters_visible_or_raise(team_id: str, viewer: User | None, db: AsyncSession) -> tuple[Team, League]:
    team = (await db.execute(select(Team).where(Team.id == team_id))).scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    league = (await db.execute(select(League).where(League.id == team.league_id))).scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    await league_view_or_raise(league, viewer, db)
    return team, league


@router.get("/league/{league_id}", response_model=list[TeamRead], dependencies=[Depends(require_league_view)])
async def get_league_teams(
    league_id: str,
    db: AsyncSession = Depends(get_db),
    viewer: User | None = Depends(get_current_user_optional),
):
    result = await db.execute(select(Team).where(Team.league_id == league_id))
    teams = result.scalars().all()
    return await _hide_rosters_unless_visible(await _with_live_records(list(teams), league_id, db), league_id, viewer, db)


@router.get("/{team_id}", response_model=TeamRead, dependencies=[Depends(require_team_league_view)])
async def get_team(
    team_id: str,
    db: AsyncSession = Depends(get_db),
    viewer: User | None = Depends(get_current_user_optional),
):
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return (await _hide_rosters_unless_visible(await _with_live_records([team], team.league_id, db), team.league_id, viewer, db))[0]


@router.get("/{team_id}/cap")
async def get_team_cap(
    team_id: str,
    db: AsyncSession = Depends(get_db),
    viewer: User | None = Depends(get_current_user_optional),
):
    """A team's active contracts + dead money + derived cap space.
    Ungated public read, mirroring get_team's own unauthenticated-read
    house style. Always available regardless of the league's
    salary_cap_settings.enabled (cheap, informative even for a league
    considering turning the feature on later -- cap_total will just be
    the default and every contracts list will be empty) -- gating on
    `enabled` is a frontend rendering decision, not an API-serving one.
    Contracts list the roster, so PRIVATE leagues are members only."""
    team, league = await _team_league_rosters_visible_or_raise(team_id, viewer, db)
    return await team_cap_summary(team, league, db)


@router.get("/{team_id}/news")
async def get_team_player_news(
    team_id: str,
    db: AsyncSession = Depends(get_db),
    viewer: User | None = Depends(get_current_user_optional),
):
    """This team's player news: the daily digest (see team_news_service.py)
    plus the real ESPN articles about its rostered players from the last
    week, read live from player_news so links are as fresh as the last
    ESPN poll even when the digest is a day old. Ungated public read.
    404 only when the team doesn't exist. "Nothing yet" is a normal empty
    200 (content null, no articles): it used to 404, which every visitor's
    console logged as a failed request on fresh teams (QA 2026-10-19).
    It's news about the roster, so PRIVATE leagues are members only."""
    team, _ = await _team_league_rosters_visible_or_raise(team_id, viewer, db)
    news = await get_team_news(team_id, db)
    recent = await espn_news_service.recent_news_for_players(list(team.roster or []), db, days=7, limit=60)
    return {
        "team_id": team_id,
        "content": news.content if news else None,
        "updated_at": news.updated_at if news else None,
        "articles": espn_news_service.serialize_grouped(recent, limit=10),
    }


@router.post("/{team_id}/news/generate")
@limiter.limit("10/hour")
async def generate_team_player_news_now(
    request: Request,
    team_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manual fallback for the scheduler's once-daily refresh: the very
    first generation, or a fresher read before the next tick. It spends AI
    budget, so only the league's own people may run it -- a team owner or
    co-owner anywhere in the league, or its commissioner (403 for anyone
    else, 401/403 first for a PRIVATE league they can't see)."""
    team, league = await _team_league_rosters_visible_or_raise(team_id, current_user, db)
    await require_league_participant(league, current_user, db)
    news = await generate_and_save_team_news(team, db)
    if not news:
        raise HTTPException(status_code=422, detail="This team has an empty roster -- nothing to report news about")
    return {
        "team_id": news.team_id, "content": news.content, "updated_at": news.updated_at,
    }
