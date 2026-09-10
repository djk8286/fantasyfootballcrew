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

# Default PPR scoring template.
#
# IMPORTANT: these stat_name keys must exactly match the raw keys Sleeper's
# stats API returns (confirmed empirically against
# /v1/stats/nfl/regular/{season}/{week} -- note the required "regular"
# season_type segment, see sleeper_sync.fetch_weekly_stats). The engine only
# does exact key lookups (calculate_player_score: `if stat_name in
# player_stats`), so any mismatch here silently scores that stat as 0 for
# every player, every week -- which is what every category previously did:
#   - "pass_yds"/"rush_yds"/"rec_yds" -> Sleeper uses singular "_yd"
#   - "int" (passing) -> Sleeper's thrown-interception key is "pass_int";
#     bare "int" is the *defense's* takeaway count
#   - "def_sack"/"def_int"/"def_fum_rec"/"def_safety" -> Sleeper's team
#     defense keys have no "def_" prefix: "sack"/"int"/"fum_rec"/"safe"
#   - "def_ret_yds" -> doesn't exist; real keys are separate "kr_yd" (kick
#     return) and "pr_yd" (punt return) -- kept as two additive entries
#     since the engine sums whichever keys are present rather than combining
#     them under one name
#   - kicking "fg_0_39"/"fg_40_49"/"fg_50_plus" -> Sleeper buckets makes as
#     fgm_20_29/fgm_30_39/fgm_40_49/fgm_50_59/fgm_60p (no bucket below 20
#     was observed; omitted rather than guessing a key that may not exist).
#     Sleeper ALSO exposes fgm_50p, but confirmed against real 2025 data
#     it's a cumulative "50+" counter equal to fgm_50_59 + fgm_60p, not a
#     fourth independent bucket -- scoring it alongside the two real
#     buckets it already contains would double-count every 50+ make, so
#     it's deliberately left out of DEFAULT_SCORING entirely.
#   - "xp" -> Sleeper's made-extra-point key is "xpm"
#   - "idp_*" keys -- an individual defender's OWN stats, distinct from the
#     "defense" category above (which is the TEAM's aggregate takeaways/
#     sacks, credited whole regardless of which of the 11 players on the
#     field made the play). Confirmed against real 2025 season data for
#     Fred Warner (LB), Nick Bosa (DL), and Minkah Fitzpatrick (DB) via
#     /v1/stats/nfl/regular/2025 -- e.g. Bosa's real record includes
#     idp_sack: 2.0, idp_tkl_solo: 9.0, idp_ff: 2.0, none of which had any
#     scoring rule to match against before this. idp_qb_hit and
#     idp_sack_yd exist in the real data too but are deliberately left out
#     of the *default* template (uncommon to score separately from sacks
#     in most standard IDP formats) -- a league can still add either via
#     its own custom scoring rules.
DEFAULT_SCORING = {
    "passing": {
        "pass_yd": 0.04,
        "pass_td": 4,
        "pass_int": -2,
        "pass_2pt": 2,
    },
    "rushing": {
        "rush_yd": 0.1,
        "rush_td": 6,
        "rush_2pt": 2,
    },
    "receiving": {
        "rec": 1.0,
        "rec_yd": 0.1,
        "rec_td": 6,
        "rec_2pt": 2,
    },
    "defense": {
        "sack": 1,
        "int": 2,
        "fum_rec": 2,
        "safe": 2,
        "def_td": 6,
        "st_fum_rec": 2,
        "st_td": 6,
        "kr_yd": 0.02,
        "pr_yd": 0.02,
    },
    # 2026-09-09: fgm_50p REMOVED and fgm_60p added -- confirmed against
    # real 2025 Sleeper stats (week 1 payload) that fgm_50p is NOT a
    # distinct "50-59" bucket the way its name alongside fgm_50_59
    # suggests -- it's a cumulative "50 yards or more" counter that
    # ALREADY INCLUDES every fgm_50_59 make too (e.g. one real kicker's
    # week 1 line: fgm_50_59=1, fgm_50p=2, fgm_60p=1 -- fgm_50p is
    # exactly fgm_50_59 + fgm_60p, not a third independent bucket).
    # Scoring both fgm_50_59 AND fgm_50p (the old default) double-counted
    # every 50-59 yard make (10 pts under a "5-point" label) and scored a
    # 60+ make as if it were only a 50-59 (fgm_60p had no rule at all --
    # the exact "60+ is wrong, labeled as 50+" bug this replaces). The
    # three real, mutually-exclusive length buckets Sleeper actually
    # provides are fgm_40_49 / fgm_50_59 / fgm_60p -- only those are
    # scored now, each independently adjustable, with 60+ deliberately
    # priced a point above 50-59 (a harder kick) rather than left at
    # parity with it.
    "kicking": {
        "fgm_20_29": 3,
        "fgm_30_39": 3,
        "fgm_40_49": 4,
        "fgm_50_59": 5,
        "fgm_60p": 6,
        "xpm": 1,
    },
    # Individual defensive player (IDP) stats -- DL/LB/DB. Standard,
    # commonly-used point values (same "reasonable default a league can
    # customize" spirit as every other category here, not a single
    # canonical standard -- IDP scoring conventions vary more across
    # platforms than offense does).
    "idp": {
        "idp_tkl_solo": 1,
        "idp_tkl_ast": 0.5,
        "idp_tkl_loss": 2,
        "idp_sack": 4,
        "idp_int": 6,
        "idp_ff": 4,
        "idp_fum_rec": 4,
        "idp_pass_def": 2,
        # An individual defender's OWN touchdown (pick-six, fumble/blocked-
        # kick return TD, etc.) -- distinct from "defense.def_td" above,
        # which only ever credits the TEAM regardless of which of the 11
        # players on the field scored it. Real Sleeper key confirmed
        # against 2025 week 1 data (idp_def_td: 1.0 on a real defender's
        # box score) -- without this key, an individual defender's TD was
        # only ever credited to their team's defense slot, never to them.
        "idp_def_td": 6,
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
IDP_FLEX_ELIGIBLE = {"DL", "LB", "DB"}

# Default starting-lineup slot counts for a new league (standard 9-starter
# roster: 1 QB, 2 RB, 2 WR, 1 TE, 1 FLEX, 1 K, 1 DEF). IDP slots default to
# 0 -- deliberately opt-in, not on by default, so an existing league's
# lineup requirements don't change out from under it just because IDP
# scoring now exists. A league that wants IDP turns these up in its own
# roster-slot settings, same as any other league setting.
DEFAULT_ROSTER_SLOTS = {
    "QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "SUPERFLEX": 0,
    "K": 1, "DEF": 1, "DL": 0, "LB": 0, "DB": 0, "IDP_FLEX": 0,
}

# Minimum yardage to consider a TD "long" automatically
LONG_TD_YARDAGE_THRESHOLD = 40


def _category_applies_to_position(category: str, player_position: str | None) -> bool:
    """2026-09-10 fix -- a real bug, not a hypothetical: the category
    loop below used to apply ANY category's rules to ANY player, as long
    as a matching stat key happened to exist in that player's OWN stats
    dict, with no regard for whether the category was ever meant to
    apply to that player's position at all.

    This was invisible under DEFAULT_SCORING's modest 0.02/yd kr_yd/
    pr_yd rate, but a real beta league had customized "defense.kr_yd" to
    0.4/yd (a deliberate, reasonable choice for how much a TEAM's return
    game should be worth) -- and Sleeper's per-player stat line for a WR
    who also returns kicks includes that SAME kr_yd key on the
    individual player, not just on the team DEF unit's synthetic entry.
    The result: a WR with 1 catch for 4 yards and 80 unremarkable kick-
    return yards scored 33.26 points in a half-PPR league, because his
    own return yards got priced at the DEFENSE unit's rate. Confirmed
    against the exact real numbers (0.9 real receiving + 80*0.4 + 9*0.04
    = 33.26, to the penny) before writing this fix.

    "passing"/"rushing"/"receiving" stay ungated -- a WR/RB legitimately
    rushing for a TD (an end-around) is common and expected, and
    DEF/K/IDP stat lines never contain those keys anyway. "defense"/
    "kicking"/"idp" are now strictly scoped to the position(s) each one
    was ever conceptually meant for -- individual IDP scoring already
    has its own dedicated "idp" category for exactly this reason
    (idp_sack et al, distinct from "defense"'s team-aggregate sack);
    there was never a legitimate reason for "defense" to score anyone
    who isn't the team DEF unit itself.

    A None/unrecognized position skips every gated category rather than
    defaulting to "apply it anyway" -- the whole point of this fix is
    that an unverified position must never be treated as license to
    apply team-defense/kicker/IDP rates to someone it wasn't meant for."""
    if category == "defense":
        return player_position == "DEF"
    if category == "kicking":
        return player_position == "K"
    if category == "idp":
        return player_position in ("DB", "DL", "LB")
    return True  # passing/rushing/receiving, and any future/custom category


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
        if not _category_applies_to_position(category, player_position):
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


def calculate_player_score_by_category(
    player_stats: Dict[str, Any],
    scoring_config: Dict[str, Any],
    player_position: str = None,
) -> Dict[str, float]:
    """Same category loop as calculate_player_score, but returns the
    per-category point breakdown instead of one summed total -- what
    insights_service.py needs to find which scoring categories are
    driving score variance week to week. A deliberate sibling, not a
    refactor of calculate_player_score itself: that function's exact
    rounding/return-float behavior is relied on elsewhere and pinned by
    existing tests, so this duplicates its small loop rather than
    risking it.

    "bonus" (threshold-based) and "custom" (user-defined rules) each
    get their own key in the returned dict, consistent with how
    they're already distinct top-level scoring_config categories
    everywhere else -- so a category_variance analysis can treat
    "bonus points" as their own signal alongside passing/rushing/etc.

    Returns: Dict of category -> points from that category (only for
    categories present in scoring_config; a category contributing 0.0
    still gets a key, since "this league scores kicking but a given
    player got 0 kicking points this week" is different from "this
    league doesn't score kicking at all").
    """
    if not player_stats:
        return {}

    by_category: Dict[str, float] = {}

    for category, rules in scoring_config.items():
        if category in ("custom", "bonus"):
            continue
        if not _category_applies_to_position(category, player_position):
            continue
        if not isinstance(rules, dict):
            continue

        category_points = 0.0
        for stat_name, points_per_unit in rules.items():
            if stat_name in player_stats:
                stat_value = player_stats[stat_name]
                if stat_value is not None:
                    category_points += float(stat_value) * float(points_per_unit)
        by_category[category] = round(category_points, 2)

    if "bonus" in scoring_config and isinstance(scoring_config["bonus"], dict):
        by_category["bonus"] = round(_calculate_bonus(player_stats, scoring_config["bonus"]), 2)

    if "custom" in scoring_config and isinstance(scoring_config["custom"], list):
        by_category["custom"] = round(_calculate_custom(player_stats, scoring_config["custom"]), 2)

    return by_category


def _calculate_bonus(player_stats: Dict[str, Any], bonus_rules: Dict[str, Any]) -> float:
    """Calculate threshold-based bonus points.

    Two rule shapes are supported in the same dict, for backward
    compatibility:
    - Legacy: `{"pass_300_yds": 3}` -- a plain number, matched against
      bonus_mappings' fixed name->(stat, threshold) table below. Every
      already-saved league's bonus config is this shape; nothing about
      it changes.
    - Configurable (2026-09-09): `{"pass_yds_bonus": {"stat_name":
      "pass_yd", "threshold": 400, "points": 3}}` -- a dict value lets a
      commissioner pick ANY yard cutoff (e.g. 400 instead of the fixed
      300/350/400 options above), not just one of the pre-named keys.
      The key name itself is arbitrary under this shape (unlike the
      legacy table, nothing here depends on matching a specific string),
      so a league can define as many custom threshold bonuses as it
      wants, each under its own key.
    """
    bonus_points = 0.0

    bonus_mappings = {
        "pass_300_yds": ("pass_yd", 300),
        "pass_350_yds": ("pass_yd", 350),
        "pass_400_yds": ("pass_yd", 400),
        "rush_100_yds": ("rush_yd", 100),
        "rush_150_yds": ("rush_yd", 150),
        "rush_200_yds": ("rush_yd", 200),
        "rec_100_yds": ("rec_yd", 100),
        "rec_150_yds": ("rec_yd", 150),
        "rec_200_yds": ("rec_yd", 200),
        "long_td_bonus": ("long_td", 1),
    }

    for bonus_name, rule in bonus_rules.items():
        if isinstance(rule, dict):
            stat_name = rule.get("stat_name")
            threshold = rule.get("threshold")
            points = rule.get("points", 0)
            if not stat_name or threshold is None:
                continue
            stat_value = player_stats.get(stat_name)
            if stat_value is None:
                continue
            try:
                stat_value = float(stat_value)
                threshold = float(threshold)
            except (TypeError, ValueError):
                continue
            if stat_value >= threshold:
                bonus_points += float(points)
            continue

        points = rule
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
        pass_yds = player_stats.get("pass_yd", 0) or 0
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
        rush_yds = player_stats.get("rush_yd", 0) or 0
        rec_yds = player_stats.get("rec_yd", 0) or 0

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
    n_dl: int = 0,
    n_lb: int = 0,
    n_db: int = 0,
    n_idp_flex: int = 0,
) -> Dict[str, Any]:
    """
    Calculate the optimal starting lineup for a roster based on projected scores.

    Uses a simple greedy approach (optimal for independent player scores).

    Args:
        roster: Dict of player_id -> {stats, position, name}
        scoring_config: League scoring config
        n_qb, n_rb, n_wr, n_te, n_flex, n_superflex, n_k, n_def: Starting lineup slots
        n_dl, n_lb, n_db: dedicated IDP position slots (all default 0 --
            see DEFAULT_ROSTER_SLOTS for why)
        n_idp_flex: a slot any of DL/LB/DB can fill, assigned last among
            the IDP slots so it never steals a player a dedicated DL/LB/DB
            slot still needed

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
    assignments += assign_slot({"DL"}, n_dl, "DL")
    assignments += assign_slot({"LB"}, n_lb, "LB")
    assignments += assign_slot({"DB"}, n_db, "DB")
    assignments += assign_slot(IDP_FLEX_ELIGIBLE, n_idp_flex, "IDP_FLEX")

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

    valid_categories = {"passing", "rushing", "receiving", "defense", "idp", "kicking", "bonus", "custom"}
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
            # "bonus" alone allows a dict value too -- see _calculate_bonus's
            # docstring for the configurable-threshold shape
            # ({"stat_name", "threshold", "points"}), which this must not
            # flag as an "invalid points value" the way every other
            # category's plain stat->points mapping would be right to.
            if category == "bonus" and isinstance(points, dict):
                if "stat_name" not in points or "threshold" not in points:
                    warnings.append(f"Custom bonus '{stat_name}' missing 'stat_name' or 'threshold'")
                continue
            try:
                float(points)
            except (TypeError, ValueError):
                warnings.append(f"Invalid points value for {category}.{stat_name}: {points}")

    return warnings
