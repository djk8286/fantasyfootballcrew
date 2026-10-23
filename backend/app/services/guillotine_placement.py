"""Final placement for a GUILLOTINE league.

Pure functions over data get_standings already has, so standings,
league home, the digest, recaps and playoff seeding all rank a
Guillotine league the same way the standings skin draws it.

Rules:
- Alive teams rank above eliminated teams. Before the finale they keep
  the usual wins, then points_for order.
- Eliminated teams rank by most recent cut first, so the last team cut
  finishes 3rd once the finale is set.
- Finale (exactly two teams left): the finalists play each other every
  week after the last cut. They rank by series record (wins minus
  losses), then total finale points, then season points_for, then the
  earlier-created team.
- The champion is decided once the last regular-season week
  (LAST_REGULAR_WEEK) has a counted score. Until then the finalists
  have no final place.
"""
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

LAST_REGULAR_WEEK = 18

WeekKey = Tuple[int, int]  # (year, week)


def _series(a_id: str, b_id: str, weeks: List[Dict[str, float]]) -> Tuple[dict, dict]:
    a = {"team_id": a_id, "wins": 0, "losses": 0, "ties": 0, "points": 0.0}
    b = {"team_id": b_id, "wins": 0, "losses": 0, "ties": 0, "points": 0.0}
    for scores in weeks:
        pa, pb = scores.get(a_id, 0.0), scores.get(b_id, 0.0)
        a["points"] += pa
        b["points"] += pb
        if pa > pb:
            a["wins"] += 1
            b["losses"] += 1
        elif pb > pa:
            b["wins"] += 1
            a["losses"] += 1
        else:
            a["ties"] += 1
            b["ties"] += 1
    a["points"] = round(a["points"], 2)
    b["points"] = round(b["points"], 2)
    return a, b


def guillotine_placement(
    teams: Iterable[Any],
    weekly_scores: Dict[WeekKey, Dict[str, float]],
    points_for: Dict[str, float],
    is_pairing: Callable[[int, str, str], bool] = lambda week, a, b: True,
) -> Dict[str, Any]:
    """Placement for one Guillotine league.

    teams: objects with .id, .eliminated_week and .created_at.
    weekly_scores: counted weeks only, {(year, week): {team_id: score}}.
    points_for: season points per team, the third finale tie-break.
    is_pairing: whether the two finalists played each other that week
    (standings_service passes its schedule check).

    Returns {phase, champion_team_id, runner_up_team_id, finalists,
    finale_weeks, order, places}. phase is "elimination", "finale" or
    "final". finalists is leader first, each {team_id, wins, losses,
    ties, points}. places maps team_id to a final place, or None for a
    team whose place isn't settled yet.
    """
    teams = list(teams)
    alive = [t for t in teams if t.eliminated_week is None]
    cut = sorted(
        (t for t in teams if t.eliminated_week is not None),
        key=lambda t: (-t.eliminated_week, -points_for.get(t.id, 0.0), _created(t)),
    )
    last_cut = max((t.eliminated_week for t in cut), default=0)
    latest_year = max((y for (y, _) in weekly_scores), default=None)

    finalists: List[dict] = []
    finale_weeks: List[int] = []
    champion = runner_up = None
    phase = "elimination"

    if len(alive) == 2 and len(teams) > 2:
        phase = "finale"
        t1, t2 = alive
        played = sorted(
            w for (y, w) in weekly_scores
            if y == latest_year and w > last_cut and is_pairing(w, t1.id, t2.id)
        )
        finale_weeks = played
        a, b = _series(t1.id, t2.id, [weekly_scores[(latest_year, w)] for w in played])
        by_id = {t.id: t for t in alive}

        def key(r: dict):
            t = by_id[r["team_id"]]
            return (-(r["wins"] - r["losses"]), -r["points"], -points_for.get(t.id, 0.0), _created(t))

        finalists = sorted([a, b], key=key)
        season_done = latest_year is not None and any(
            y == latest_year and w >= LAST_REGULAR_WEEK for (y, w) in weekly_scores
        )
        if season_done:
            phase = "final"
            champion, runner_up = finalists[0]["team_id"], finalists[1]["team_id"]
        alive_order = [r["team_id"] for r in finalists]
    else:
        alive_order = [t.id for t in alive]  # caller keeps its own order for these

    places: Dict[str, Optional[int]] = {t.id: None for t in alive}
    if phase == "final":
        places[champion] = 1
        places[runner_up] = 2
    for i, t in enumerate(cut):
        places[t.id] = len(alive) + i + 1

    return {
        "phase": phase,
        "champion_team_id": champion,
        "runner_up_team_id": runner_up,
        "finalists": finalists,
        "finale_weeks": finale_weeks,
        "order": alive_order + [t.id for t in cut],
        "places": places,
    }


def _created(t: Any) -> float:
    c = getattr(t, "created_at", None)
    return c.timestamp() if isinstance(c, datetime) else 0.0


def order_guillotine_rows(rows: List[dict], placement: Dict[str, Any]) -> List[dict]:
    """Re-sort get_standings rows (already in wins, points_for order) by
    Guillotine placement and tag each row with its place. Alive teams
    before the finale keep the incoming order."""
    places = placement["places"]
    finalist_rank = {tid: i for i, tid in enumerate(r["team_id"] for r in placement["finalists"])}
    cut_rank = {tid: i for i, tid in enumerate(placement["order"]) if tid not in finalist_rank}
    incoming = {r["team_id"]: i for i, r in enumerate(rows)}

    def key(r: dict):
        tid = r["team_id"]
        if r.get("eliminated_week") is None:
            return (0, finalist_rank.get(tid, incoming[tid]))
        return (1, cut_rank.get(tid, incoming[tid]))

    out = sorted(rows, key=key)
    for r in out:
        r["guillotine_place"] = places.get(r["team_id"])
    return out
