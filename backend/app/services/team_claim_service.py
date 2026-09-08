"""
Shared "take over a CPU team" logic -- used by both a user picking a
specific team (teams.py's claim_team) and auto-claiming one on invite
accept (invites.py's accept_invite). Extracted here once accept_invite
needed the exact same ownership/rename/Dual-Squad-mirror behavior
claim_team already had, rather than duplicating it.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.team import Team
from app.models.league import League, LeagueType
from app.models.user import User


async def apply_team_claim(db: AsyncSession, team: Team, league: League, user: User) -> None:
    """Mutates `team` (and its Dual-Squad partner, if any) in place --
    caller commits. Does NOT check team.is_cpu or user_can_join_league;
    a caller claiming a specific team the user asked for (claim_team)
    still needs to check those itself first."""
    team.owner_id = user.id
    team.is_cpu = False
    # Personalize the placeholder name ("CPU Team 3", etc.) the moment a
    # real person takes it over -- rename UI (PATCH /teams/{id}) lets them
    # change it again later if they want something else.
    team.name = f"{user.username}'s Team"

    # Dual-Squad (Phase 7): claiming one team of a linked pair also
    # auto-claims its still-CPU partner as the SAME owner, atomically.
    # Only mirrors the OWNER; co-owner is deliberately NOT auto-mirrored
    # (a manager might want a different or no co-owner per team). If the
    # partner was already independently claimed by someone else (a
    # race), this just leaves the pair split between two owners rather
    # than erroring.
    if league.league_type == LeagueType.DUAL_SQUAD and team.partner_team_id:
        partner_result = await db.execute(select(Team).where(Team.id == team.partner_team_id))
        partner = partner_result.scalar_one_or_none()
        if partner and partner.is_cpu:
            partner.owner_id = user.id
            partner.is_cpu = False


async def find_open_team(db: AsyncSession, league_id: str) -> Team | None:
    """The first still-CPU team in a league, in a stable order (team
    name -- these are created "CPU Team 1", "CPU Team 2", ... in order,
    so this reliably hands out the lowest-numbered open slot rather than
    whatever order Postgres happens to return rows in). None if the
    league is already full of real owners."""
    result = await db.execute(
        select(Team).where(Team.league_id == league_id, Team.is_cpu == True).order_by(Team.name)  # noqa: E712
    )
    return result.scalars().first()
