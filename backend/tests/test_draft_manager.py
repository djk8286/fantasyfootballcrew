"""
Tests for the IDP (individual defensive player) ranking added to the
draft pool -- build_idp_rank_by_id and get_rank_score. Only the pure
ranking logic is covered here (no DB/network involved, Player() objects
are just plain attribute holders, never persisted); the rest of
get_draft_state (query building, pick history, etc.) is exercised via
manual live verification instead, matching this project's existing
practice for this file (see the CPU-draft-realism verification notes and
test_scheduler.py's own docstring for why).
"""
from app.models.player import Player
from app.services.scoring_engine import DEFAULT_SCORING
from app.services.draft_manager import build_idp_rank_by_id, get_rank_score, get_player_rank_from_list


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


def test_idp_players_ranked_best_production_first():
    # Fitzpatrick's real 2025 line scores 107 (see test_scoring_engine.py),
    # Bosa's scores 41 -- the better real season should get the lower
    # (better) rank number.
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
    ranks = build_idp_rank_by_id([good_db, weaker_dl], DEFAULT_SCORING)
    assert ranks[good_db.id] < ranks[weaker_dl.id]
    assert ranks[good_db.id] == 1001  # best real production ranks first, right after the static list's range


def test_non_idp_positions_excluded_from_idp_ranking():
    qb = _player("p3", "QB", last="Someone")
    lb = _player("p4", "LB", last="Somebody", last_season_stats={"idp_tkl_solo": 10}, last_season_year=2025)
    ranks = build_idp_rank_by_id([qb, lb], DEFAULT_SCORING)
    assert qb.id not in ranks
    assert lb.id in ranks


def test_zero_production_idp_player_still_gets_ranked():
    """No real stats at all -- still gets a real (if last-place) rank,
    not silently dropped."""
    no_stats_lb = _player("p5", "LB", last="Unknown")
    ranks = build_idp_rank_by_id([no_stats_lb], DEFAULT_SCORING)
    assert ranks[no_stats_lb.id] == 1001


def test_get_rank_score_uses_static_list_first():
    # A name that IS on the static tier list should use that rank, not
    # fall through to IDP ranking, even if their position happened to be
    # DB/DL/LB (it never is in the real static list, but confirm the
    # precedence is right either way).
    mccaffrey = _player("p6", "RB", first="Christian", last="McCaffrey")
    static_rank = get_player_rank_from_list("Christian McCaffrey")
    assert static_rank != 1000
    assert get_rank_score(mccaffrey, idp_rank_by_id={}) == static_rank


def test_get_rank_score_falls_back_to_idp_rank():
    lb = _player("p7", "LB", last="Nobody")
    assert get_rank_score(lb, idp_rank_by_id={"p7": 1050}) == 1050


def test_get_rank_score_falls_back_to_1000_when_uncovered():
    kicker = _player("p8", "K", last="Nobody")
    assert get_rank_score(kicker, idp_rank_by_id={}) == 1000


def test_get_rank_score_idp_position_never_uses_static_list_even_on_name_collision():
    """Regression test for a real, confirmed case: a backup LB happens to
    share the exact name "Justin Jefferson" with the real star WR, who IS
    on the static tier-1 list. An LB must never inherit a WR's static rank
    just because get_player_rank_from_list only matches on name."""
    wr_rank = get_player_rank_from_list("Justin Jefferson")
    assert wr_rank != 1000  # sanity check the real WR is genuinely on the list
    same_name_lb = _player("p9", "LB", first="Justin", last="Jefferson")
    # Not covered by idp_rank_by_id (e.g. no stats yet) -- must still fall
    # back to the generic 1000, never the WR's static rank.
    assert get_rank_score(same_name_lb, idp_rank_by_id={}) == 1000
    assert get_rank_score(same_name_lb, idp_rank_by_id={"p9": 1500}) == 1500
