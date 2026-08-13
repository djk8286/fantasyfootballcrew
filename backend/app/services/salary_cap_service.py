"""
Salary-Cap + Contract Leagues (Phase 5).

Bolts a full salary/contract subsystem onto the existing, unmodified
snake draft (draft_manager.py) and the existing, unmodified always-open
waiver/trade system. Entirely opt-in per league
(League.salary_cap_settings["enabled"], default False) and a pure
roster-CONSTRUCTION-time concern -- calculate_week/get_standings never
read anything from this module, confirmed and pinned by a dedicated
regression test (see test_salary_cap_draft.py).

Single-season enforcement only: contract_years/signed_year are stored
for a hypothetical future keeper/dynasty phase, but nothing in this app
rolls a contract forward between fantasy seasons today -- there is no
season-boundary concept anywhere in the codebase (every "season" is
just whatever year integer a caller passes to calculate_week/
get_standings). Dead money is still a real WITHIN-season mechanic:
releasing a multi-year-contract player early charges a separate
DeadMoney entry against the team's cap for the rest of the season.

Salary scale: two-number linear interpolation (top_salary at pick #1 /
best-ranked free agent, bottom_salary at the worst pick slot / a
bottom-tier free agent), not a 200+-row lookup table -- a commissioner
configures exactly 2 numbers. Waiver/free-agent salaries reuse the same
formula, keyed off the player's existing static rank/tier
(draft_manager.get_player_rank_from_list/get_player_tier) instead of a
pick number, then scaled down by waiver_salary_pct -- distinct from but
proportional to the pick-slot scale, since there's no real bid to
derive it from.
"""
from typing import Any
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.league import League
from app.models.team import Team
from app.models.player import Player
from app.models.contract import Contract, DeadMoney

DEFAULT_SALARY_CAP_SETTINGS: dict[str, Any] = {
    "enabled": False,
    "cap_total": 200.0,
    "max_roster_size": 20,
    "top_salary": 50.0,
    "bottom_salary": 1.0,
    "waiver_salary_pct": 0.6,
    "dead_money_pct": 0.5,
    "default_contract_years": 2,   # every draft-time signing
    "waiver_contract_years": 1,    # every waiver/free-agent signing
}


def get_salary_cap_settings(league: League) -> dict[str, Any]:
    merged = dict(DEFAULT_SALARY_CAP_SETTINGS)
    merged.update(league.salary_cap_settings or {})
    return merged


def compute_pick_slot_salary(pick_number: int, total_picks: int, settings: dict) -> float:
    """Linear interpolation from top_salary (pick 1) to bottom_salary
    (last pick), so a commissioner configures exactly 2 numbers instead
    of a 200+-row lookup table. pick_number is 1-indexed."""
    top, bottom = settings["top_salary"], settings["bottom_salary"]
    if total_picks <= 1:
        return round(top, 2)
    frac = (pick_number - 1) / (total_picks - 1)
    return round(top - (top - bottom) * frac, 2)


def compute_waiver_salary(player: Player, settings: dict) -> float:
    """Same interpolation formula as compute_pick_slot_salary, keyed off
    the player's existing static rank (ranked players) or tier (everyone
    else) instead of a draft-pick position, then scaled by
    waiver_salary_pct -- the "distinct but proportional to the pick-slot
    scale" waiver/free-agent scale, since there's no real bid to price a
    free-agent signing off of."""
    # Local import: avoids a module-load-order cycle (draft_manager
    # doesn't import this module, but importing it eagerly at the top of
    # this file would still tie this service's import time to the full
    # weight of draft_manager's own player-ranking-list construction).
    from app.services.draft_manager import get_player_rank_from_list, get_player_tier, _SEQUENTIAL_RANKINGS

    full_name = f"{player.first_name} {player.last_name}"
    rank = get_player_rank_from_list(full_name)
    if rank < 1000:
        base = compute_pick_slot_salary(rank, len(_SEQUENTIAL_RANKINGS), settings)
    else:
        tier = get_player_tier(full_name)  # 1-4, or 5 for unranked
        base = compute_pick_slot_salary(tier, 5, settings)
    return round(base * settings["waiver_salary_pct"], 2)


async def team_cap_summary(team: Team, league: League, db: AsyncSession) -> dict[str, Any]:
    """Active contracts total + dead money total + derived cap space --
    the shape returned by GET /teams/{id}/cap and threaded into AI
    prompts via _salary_summary. Always computable regardless of
    settings["enabled"] (a league considering turning the feature on can
    still see what it would look like); callers decide whether/how to
    gate on `enabled` for their own purposes."""
    settings = get_salary_cap_settings(league)
    contracts = (await db.execute(
        select(Contract).where(Contract.team_id == team.id, Contract.is_active == True)  # noqa: E712
    )).scalars().all()
    contracts_total = round(sum(c.salary for c in contracts), 2)
    dead_money_total = round((await db.execute(
        select(func.sum(DeadMoney.amount)).where(DeadMoney.team_id == team.id)
    )).scalar() or 0.0, 2)
    cap_used = round(contracts_total + dead_money_total, 2)
    return {
        "cap_total": settings["cap_total"],
        "contracts_total": contracts_total,
        "dead_money_total": dead_money_total,
        "cap_used": cap_used,
        "cap_space": round(settings["cap_total"] - cap_used, 2),
        "max_roster_size": settings["max_roster_size"],
        "roster_size": len(team.roster or []),
        "contracts": [
            {"player_id": c.player_id, "salary": c.salary, "contract_years": c.contract_years, "signed_year": c.signed_year}
            for c in contracts
        ],
    }


async def release_player(
    db: AsyncSession, team: Team, player_id: str, league: League, reason: str = "early release"
) -> float:
    """Deactivate a player's active Contract (if any) and record dead
    money if contract_years > 1 at signing (a 1-year deal has no future
    guarantee to break, so releasing it costs nothing). Returns the
    dead-money amount charged (0.0 if none, including when the league
    has no cap enabled at all -- there's simply no active Contract to
    find, so this safely no-ops everywhere).

    Shared by process_waivers' paired-drop path and the standalone
    POST /teams/{id}/release endpoint. Does NOT touch team.roster --
    callers own the roster mutation (and its own CAS write); this only
    ever touches Contract/DeadMoney rows.
    """
    settings = get_salary_cap_settings(league)
    result = await db.execute(
        select(Contract).where(
            Contract.league_id == league.id, Contract.player_id == player_id, Contract.is_active == True  # noqa: E712
        )
    )
    contract = result.scalar_one_or_none()
    if not contract:
        return 0.0
    contract.is_active = False
    dead_amount = round(contract.salary * settings["dead_money_pct"], 2) if contract.contract_years > 1 else 0.0
    if dead_amount:
        db.add(DeadMoney(
            league_id=league.id, team_id=team.id, player_id=player_id,
            contract_id=contract.id, amount=dead_amount, reason=reason,
        ))
    return dead_amount
