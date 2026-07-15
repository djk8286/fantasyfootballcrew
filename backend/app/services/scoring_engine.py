"""
Customizable Scoring Engine for FantasyFootballCrew.

This is the heart of the platform. Users can define their own scoring rules
and the engine calculates points based on real NFL stats.

Design:
- Scoring config is stored as JSONB on the League model
- The config maps Sleeper API stat keys to point values
- Supports categories: passing, rushing, receiving, defense, kicking, bonus, custom
- Bonuses trigger at thresholds (e.g., 100 rushing yards = +3 bonus)
- Custom rules allow user-defined formulas
- Long TD detection uses play-level stat hints
"""

from typing import Dict, Any, Optional, List, Union

# Default PPR scoring template
DEFAULT_SCORING = {
    "passing": {
        "pass_yds": 0.04,
        "pass_td": 4,
        "int": -2,
        "pass_2pt": 2,
    },
    "rushing": {
        "rush_yds": 0.1,
        "rush_td": 6,
        "rush_2pt": 2,
    },
    "receiving": {
        "rec": 1.0,
        "rec_yds": 0.1,
        "rec_td": 6,
        "rec_2pt": 2,
    },
    "defense": {
        "def_sack": 1,
        "def_int": 2,
        "def_fum_rec": 2,
        "def_safety": 2,
        "def_td": 6,
        "st_fum_rec": 2,
        "st_td": 6,
        "def_ret_yds": 0.02,
    },
    "kicking": {
        "fg_0_39": 3,
        "fg_40_49": 4,
        "fg_50_plus": 5,
        "xp": 1,
    },
    "bonus": {
        "pass_300_yds": 3,
        "rush_100_yds": 3,
        "rec_100_yds": 3,
        "long_td_bonus": 3,
    },
}

# Positions eligible per slot type (standard fantasy roster)
FLEX_ELIGIBLE = {"RB", "WR", "TE"}
SUPERFLEX_ELIGIBLE = {"QB", "RB", "WR", "TE"}

# Minimum yardage to consider a TD "long" automatically
LONG_TD_YARDAGE_THRESHOLD = 40


def calculate_player_score(
    player_stats: Dict[str, Any],
    scoring_config: Dict[str, Any],
    player_position: str = None,
) -> float:
    """
    Calculate fantasy points for a single player based on their stats and league scoring config.

    Args:
        player_stats: Dict of stat_name -> value from Sleeper API
        scoring_config: League's scoring configuration
        player_position: Player position (QB, RB, WR, TE, K, DEF)

    Returns:
        Total fantasy points
    """
    if not player_stats:
        return 0.0

    total_points = 0.0

    # Calculate points from each category
    for category, rules in scoring_config.items():
        if category == "custom":
            continue
        if category == "bonus":
            continue

        if not isinstance(rules, dict):
            continue

        for stat_name, points_per_unit in rules.items():
            if stat_name in player_stats:
                stat_value = player_stats[stat_name]
                if stat_value is not None:
                    total_points += float(stat_value) * float(points_per_unit)

    # Calculate bonus points (threshold-based)
    if "bonus" in scoring_config and isinstance(scoring_config["bonus"], dict):
        total_points += _calculate_bonus(player_stats, scoring_config["bonus"])

    # Calculate custom rules
    if "custom" in scoring_config and isinstance(scoring_config["custom"], list):
        total_points += _calculate_custom(player_stats, scoring_config["custom"])

    return round(total_points, 2)


def _calculate_bonus(player_stats: Dict[str, Any], bonus_rules: Dict[str, float]) -> float:
    """Calculate threshold-based bonus points."""
    bonus_points = 0.0

    bonus_mappings = {
        "pass_300_yds": ("pass_yds", 300),
        "pass_350_yds": ("pass_yds", 350),
        "pass_400_yds": ("pass_yds", 400),
        "rush_100_yds": ("rush_yds", 100),
        "rush_150_yds": ("rush_yds", 150),
        "rush_200_yds": ("rush_yds", 200),
        "rec_100_yds": ("rec_yds", 100),
        "rec_150_yds": ("rec_yds", 150),
        "rec_200_yds": ("rec_yds", 200),
        "long_td_bonus": ("long_td", 1),
    }

    for bonus_name, points in bonus_rules.items():
        if bonus_name in bonus_mappings:
            stat_name, threshold = bonus_mappings[bonus_name]
            stat_value = player_stats.get(stat_name)
            if stat_value is not None:
                try:
                    stat_value = float(stat_value)
                except (TypeError, ValueError):
                    continue
                if stat_value >= threshold:
                    bonus_points += points
        elif bonus_name.endswith("_long_td"):
            # Handle position-specific long TD bonuses
            position = bonus_name.replace("_long_td", "").upper()
            if position in ("QB", "RB", "WR", "TE"):
                long_tds = _estimate_long_tds(player_stats, position)
                if long_tds > 0:
                    bonus_points += long_tds * points

    return bonus_points


def _estimate_long_tds(player_stats: Dict[str, Any], position: str) -> int:
    """
    Estimate number of long (40+ yard) touchdowns from available stat data.

    This is best-effort. Full play-level data from the NFL API would
    give exact counts; this uses reasonable heuristics:
    - A player's average TD length is estimated from total receiving/rushing
      yards and TDs. If yards per TD >= LONG_TD_YARDAGE_THRESHOLD, all their
      TDs are long. If below, we estimate a fraction based on the ratio.
    """
    if position == "QB":
        td_count = player_stats.get("pass_td", 0) or 0
        pass_yds = player_stats.get("pass_yds", 0) or 0
        if td_count == 0:
            return 0
        # If QB had 400+ yards passing AND 4+ TDs, likely some were long
        if pass_yds >= 400 and td_count >= 4:
            return max(1, td_count // 3)
        # Check for explicit long_pass_td stat from advanced data
        explicit_long = player_stats.get("long_pass_td", 0) or 0
        return int(explicit_long)

    if position in ("RB", "WR", "TE"):
        rush_tds = player_stats.get("rush_td", 0) or 0
        rec_tds = player_stats.get("rec_td", 0) or 0
        rush_yds = player_stats.get("rush_yds", 0) or 0
        rec_yds = player_stats.get("rec_yds", 0) or 0

        # Check for explicit long TD stats from advanced data
        explicit_long = int(player_stats.get("long_rush_td", 0) or 0) + int(player_stats.get("long_rec_td", 0) or 0)

        if position in ("RB",):
            total_tds = rush_tds + rec_tds
            total_yds = rush_yds + rec_yds
        else:
            total_tds = rec_tds + rush_tds
            total_yds = rec_yds + rush_yds

        if total_tds == 0:
            return explicit_long

        # If explicit long TDs are reported, use them
        if explicit_long > 0:
            return explicit_long

        # Estimate: if yards per TD >= threshold, all TDs are long
        yds_per_td = total_yds / total_tds
        if yds_per_td >= LONG_TD_YARDAGE_THRESHOLD:
            return total_tds

        # Fractional estimate: only count TDs as long if yds_per_td >= 75% of threshold.
        # This prevents overcounting for players with many short TDs.
        if yds_per_td >= LONG_TD_YARDAGE_THRESHOLD * 0.75:
            # Estimate: divide total yards by (threshold * 2) to get a rough count
            estimated = max(1, int(total_yds / (LONG_TD_YARDAGE_THRESHOLD * 2)))
            return min(estimated, total_tds)
        return 0

    return 0


def _calculate_custom(player_stats: Dict[str, Any], custom_rules: list) -> float:
    """Calculate custom user-defined scoring rules."""
    points = 0.0
    for rule in custom_rules:
        if not isinstance(rule, dict):
            continue
        stat_name = rule.get("stat_name")
        operator = rule.get("operator", ">=")
        threshold = rule.get("threshold", 0)
        points_value = rule.get("points", 0)
        multiplier = rule.get("multiplier", 1)

        if stat_name not in player_stats:
            continue

        stat_value = player_stats[stat_name]
        if stat_value is None:
            continue

        matched = False
        if operator == ">=" and stat_value >= threshold:
            matched = True
        elif operator == ">" and stat_value > threshold:
            matched = True
        elif operator == "==" and stat_value == threshold:
            matched = True
        elif operator == "<=" and stat_value <= threshold:
            matched = True
        elif operator == "<" and stat_value < threshold:
            matched = True
        elif operator == "per_unit":
            # Points per unit above threshold
            matched = True
            if isinstance(threshold, (int, float)) and stat_value > threshold:
                points += float(points_value) * (float(stat_value) - float(threshold))

        if matched and operator != "per_unit":
            points += float(points_value) * float(multiplier)

    return points


def calculate_weekly_score(
    roster_player_ids: list[str],
    week_stats: Dict[str, Dict[str, Any]],
    scoring_config: Dict[str, Any],
    player_positions: Dict[str, str],
) -> Dict[str, Any]:
    """
    Calculate total weekly score for a team's roster.

    Args:
        roster_player_ids: List of active lineup player IDs
        week_stats: Dict of player_id -> {stat_key: value}
        scoring_config: League scoring config
        player_positions: Dict of player_id -> position

    Returns:
        Dict with total_score and per-player breakdown
    """
    breakdown = {}
    total = 0.0

    for player_id in roster_player_ids:
        stats = week_stats.get(player_id, {})
        position = player_positions.get(player_id, "UNKNOWN")
        player_score = calculate_player_score(stats, scoring_config, position)
        breakdown[player_id] = {
            "score": player_score,
            "stats": stats,
            "position": position,
        }
        total += player_score

    return {
        "total": round(total, 2),
        "breakdown": breakdown,
    }


def calculate_optimal_lineup(
    roster: Dict[str, Dict[str, Any]],
    scoring_config: Dict[str, Any],
    n_qb: int = 1,
    n_rb: int = 2,
    n_wr: int = 2,
    n_te: int = 1,
    n_flex: int = 1,
    n_superflex: int = 0,
    n_k: int = 1,
    n_def: int = 1,
) -> Dict[str, Any]:
    """
    Calculate the optimal starting lineup for a roster based on projected scores.

    Uses a simple greedy approach (optimal for independent player scores).

    Args:
        roster: Dict of player_id -> {stats, position, name}
        scoring_config: League scoring config
        n_qb, n_rb, n_wr, n_te, n_flex, n_superflex, n_k, n_def: Starting lineup slots

    Returns:
        Dict with optimal_score, lineup_assignments, points_benched
    """
    scored = []
    for pid, pdata in roster.items():
        score = calculate_player_score(
            pdata.get("stats", {}),
            scoring_config,
            pdata.get("position"),
        )
        scored.append({
            "player_id": pid,
            "score": score,
            "position": pdata.get("position", "UNKNOWN"),
            "name": pdata.get("name", pid),
        })

    # Sort by score descending
    scored.sort(key=lambda x: x["score"], reverse=True)

    assignments = []
    used_ids = set()

    def assign_slot(position_filter, count, slot_name):
        """Assign best N players matching position_filter to a slot."""
        assigned = []
        for player in scored:
            if len(assigned) >= count:
                break
            if player["player_id"] in used_ids:
                continue
            if position_filter is None or player["position"] in position_filter:
                assigned.append({**player, "slot": slot_name})
                used_ids.add(player["player_id"])
        return assigned

    assignments += assign_slot({"QB"}, n_qb, "QB")
    assignments += assign_slot({"RB"}, n_rb, "RB")
    assignments += assign_slot({"WR"}, n_wr, "WR")
    assignments += assign_slot({"TE"}, n_te, "TE")
    assignments += assign_slot(FLEX_ELIGIBLE, n_flex, "FLEX")
    assignments += assign_slot(SUPERFLEX_ELIGIBLE, n_superflex, "SUPERFLEX")
    assignments += assign_slot({"K"}, n_k, "K")
    assignments += assign_slot({"DEF"}, n_def, "DEF")

    total_score = sum(a["score"] for a in assignments)
    benched = [p for p in scored if p["player_id"] not in used_ids]

    return {
        "optimal_score": round(total_score, 2),
        "lineup": assignments,
        "benched": benched,
    }


def validate_scoring_config(scoring_config: dict) -> List[str]:
    """
    Validate a scoring configuration for correctness.

    Returns a list of warning/error messages. Empty list = valid config.
    """
    warnings = []
    if not scoring_config:
        return ["Scoring config is empty"]

    valid_categories = {"passing", "rushing", "receiving", "defense", "kicking", "bonus", "custom"}
    for category in scoring_config:
        if category not in valid_categories:
            warnings.append(f"Unknown category: '{category}'")
            continue

        rules = scoring_config[category]
        if category == "custom":
            if not isinstance(rules, list):
                warnings.append("'custom' should be a list of rule objects")
            else:
                for i, rule in enumerate(rules):
                    if "stat_name" not in rule:
                        warnings.append(f"Custom rule #{i} missing 'stat_name'")
            continue

        if not isinstance(rules, dict):
            warnings.append(f"Category '{category}' should be a dict of stat -> points")
            continue

        for stat_name, points in rules.items():
            try:
                float(points)
            except (TypeError, ValueError):
                warnings.append(f"Invalid points value for {category}.{stat_name}: {points}")

    return warnings
