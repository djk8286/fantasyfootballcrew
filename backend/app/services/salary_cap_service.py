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
best-produced free agent, bottom_salary at the worst pick slot / a
zero-production free agent), not a 200+-row lookup table -- a
commissioner configures exactly 2 numbers. Waiver/free-agent salaries
reuse the same formula, keyed off the player's own real last-season
production (calculate_player_score against last_season_stats,
DEFAULT_SCORING, normalized against WAIVER_SALARY_SCALE_MAX -- see
compute_waiver_salary) instead of a pick number, then scaled down by
waiver_salary_pct -- distinct from but proportional to the pick-slot
scale, since there's no real bid to derive it from.
"""
from typing import Any
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.league import League
from app.models.team import Team
from app.models.player import Player
from app.models.contract import Contract, DeadMoney
from app.services.scoring_engine import calculate_player_score, DEFAULT_SCORING

# Reference "top of the scale" point total standing in for pick #1 in
# compute_pick_slot_salary's interpolation -- there's no natural draft-
# pick-style rank to place a free agent at without scoring the entire
# player pool on every single valuation call, so this normalizes against
# a fixed point total instead. Roughly a standout full-season starter
# under DEFAULT_SCORING (see test_scoring_engine.py's season-total
# examples, e.g. a 107-point IDP season) -- a deliberately generous
# ceiling so only truly elite production reaches top_salary.
WAIVER_SALARY_SCALE_MAX = 350.0

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
    """Same top/bottom-salary interpolation formula as
    compute_pick_slot_salary, but keyed off the player's own real last-
    season production (calculate_player_score against last_season_stats)
    instead of draft_manager's static name/tier list (removed -- see
    draft_manager.build_rank_by_id for why it was stale and wrong),
    normalized against WAIVER_SALARY_SCALE_MAX in place of a rank
    position, then scaled by waiver_salary_pct -- the "distinct but
    proportional to the pick-slot scale" waiver/free-agent price, since
    there's no real bid to derive it from. No stats yet (a rookie/newly-
    synced player) scores 0 and lands at bottom_salary, same as the old
    system's "unranked" fallback did."""
    score = calculate_player_score(player.last_season_stats or {}, DEFAULT_SCORING, player.position)
    frac = min(max(score, 0.0) / WAIVER_SALARY_SCALE_MAX, 1.0)
    top, bottom = settings["top_salary"], settings["bottom_salary"]
    base = round(bottom + (top - bottom) * frac, 2)
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
