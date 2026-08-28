"""
Tests for the real player ranking that replaced draft_manager's old
static ~194-name tier list (get_tier_names, removed -- it read like a
stale 2024-offseason snapshot with zero 2025-class players and
still-ranked declining/retired-adjacent veterans; anyone not manually
added fell to a fixed fallback rank of 1000, worse than every listed
player).

build_rank_by_id/get_rank_score/get_percentile_tier now rank primarily
by Player.search_rank -- Sleeper's own real, live, year-round overall
fantasy-relevance rank (confirmed directly against the real API: a true
ADP-style signal reflecting the CURRENT season, unlike last season's box
score), falling back to real last-season production
(effective_season_stats + calculate_player_score) only for players with
no usable search_rank at all (confirmed: team DEF entries never carry
one).

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
            last_season_stats=None, last_season_year=None, search_rank=None):
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
        search_rank=search_rank,
    )


def test_players_ranked_by_search_rank_first():
    # A real ADP-style rank should decide ordering directly, regardless
    # of last-season production either player happens to have.
    better = _player("p1", "RB", last="BetterRank", search_rank=5,
                      last_season_stats={"rush_yd": 100})  # weak production
    worse = _player("p2", "RB", last="WorseRank", search_rank=50,
                     last_season_stats={"rush_yd": 2000, "rush_td": 20})  # strong production
    ranks = build_rank_by_id([better, worse], DEFAULT_SCORING)
    assert ranks[better.id] == 1
    assert ranks[worse.id] == 2


def test_a_current_rookie_outranks_a_stale_veteran_via_search_rank():
    """Direct regression test for the reported bug: under both the old
    static list AND last session's production-based-only fix, a name/
    player simply not accounted for could rank below a name that
    happened to be tracked. A real 2025-class rookie's low (good)
    search_rank must outrank a declining veteran's high (bad) one."""
    breakout_rookie = _player("p10", "RB", first="Breakout", last="Rookie", search_rank=12)
    declining_veteran = _player("p11", "QB", first="Declining", last="Veteran", search_rank=196)
    ranks = build_rank_by_id([breakout_rookie, declining_veteran], DEFAULT_SCORING)
    assert ranks[breakout_rookie.id] < ranks[declining_veteran.id]


def test_players_without_search_rank_fall_back_to_production_and_rank_after_ranked_players():
    ranked = _player("p1", "RB", last="Ranked", search_rank=1)
    unranked_strong = _player("p2", "RB", last="UnrankedStrong", search_rank=None,
                               last_season_stats={"rush_yd": 2000, "rush_td": 20})
    unranked_weak = _player("p3", "RB", last="UnrankedWeak", search_rank=None,
                             last_season_stats={"rush_yd": 100})
    ranks = build_rank_by_id([ranked, unranked_strong, unranked_weak], DEFAULT_SCORING)
    # The search_rank-ranked player always wins, even over strong fallback production.
    assert ranks[ranked.id] == 1
    # Among the fallback pool, real production still decides order.
    assert ranks[unranked_strong.id] < ranks[unranked_weak.id]


def test_search_rank_sentinel_treated_as_unranked():
    """Sleeper's own 'not really ranked' sentinel (e.g. an inactive
    player) must not be trusted as a real rank -- falls through to the
    production fallback like search_rank=None would."""
    sentinel = _player("p1", "RB", last="Sentinel", search_rank=9_999_999,
                        last_season_stats={"rush_yd": 500})
    real_rank = _player("p2", "RB", last="RealRank", search_rank=250)
    ranks = build_rank_by_id([sentinel, real_rank], DEFAULT_SCORING)
    assert ranks[real_rank.id] < ranks[sentinel.id]


def test_team_defense_has_no_search_rank_and_uses_production_fallback():
    """Confirmed directly against the real API: team DEF entries never
    carry a search_rank field at all -- must still get a real (if
    fallback) rank, not crash or get silently dropped."""
    defense = _player("p1", "DEF", first="Denver", last="Broncos", search_rank=None,
                       last_season_stats={"def_sack": 40, "def_int": 15})
    ranks = build_rank_by_id([defense], DEFAULT_SCORING)
    assert ranks[defense.id] == 1


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
