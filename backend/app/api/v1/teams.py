from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.core.database import get_db
from app.models.team import Team
from app.models.league import League, LeagueType
from app.models.user import User
from app.schemas.team import TeamCreate, TeamRead, TeamUpdate
from app.api.deps import get_current_user, require_team_or_league_access, user_can_join_league
from app.services.salary_cap_service import get_salary_cap_settings, team_cap_summary, release_player
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
async def create_team(
    team_data: TeamCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    league_result = await db.execute(select(League).where(League.id == team_data.league_id))
    league = league_result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")

    team = Team(
        name=team_data.name,
        owner_id=current_user.id,
        co_owner_id=team_data.co_owner_id,
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
async def update_team(
    team_id: str,
    update_data: TeamUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update team name, avatar_url, co_owner_id, or conference. Owner,
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
        team.avatar_url = update_data.avatar_url
    if update_data.co_owner_id is not None:
        team.co_owner_id = update_data.co_owner_id
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
async def release_player_route(
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
async def claim_co_owner(
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
    # Visibility gate -- see user_can_join_league's docstring. Without
    # this, INVITE_ONLY/PRIVATE leagues were only "private" in the
    # discovery listing, not in who could actually claim a slot.
    if not await user_can_join_league(db, league, current_user):
        raise HTTPException(status_code=403, detail="You need an accepted invite or approved join request to join this league")

    if team.is_cpu:
        raise HTTPException(status_code=400, detail="Claim this team as owner first, not co-owner")
    if team.eliminated_week is not None:
        raise HTTPException(status_code=400, detail="This team has been eliminated and can no longer take a co-owner")
    if team.co_owner_id:
        raise HTTPException(status_code=400, detail="This team already has a co-owner")
    if current_user.id == team.owner_id:
        raise HTTPException(status_code=400, detail="You already own this team")

    team.co_owner_id = current_user.id
    await db.commit()
    await db.refresh(team)
    return team


@router.post("/{team_id}/claim", response_model=TeamRead)
async def claim_team(
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
    if not await user_can_join_league(db, league, current_user):
        raise HTTPException(status_code=403, detail="You need an accepted invite or approved join request to join this league")

    if not team.is_cpu:
        raise HTTPException(status_code=400, detail="Team is already owned by a user")

    team.owner_id = current_user.id
    team.is_cpu = False

    # Dual-Squad (Phase 7): claiming one team of a linked pair also
    # auto-claims its still-CPU partner as the SAME owner, atomically --
    # reuses this existing "Claim CPU team" button rather than adding a
    # second endpoint. Only mirrors the OWNER; claim_co_owner is
    # deliberately NOT auto-mirrored (a manager might want a different
    # or no co-owner per team). If the partner was already independently
    # claimed by someone else (a race), this just leaves the pair split
    # between two owners rather than erroring.
    if league.league_type == LeagueType.DUAL_SQUAD and team.partner_team_id:
        partner_result = await db.execute(select(Team).where(Team.id == team.partner_team_id))
        partner = partner_result.scalar_one_or_none()
        if partner and partner.is_cpu:
            partner.owner_id = current_user.id
            partner.is_cpu = False

    await db.commit()
    await db.refresh(team)
    return team


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(
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

    # Dual-Squad (Phase 7): clear the partner's pointer first so deleting
    # one half of a pair doesn't leave a dangling partner_team_id (or hit
    # an FK error on Postgres, which has no ondelete configured here,
    # same as every other FK column in this codebase).
    if team.partner_team_id:
        partner_result = await db.execute(select(Team).where(Team.id == team.partner_team_id))
        partner = partner_result.scalar_one_or_none()
        if partner:
            partner.partner_team_id = None

    await db.delete(team)
    await db.commit()
    return None


@router.post("/bulk-add/{league_id}", status_code=status.HTTP_201_CREATED)
async def bulk_add_cpu_teams(
    league_id: str,
    req: BulkAddTeamsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fill a league's empty slots with CPU-controlled teams (commissioner only)."""
    # Check league exists and get current team count
    result = await db.execute(select(League).where(League.id == league_id))
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    if current_user.id not in {league.commissioner_id, *(league.co_commissioner_ids or [])}:
        raise HTTPException(status_code=403, detail="Commissioner access required")

    result = await db.execute(select(Team).where(Team.league_id == league_id))
    existing = result.scalars().all()
    current_count = len(existing)
    max_teams = league.max_teams or 32
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


@router.get("/league/{league_id}", response_model=list[TeamRead])
async def get_league_teams(league_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Team).where(Team.league_id == league_id))
    teams = result.scalars().all()
    return teams


@router.get("/{team_id}", response_model=TeamRead)
async def get_team(team_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


@router.get("/{team_id}/cap")
async def get_team_cap(team_id: str, db: AsyncSession = Depends(get_db)):
    """A team's active contracts + dead money + derived cap space.
    Ungated public read, mirroring get_team's own unauthenticated-read
    house style. Always available regardless of the league's
    salary_cap_settings.enabled (cheap, informative even for a league
    considering turning the feature on later -- cap_total will just be
    the default and every contracts list will be empty) -- gating on
    `enabled` is a frontend rendering decision, not an API-serving one."""
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    league_result = await db.execute(select(League).where(League.id == team.league_id))
    league = league_result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    return await team_cap_summary(team, league, db)
