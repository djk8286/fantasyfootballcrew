from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.scoring import ScoringConfig
from app.models.player import Player
from app.models.league import League
from app.services.scoring_engine import (
    calculate_player_score,
    calculate_weekly_score,
    calculate_optimal_lineup,
    validate_scoring_config,
    DEFAULT_SCORING,
)
from app.services.sleeper_sync import fetch_weekly_stats
from app.schemas.scoring import (
    ScoringCalculatorInput,
    ScoringCalculatorResult,
    WeeklyScoringInput,
    WeeklyScoringResult,
    PlayerBreakdown,
    OptimalLineupInput,
    OptimalLineupResult,
    OptimalLineupSlot,
    SleeperWeeklyScoringInput,
)
from pydantic import BaseModel
from typing import Optional, Dict

router = APIRouter(prefix="/scoring", tags=["scoring"])


class ScoringConfigCreate(BaseModel):
    league_id: str
    category: str
    stat_name: str
    points_per_unit: float
    is_active: bool = True


# ─── CRUD endpoints ──────────────────────────────────────────────────


@router.post("/", status_code=201)
async def create_scoring_config(config: ScoringConfigCreate, db: AsyncSession = Depends(get_db)):
    sc = ScoringConfig(
        league_id=config.league_id,
        category=config.category,
        stat_name=config.stat_name,
        points_per_unit=config.points_per_unit,
        is_active=config.is_active,
    )
    db.add(sc)
    await db.commit()
    await db.refresh(sc)
    return sc


@router.get("/league/{league_id}")
async def get_league_scoring(league_id: str, db: AsyncSession = Depends(get_db)):
    """Get active scoring config rows for a league."""
    result = await db.execute(
        select(ScoringConfig).where(
            ScoringConfig.league_id == league_id,
            ScoringConfig.is_active == True,
        )
    )
    configs = result.scalars().all()
    return configs


@router.delete("/{config_id}", status_code=204)
async def delete_scoring_config(config_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a single scoring config row."""
    result = await db.execute(select(ScoringConfig).where(ScoringConfig.id == config_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Scoring config not found")
    await db.delete(config)
    await db.commit()


# ─── Calculator endpoints ─────────────────────────────────────────────


@router.get("/defaults")
async def get_default_scoring():
    """Return the default PPR scoring configuration as a template."""
    return DEFAULT_SCORING


@router.post("/calculate", response_model=ScoringCalculatorResult)
async def calculate_score(input: ScoringCalculatorInput):
    """
    Calculate fantasy points for a single player.

    Accepts raw stats and scoring config, returns total score
    with a detailed breakdown of points by category.
    """
    total = calculate_player_score(input.stats, input.scoring_config, input.position)

    # Build detailed breakdown by category
    breakdown = {}
    bonuses = {}
    custom_points = 0.0

    for category, rules in input.scoring_config.items():
        if category == "custom":
            from app.services.scoring_engine import _calculate_custom
            custom_points = _calculate_custom(input.stats, rules)
            continue
        if category == "bonus":
            from app.services.scoring_engine import _calculate_bonus
            bonuses = _calculate_bonus(input.stats, rules)
            # Convert flat dict if _calculate_bonus returned a float
            if isinstance(bonuses, dict):
                pass  # Now _calculate_bonus returns float, so this is legacy
            continue

        if not isinstance(rules, dict):
            continue

        category_total = 0.0
        for stat_name, points_per_unit in rules.items():
            if stat_name in input.stats and input.stats[stat_name] is not None:
                val = float(input.stats[stat_name]) * float(points_per_unit)
                category_total += val

        if category_total != 0:
            breakdown[category] = round(category_total, 2)

    from app.services.scoring_engine import _calculate_bonus
    bonus_total = _calculate_bonus(input.stats, input.scoring_config.get("bonus", {}))
    bonuses = dict(input.scoring_config.get("bonus", {})) if isinstance(input.scoring_config.get("bonus"), dict) else {}
    active_bonuses = {}
    for bonus_name, bonus_val in bonuses.items():
        threshold_map = {
            "pass_300_yds": ("pass_yds", 300),
            "pass_350_yds": ("pass_yds", 350),
            "pass_400_yds": ("pass_yds", 400),
            "rush_100_yds": ("rush_yds", 100),
            "rush_150_yds": ("rush_yds", 150),
            "rush_200_yds": ("rush_yds", 200),
            "rec_100_yds": ("rec_yds", 100),
            "rec_150_yds": ("rec_yds", 150),
            "rec_200_yds": ("rec_yds", 200),
        }
        if bonus_name in threshold_map:
            stat, thresh = threshold_map[bonus_name]
            if input.stats.get(stat, 0) or 0 >= thresh:
                active_bonuses[bonus_name] = float(bonus_val)

    return ScoringCalculatorResult(
        total_score=total,
        breakdown=breakdown,
        bonuses=active_bonuses,
        custom_points=round(custom_points, 2),
    )


@router.post("/calculate/weekly", response_model=WeeklyScoringResult)
async def calculate_weekly(input: WeeklyScoringInput):
    """
    Calculate total weekly score for a lineup of players.

    Accepts a list of players with their stats and positions,
    plus a scoring config. Returns total and per-player breakdown.
    """
    roster_ids = [p.player_id for p in input.lineup]
    week_stats = {p.player_id: p.stats for p in input.lineup}
    positions = {p.player_id: p.position for p in input.lineup}

    result = calculate_weekly_score(roster_ids, week_stats, input.scoring_config, positions)

    breakdown = {}
    for pid, bd in result["breakdown"].items():
        name_lookup = next(
            (p.name for p in input.lineup if p.player_id == pid),
            None,
        )
        breakdown[pid] = PlayerBreakdown(
            player_id=pid,
            name=name_lookup,
            score=bd["score"],
            stats=bd["stats"],
            position=bd["position"],
        )

    return WeeklyScoringResult(
        total=result["total"],
        breakdown=breakdown,
        player_count=len(input.lineup),
    )


@router.post("/calculate/optimal", response_model=OptimalLineupResult)
async def calculate_optimal(input: OptimalLineupInput):
    """
    Calculate the optimal starting lineup from a roster.

    Uses greedy assignment by position to find the highest-scoring
    possible lineup given position slot constraints.
    """
    result = calculate_optimal_lineup(
        roster=input.roster,
        scoring_config=input.scoring_config,
        n_qb=input.n_qb,
        n_rb=input.n_rb,
        n_wr=input.n_wr,
        n_te=input.n_te,
        n_flex=input.n_flex,
        n_superflex=input.n_superflex,
        n_k=input.n_k,
        n_def=input.n_def,
    )

    lineup = [
        OptimalLineupSlot(**slot) for slot in result["lineup"]
    ]
    benched = [
        OptimalLineupSlot(
            player_id=p["player_id"],
            name=p.get("name"),
            score=p["score"],
            position=p["position"],
            slot="BENCH",
        )
        for p in result["benched"]
    ]

    return OptimalLineupResult(
        optimal_score=result["optimal_score"],
        lineup=lineup,
        benched=benched,
    )


@router.post("/validate")
async def validate_config(scoring_config: dict):
    """
    Validate a scoring configuration and return any warnings/errors.
    """
    warnings = validate_scoring_config(scoring_config)
    return {
        "valid": len(warnings) == 0,
        "warnings": warnings,
    }


# ─── Sleeper-specific endpoints ────────────────────────────────────────


@router.post("/sleeper/weekly", response_model=Dict[str, PlayerBreakdown])
async def sleeper_weekly_scoring(
    input: SleeperWeeklyScoringInput,
    db: AsyncSession = Depends(get_db),
):
    """
    Fetch weekly stats from Sleeper API for given player IDs
    and calculate their fantasy scores using the provided config.
    """
    # Fetch stats from Sleeper
    weekly_stats = await fetch_weekly_stats(input.year, input.week)

    result = {}
    for pid in input.player_ids:
        pid_str = str(pid)
        stats = weekly_stats.get(pid_str, {})

        # Look up position from DB
        player_lookup = await db.execute(
            select(Player).where(Player.sleeper_id == pid_str)
        )
        player = player_lookup.scalar_one_or_none()
        position = player.position if player else "UNKNOWN"
        name = f"{player.first_name} {player.last_name}" if player else pid_str

        score = calculate_player_score(stats, input.scoring_config, position)

        result[pid_str] = PlayerBreakdown(
            player_id=pid_str,
            name=name,
            score=score,
            stats=stats,
            position=position,
        )

    return result
