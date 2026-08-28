"""
Tests for the real, data-driven player ranking that replaced
draft_manager's old static ~194-name tier list (get_tier_names, removed
-- it read like a stale 2024-offseason snapshot with zero 2025-class
players and still-ranked declining/retired-adjacent veterans; anyone not
manually added fell to a fixed fallback rank of 1000, worse than every
listed player). build_rank_by_id/get_rank_score/get_percentile_tier now
rank every player by real production (effective_season_stats +
calculate_player_score), across ALL positions including the DB/DL/LB
individual-defense ones the old system had zero coverage for at all.

Only the pure ranking logic is covered here (no DB/network involved,
Player() objects are just plain attribute holders, never persisted); the
rest of get_draft_state/get_ai_mock_pick (query building, pick history,
CPU scoring, etc.) is exercised via manual live verification instead,
matching this project's existing practice for this file (see the
CPU-draft-realism verification notes and test_scheduler.py's own
docstring for why).
"""
from app.models.player import Player
from app.services.scoring_engine import DEFAULT_SCORING
from app.services.draft_manager import build_rank_by_id, get_rank_score, get_percentile_tier


def _player(id_, position, first="Test", last="Player", stats=None, stats_year=None,
            last_season_stats=None, last_season_year=None):
    return Player(
        id=id_,
        sleeper_id=id_,
        first_name=first,
        last_name=last,
        position=position,
        stats=stats or {},
        stats_year=stats_year,
        last_season_stats=last_season_stats or {},
        last_season_year=last_season_year,
    )


def test_players_ranked_best_production_first_across_any_position():
    # Fitzpatrick's real 2025 line scores 107 (see test_scoring_engine.py),
    # Bosa's scores 41 -- the better real season should get the lower
    # (better, rank 1) number, regardless of position.
    good_db = _player(
        "p1", "DB", last="Fitzpatrick",
        last_season_stats={"idp_tkl_solo": 56, "idp_tkl_ast": 18, "idp_tkl_loss": 4,
                            "idp_sack": 1, "idp_int": 1, "idp_ff": 1, "idp_fum_rec": 2, "idp_pass_def": 6},
        last_season_year=2025,
    )
    weaker_dl = _player(
        "p2", "DL", last="Bosa",
        last_season_stats={"idp_tkl_solo": 9, "idp_tkl_ast": 8, "idp_tkl_loss": 4,
                            "idp_sack": 2, "idp_ff": 2, "idp_fum_rec": 1},
        last_season_year=2025,
    )
    ranks = build_rank_by_id([good_db, weaker_dl], DEFAULT_SCORING)
    assert ranks[good_db.id] < ranks[weaker_dl.id]
    assert ranks[good_db.id] == 1  # best real production in the pool ranks first


def test_a_current_star_outranks_a_stale_veteran_with_lesser_real_production():
    """Direct regression test for the reported bug: under the old static
    list, a name simply not on it (e.g. any 2025-class rookie) fell to a
    fixed fallback rank of 1000 -- worse than every listed player, even a
    declining veteran still sitting in a top tier purely because the list
    was never updated. Real production must decide this instead."""
    breakout_rookie = _player(
        "p10", "RB", first="Breakout", last="Rookie",
        last_season_stats={"rush_yd": 1400, "rush_td": 14, "rec": 40, "rec_yd": 300, "rec_td": 2},
        last_season_year=2025,
    )
    declining_veteran = _player(
        "p11", "RB", first="Declining", last="Veteran",
        last_season_stats={"rush_yd": 400, "rush_td": 2, "rec": 10, "rec_yd": 60, "rec_td": 0},
        last_season_year=2025,
    )
    ranks = build_rank_by_id([breakout_rookie, declining_veteran], DEFAULT_SCORING)
    assert ranks[breakout_rookie.id] < ranks[declining_veteran.id]


def test_all_given_positions_included_not_just_skill_positions():
    qb = _player("p3", "QB", last="Someone", last_season_stats={"pass_yd": 4000, "pass_td": 30})
    lb = _player("p4", "LB", last="Somebody", last_season_stats={"idp_tkl_solo": 10}, last_season_year=2025)
    ranks = build_rank_by_id([qb, lb], DEFAULT_SCORING)
    assert qb.id in ranks
    assert lb.id in ranks


def test_zero_production_player_still_gets_a_real_rank():
    """No real stats at all -- still gets a real (if last-place) rank,
    not silently dropped."""
    no_stats_lb = _player("p5", "LB", last="Unknown")
    ranks = build_rank_by_id([no_stats_lb], DEFAULT_SCORING)
    assert ranks[no_stats_lb.id] == 1


def test_get_rank_score_returns_computed_rank_when_present():
    player = _player("p6", "RB", first="Christian", last="McCaffrey")
    rank_by_id = {"p6": 3}
    assert get_rank_score(player, rank_by_id) == 3


def test_get_rank_score_falls_back_worse_than_everyone_ranked_when_absent():
    """A player outside the pool this particular call ranked over (e.g. a
    drafted/historic player display) gets a fallback strictly worse than
    every player that WAS ranked -- never a value that could collide with
    or outrank a real computed rank."""
    player = _player("p7", "K", last="Nobody")
    rank_by_id = {"other-1": 1, "other-2": 2}
    assert get_rank_score(player, rank_by_id) == 3


def test_get_rank_score_empty_pool_fallback_is_one():
    player = _player("p8", "K", last="Nobody")
    assert get_rank_score(player, {}) == 1


def test_get_percentile_tier_buckets():
    # 100-player pool: rank 1-5 = tier 1 (top 5%), 6-20 = tier 2 (next 15%),
    # 21-50 = tier 3, 51-80 = tier 4, 81-100 = tier 5.
    assert get_percentile_tier(1, 100) == 1
    assert get_percentile_tier(5, 100) == 1
    assert get_percentile_tier(6, 100) == 2
    assert get_percentile_tier(20, 100) == 2
    assert get_percentile_tier(21, 100) == 3
    assert get_percentile_tier(50, 100) == 3
    assert get_percentile_tier(51, 100) == 4
    assert get_percentile_tier(80, 100) == 4
    assert get_percentile_tier(81, 100) == 5
    assert get_percentile_tier(100, 100) == 5


def test_get_percentile_tier_empty_pool_is_worst_tier():
    assert get_percentile_tier(1, 0) == 5
