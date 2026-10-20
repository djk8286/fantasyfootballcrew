"""Default lineups for teams that never saved one for a week.

Before this module, a team with no Lineup row for a week scored its whole
roster. Every CPU team works that way, so a CPU team could count 15
players (two QBs, two kickers, and so on) against a human team capped at
its league's starting slots.

Now a team with no saved lineup scores a legal default lineup built from
the league's roster slots. The ranking is deterministic and never looks
at the week being scored:

1. Players whose NFL team has no game that week (bye) are skipped, when
   that week's NFL schedule is known.
2. Players ruled out (Out, IR, PUP, suspended, NA) are skipped when the
   caller asks for it, which calculate_week and the lineup page do for
   any week not yet final (a default already frozen at kickoff is kept
   as is). A recompute of a finished week can't know a player's status
   back then, so it doesn't filter on injury.
3. The rest are ranked by fantasy points from this season's weeks
   strictly before the scored week (the same season stats the lineup
   auto-fill uses, minus the week itself), falling back to last
   season's totals when there are no earlier weeks yet. Ties break by
   player id.
4. calculate_optimal_lineup fills the slots greedily in league order
   (QB, RB, WR, TE, FLEX, SUPERFLEX, K, DEF, IDP...). A slot with no
   eligible player stays empty and scores nothing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set

from app.services.scoring_engine import DEFAULT_ROSTER_SLOTS, calculate_optimal_lineup
from app.services.sleeper_sync import aggregate_week_stats

# Sleeper injury designations that mean "won't play this week".
INACTIVE_STATUSES = {"out", "ir", "pup", "sus", "suspended", "na"}


def is_inactive_status(status: Optional[str]) -> bool:
    return bool(status) and status.strip().lower() in INACTIVE_STATUSES


@dataclass
class Candidate:
    player_id: str
    position: str
    nfl_team: Optional[str] = None
    injury_status: Optional[str] = None
    ranking_stats: Dict[str, Any] = field(default_factory=dict)


def pre_week_ranking_stats(player: Any, week: int, year: int) -> Dict[str, Any]:
    """Season stat totals from `year`'s weeks strictly before `week`, or
    last season's archived totals if there are none yet. Never includes
    the scored week, so the ranking can't depend on how that week went."""
    week_stats = getattr(player, "week_stats", None) or {}
    if getattr(player, "stats_year", None) == year and week_stats:
        earlier = {k: v for k, v in week_stats.items() if str(k).isdigit() and int(k) < week}
        if earlier:
            return aggregate_week_stats(earlier)
    return dict(getattr(player, "last_season_stats", None) or {})


def candidate_from_player(player: Any, week: int, year: int) -> Candidate:
    return Candidate(
        player_id=player.id,
        position=player.position,
        nfl_team=player.team,
        injury_status=player.injury_status,
        ranking_stats=pre_week_ranking_stats(player, week, year),
    )


def league_roster_slots(league: Any) -> Dict[str, int]:
    slots = dict(DEFAULT_ROSTER_SLOTS)
    slots.update(getattr(league, "roster_slots", None) or {})
    return slots


def choose_default_starters(
    candidates: Iterable[Candidate],
    roster_slots: Dict[str, int],
    scoring_config: Dict[str, Any],
    *,
    teams_playing: Optional[Set[str]] = None,
    exclude_inactive: bool = False,
) -> List[str]:
    """Player ids for a legal default lineup, in slot order.

    teams_playing: NFL team abbreviations with a game this week, or None
    when the schedule isn't known (then nobody is treated as on bye).
    """
    pool = sorted(candidates, key=lambda c: c.player_id)
    if teams_playing is not None:
        pool = [c for c in pool if c.nfl_team and c.nfl_team in teams_playing]
    if exclude_inactive:
        pool = [c for c in pool if not is_inactive_status(c.injury_status)]

    # Insertion order is player-id order and calculate_optimal_lineup's
    # sort is stable, so equal scores resolve by player id.
    roster = {c.player_id: {"stats": c.ranking_stats, "position": c.position, "name": c.player_id} for c in pool}
    result = calculate_optimal_lineup(
        roster,
        scoring_config,
        n_qb=roster_slots.get("QB", 0),
        n_rb=roster_slots.get("RB", 0),
        n_wr=roster_slots.get("WR", 0),
        n_te=roster_slots.get("TE", 0),
        n_flex=roster_slots.get("FLEX", 0),
        n_superflex=roster_slots.get("SUPERFLEX", 0),
        n_k=roster_slots.get("K", 0),
        n_def=roster_slots.get("DEF", 0),
        n_dl=roster_slots.get("DL", 0),
        n_lb=roster_slots.get("LB", 0),
        n_db=roster_slots.get("DB", 0),
        n_idp_flex=roster_slots.get("IDP_FLEX", 0),
    )
    return [a["player_id"] for a in result["lineup"]]
