"""One player, one roster per league.

Team.roster is a JSON list per team, so the database can't enforce
"a player is on at most one roster in a league" by itself. Every path
that ADDS a player to a roster (waiver grants, draft picks) instead:

1. takes a row lock on the league (SELECT ... FOR UPDATE on Postgres),
   which serializes roster additions within that league, then
2. re-reads every team's roster in the league (populate_existing, so no
   stale identity-map copy) and refuses a player who is already on one,
3. and still writes the roster with the existing roster_version
   compare-and-swap.

The lock is held until the caller's commit/rollback. Lock order is
always league -> draft/team rows' own CAS, never the reverse, so these
paths can't deadlock each other. Trades only move players between the
two teams involved (both sides are verified to hold what they give), so
they can't create a duplicate and don't take this lock.

QA 2026-10-19: a waiver claim for Josh Allen, submitted during the draft
while he was still undrafted, was granted after the draft, when Team 5
had already drafted him: processing never re-checked that the player was
still a free agent, and the draft never checked waiver-added players.
"""
from __future__ import annotations

from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.league import League
from app.models.team import Team


class PlayerAlreadyRostered(ValueError):
    def __init__(self, player_id: str, team: Team):
        self.player_id = player_id
        self.team = team
        super().__init__(f"Player is already on {team.name}'s roster in this league")


async def lock_league_rosters(db: AsyncSession, league_id: str) -> None:
    """Row-lock the league for the rest of this transaction (no-op on SQLite)."""
    await db.execute(select(League.id).where(League.id == league_id).with_for_update())


async def league_teams_fresh(db: AsyncSession, league_id: str) -> list[Team]:
    result = await db.execute(
        select(Team).where(Team.league_id == league_id).execution_options(populate_existing=True)
    )
    return list(result.scalars().all())


def roster_owner_map(teams: Iterable[Team]) -> dict[str, Team]:
    """player_id -> the team rostering him (first one, if a legacy duplicate)."""
    owners: dict[str, Team] = {}
    for t in teams:
        for pid in t.roster or []:
            owners.setdefault(pid, t)
    return owners


async def rostered_player_ids(db: AsyncSession, league_id: str) -> set[str]:
    return set(roster_owner_map(await league_teams_fresh(db, league_id)))


async def assert_free_agent(db: AsyncSession, league_id: str, player_id: str, *, lock: bool = True) -> list[Team]:
    """Lock the league (unless the caller already did) and raise
    PlayerAlreadyRostered if any team in it rosters player_id. Returns the
    freshly read teams for the caller's own use."""
    if lock:
        await lock_league_rosters(db, league_id)
    teams = await league_teams_fresh(db, league_id)
    owner = roster_owner_map(teams).get(player_id)
    if owner is not None:
        raise PlayerAlreadyRostered(player_id, owner)
    return teams
