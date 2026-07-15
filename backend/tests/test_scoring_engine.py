"""
Tests for the fantasy football scoring engine.

Covers:
- calculate_player_score for each position
- Edge cases: empty stats, missing stats, zero values, negative values
- Bonus calculations (thresholds)
- Long TD estimation
- Custom rules
- Weekly lineup scoring
- Optimal lineup calculation
- Scoring config validation
"""

from decimal import Decimal
from typing import Dict, Any

import pytest

from app.services.scoring_engine import (
    calculate_player_score,
    calculate_weekly_score,
    calculate_optimal_lineup,
    validate_scoring_config,
    _calculate_bonus,
    _calculate_custom,
    _estimate_long_tds,
    DEFAULT_SCORING,
)


# ─── QB scoring ──────────────────────────────────────────────────────


class TestQBScoring:
    def test_basic_qb(self, default_scoring, qb_stats):
        """300 pass yds (12) + 3 pass TDs (12) - 1 INT (-2) + 15 rush yds (1.5) = 23.5"""
        score = calculate_player_score(qb_stats, default_scoring, "QB")
        assert score == 26.5

    def test_qb_with_rush_td(self, default_scoring):
        """QB with both passing and rushing TDs."""
        stats = {
            "pass_yds": 250,
            "pass_td": 2,
            "int": 0,
            "rush_yds": 40,
            "rush_td": 1,
        }
        score = calculate_player_score(stats, default_scoring, "QB")
        # 250*0.04 (10) + 2*4 (8) + 40*0.1 (4) + 1*6 (6) = 28
        assert score == 28.0

    def test_qb_with_2pt(self, default_scoring):
        """QB with a 2-point conversion."""
        stats = {"pass_yds": 200, "pass_td": 1, "int": 0, "pass_2pt": 1}
        score = calculate_player_score(stats, default_scoring, "QB")
        # 200*0.04 (8) + 1*4 (4) + 1*2 (2) = 14
        assert score == 14.0

    def test_qb_negative_stats(self, default_scoring):
        """QB with more INTs than TDs."""
        stats = {"pass_yds": 150, "pass_td": 0, "int": 3}
        score = calculate_player_score(stats, default_scoring, "QB")
        # 150*0.04 (6) + 0 - 3*2 (-6) = 0
        assert score == 0.0

    def test_qb_bonus_300(self, default_scoring, qb_stats):
        """QB with 300+ passing yards gets the 300-yard bonus."""
        # qb_stats has 300 pass_yds => should trigger pass_300_yds bonus
        score = calculate_player_score(qb_stats, default_scoring, "QB")
        # 23.5 + 3 (bonus) = 26.5
        assert score == 26.5

    def test_qb_bonus_400(self, default_scoring):
        """QB with 400+ yards gets the 300-yard bonus (400 threshold also enabled)."""
        stats = {"pass_yds": 410, "pass_td": 3, "int": 0}
        score = calculate_player_score(stats, default_scoring, "QB")
        # 410*0.04 (16.4) + 3*4 (12) + 3 (300_yd bonus) = 31.4
        assert score == 31.4


# ─── RB scoring ──────────────────────────────────────────────────────


class TestRBScoring:
    def test_basic_rb(self, default_scoring, rb_stats):
        """100 rush yds (10) + 1 rush TD (6) + 4 rec (4) + 30 rec yds (3) + 3 bonus = 26"""
        score = calculate_player_score(rb_stats, default_scoring, "RB")
        assert score == 26.0

    def test_rb_bonus_100(self, default_scoring, rb_stats):
        """RB with 100+ rushing yards gets the 100-yard bonus."""
        # rb_stats has 100 rush_yds => should trigger rush_100_yds bonus
        score = calculate_player_score(rb_stats, default_scoring, "RB")
        # 23 + 3 (bonus) = 26
        assert score == 26.0

    def test_rb_passing_game_rb(self, default_scoring):
        """RB who also catches passes (receiving work)."""
        stats = {
            "rush_yds": 45,
            "rush_td": 0,
            "rec": 7,
            "rec_yds": 80,
            "rec_td": 1,
        }
        score = calculate_player_score(stats, default_scoring, "RB")
        # 45*0.1 (4.5) + 7*1 (7) + 80*0.1 (8) + 1*6 (6) = 25.5
        assert score == 25.5

    def test_rb_zero_carries(self, default_scoring):
        """RB with no touches."""
        stats = {"rush_yds": 0, "rush_td": 0, "rec": 0, "rec_yds": 0}
        score = calculate_player_score(stats, default_scoring, "RB")
        assert score == 0.0

    def test_rb_goal_line_back(self, default_scoring):
        """RB with short TD but minimal yards."""
        stats = {"rush_yds": 5, "rush_td": 2}
        score = calculate_player_score(stats, default_scoring, "RB")
        # 5*0.1 (0.5) + 2*6 (12) = 12.5
        assert score == 12.5


# ─── WR scoring ──────────────────────────────────────────────────────


class TestWRScoring:
    def test_basic_wr(self, default_scoring, wr_stats):
        """8 rec (8) + 120 rec yds (12) + 1 rec TD (6) + 3 bonus = 29"""
        score = calculate_player_score(wr_stats, default_scoring, "WR")
        assert score == 29.0

    def test_wr_bonus_100(self, default_scoring, wr_stats):
        """WR with 100+ receiving yards gets the bonus."""
        # wr_stats has 120 rec_yds => trigger rec_100_yds bonus
        score = calculate_player_score(wr_stats, default_scoring, "WR")
        # 26 + 3 (bonus) = 29
        assert score == 29.0

    def test_wr_with_rush(self, default_scoring):
        """WR who also gets a carry (jet sweep / end around)."""
        stats = {"rec": 5, "rec_yds": 60, "rec_td": 0, "rush_yds": 15, "rush_td": 1}
        score = calculate_player_score(stats, default_scoring, "WR")
        # 5*1 (5) + 60*0.1 (6) + 15*0.1 (1.5) + 1*6 (6) = 18.5
        assert score == 18.5

    def test_wr_slot_ppr_merchant(self, default_scoring):
        """High-volume PPR slot receiver with short gains."""
        stats = {"rec": 12, "rec_yds": 85, "rec_td": 0}
        score = calculate_player_score(stats, default_scoring, "WR")
        # 12*1 (12) + 85*0.1 (8.5) = 20.5
        assert score == 20.5


# ─── TE scoring ──────────────────────────────────────────────────────


class TestTEScoring:
    def test_basic_te(self, default_scoring, te_stats):
        """5 rec (5) + 60 rec yds (6) + 1 rec TD (6) = 17"""
        score = calculate_player_score(te_stats, default_scoring, "TE")
        assert score == 17.0

    def test_te_elite(self, default_scoring):
        """Elite TE performance."""
        stats = {"rec": 10, "rec_yds": 150, "rec_td": 2}
        score = calculate_player_score(stats, default_scoring, "TE")
        # 10*1 (10) + 150*0.1 (15) + 2*6 (12) + 3 (rec_100 bonus) = 40
        assert score == 40.0


# ─── Kicker scoring ─────────────────────────────────────────────────


class TestKickerScoring:
    def test_basic_kicker(self, default_scoring, kicker_stats):
        """2 FG (0-39) (6) + 1 FG (40-49) (4) + 3 XP (3) = 13"""
        score = calculate_player_score(kicker_stats, default_scoring, "K")
        assert score == 13.0

    def test_kicker_long_fg(self, default_scoring):
        """Kicker hitting a 50+ yarder."""
        stats = {"fg_0_39": 0, "fg_40_49": 0, "fg_50_plus": 2, "xp": 1}
        score = calculate_player_score(stats, default_scoring, "K")
        # 2*5 (10) + 1*1 (1) = 11
        assert score == 11.0

    def test_kicker_perfect_day(self, default_scoring):
        """Perfect day for a kicker: 5/5, long range."""
        stats = {"fg_0_39": 2, "fg_40_49": 2, "fg_50_plus": 1, "xp": 4}
        score = calculate_player_score(stats, default_scoring, "K")
        # 2*3 (6) + 2*4 (8) + 1*5 (5) + 4*1 (4) = 23
        assert score == 23.0


# ─── Defense scoring ──────────────────────────────────────────────────


class TestDefenseScoring:
    def test_basic_defense(self, default_scoring, defense_stats):
        """3 sacks (3) + 2 INT (4) + 1 fum rec (2) + 1 TD (6) + 45 ret yds (0.9) = 15.9"""
        score = calculate_player_score(defense_stats, default_scoring, "DEF")
        assert score == 15.9

    def test_defense_shutout(self, default_scoring):
        """Defense with a special teams TD."""
        stats = {"def_sack": 2, "def_int": 1, "def_fum_rec": 0, "def_td": 0, "st_td": 1}
        score = calculate_player_score(stats, default_scoring, "DEF")
        # 2*1 (2) + 1*2 (2) + 1*6 (6) = 10
        assert score == 10.0


# ─── Edge cases ──────────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_stats(self, default_scoring):
        """Empty stats should score 0."""
        score = calculate_player_score({}, default_scoring, "QB")
        assert score == 0.0

    def test_none_stats(self, default_scoring):
        """Stats with None values should be handled gracefully."""
        stats = {"pass_yds": None, "pass_td": 2, "int": None}
        score = calculate_player_score(stats, default_scoring, "QB")
        # 2*4 = 8
        assert score == 8.0

    def test_empty_scoring_config(self, qb_stats):
        """Empty scoring config should score 0."""
        score = calculate_player_score(qb_stats, {}, "QB")
        assert score == 0.0

    def test_none_position(self, default_scoring, rb_stats):
        """Position=None should still calculate correctly."""
        score = calculate_player_score(rb_stats, default_scoring, None)
        # Same as RB: 23 + 3 (bonus) = 26
        assert score == 26.0

    def test_all_stat_types_as_strings(self, default_scoring):
        """Stats as string numbers should still work."""
        stats = {"pass_yds": "250", "pass_td": "2", "int": "0"}
        score = calculate_player_score(stats, default_scoring, "QB")
        # 250*0.04 (10) + 2*4 (8) = 18
        assert score == 18.0

    def test_missing_stat_is_zero(self, default_scoring):
        """Missing stat keys should not error."""
        stats = {"pass_yds": 200}  # no pass_td, no int
        score = calculate_player_score(stats, default_scoring, "QB")
        # 200*0.04 = 8
        assert score == 8.0

    def test_negative_yards(self, default_scoring):
        """A RB with negative rushing yards (rare but possible)."""
        stats = {"rush_yds": -5, "rush_td": 0, "rec": 1, "rec_yds": 8}
        score = calculate_player_score(stats, default_scoring, "RB")
        # -5*0.1 (-0.5) + 1*1 (1) + 8*0.1 (0.8) = 1.3
        assert score == 1.3


# ─── Bonus calculations ──────────────────────────────────────────────


class TestBonuses:
    def test_no_bonus_below_threshold(self, default_scoring):
        """No bonus triggered when below threshold."""
        stats = {"pass_yds": 280, "rush_yds": 95, "rec_yds": 90}
        bonus = _calculate_bonus(stats, default_scoring["bonus"])
        assert bonus == 0.0

    def test_300_passing_bonus(self, default_scoring):
        stats = {"pass_yds": 305}
        bonus = _calculate_bonus(stats, default_scoring["bonus"])
        assert bonus == 3.0

    def test_100_rushing_bonus(self, default_scoring):
        stats = {"rush_yds": 150}
        bonus = _calculate_bonus(stats, default_scoring["bonus"])
        assert bonus == 3.0

    def test_100_receiving_bonus(self, default_scoring):
        stats = {"rec_yds": 100}
        bonus = _calculate_bonus(stats, default_scoring["bonus"])
        assert bonus == 3.0

    def test_150_rushing_bonus(self, default_scoring):
        """Additional thresholds enabled in default config."""
        bonus_rules = {"rush_150_yds": 3}
        stats = {"rush_yds": 151}
        bonus = _calculate_bonus(stats, bonus_rules)
        assert bonus == 3.0

    def test_200_rushing_bonus(self, default_scoring):
        bonus_rules = {"rush_200_yds": 3}
        stats = {"rush_yds": 250}
        bonus = _calculate_bonus(stats, bonus_rules)
        assert bonus == 3.0

    def test_multiple_bonuses(self, default_scoring):
        """Player can trigger multiple bonuses."""
        stats = {"pass_yds": 320, "rush_yds": 110, "rec_yds": 50}
        bonus = _calculate_bonus(stats, default_scoring["bonus"])
        # pass_300_yds (3) + rush_100_yds (3) = 6
        assert bonus == 6.0

    def test_empty_bonus_rules(self):
        bonus = _calculate_bonus({"pass_yds": 400}, {})
        assert bonus == 0.0

    def test_none_stats_in_bonus(self, default_scoring):
        stats = {"pass_yds": None}
        bonus = _calculate_bonus(stats, default_scoring["bonus"])
        assert bonus == 0.0


# ─── Long TD estimation ─────────────────────────────────────────────


class TestLongTDEstimation:
    def test_rb_long_td(self):
        """RB with high YPC has long TDs."""
        stats = {"rush_yds": 150, "rush_td": 2, "rec_yds": 0, "rec_td": 0}
        # 150/2 = 75 yds per TD > 40 => all 2 TDs are "long"
        long_tds = _estimate_long_tds(stats, "RB")
        assert long_tds == 2

    def test_rb_short_td(self):
        """RB with goal-line TDs has no long TDs."""
        stats = {"rush_yds": 30, "rush_td": 3, "rec_yds": 0, "rec_td": 0}
        # 30/3 = 10 yds per TD < 40 => estimate fractional
        long_tds = _estimate_long_tds(stats, "RB")
        assert long_tds == 0

    def test_wr_deep_threat(self):
        """WR with deep TDs."""
        stats = {"rec_yds": 200, "rec_td": 2, "rush_yds": 0, "rush_td": 0}
        # 200/2 = 100 yds per TD > 40 => all 2 are long
        long_tds = _estimate_long_tds(stats, "WR")
        assert long_tds == 2

    def test_wr_slot_receiver(self):
        """Slot WR with short TDs."""
        stats = {"rec_yds": 80, "rec_td": 3, "rush_yds": 0, "rush_td": 0}
        # 80/3 ≈ 26.7 < 40 => 0 long TDs
        long_tds = _estimate_long_tds(stats, "WR")
        assert long_tds == 0

    def te_mixed_tds(self):
        """TE with one deep and one short TD (mixed)."""
        stats = {"rec_yds": 115, "rec_td": 2, "rush_yds": 0, "rush_td": 0}
        # 115/2 = 57.5 > 40 => all 2 long
        long_tds = _estimate_long_tds(stats, "TE")
        assert long_tds == 2

    def qb_long_passing(self):
        """QB with 400+ yards and 4+ TDs should get some credit."""
        stats = {"pass_yds": 420, "pass_td": 4}
        long_tds = _estimate_long_tds(stats, "QB")
        assert long_tds >= 1

    def test_no_tds_no_long(self):
        """No TDs means no long TDs."""
        stats = {"rush_yds": 100, "rush_td": 0}
        long_tds = _estimate_long_tds(stats, "RB")
        assert long_tds == 0

    def test_explicit_long_td_stat(self):
        """When explicit long_td stats are provided, use those."""
        stats = {"rush_yds": 50, "rush_td": 2, "long_rush_td": 1}
        long_tds = _estimate_long_tds(stats, "RB")
        assert long_tds == 1


# ─── Custom rules ────────────────────────────────────────────────────


class TestCustomRules:
    def test_custom_threshold(self):
        """Custom rule: bonus points when a stat exceeds a threshold."""
        rules = [
            {"stat_name": "pass_yds", "operator": ">=", "threshold": 350, "points": 5}
        ]
        points = _calculate_custom({"pass_yds": 380}, rules)
        assert points == 5.0

    def test_custom_not_met(self):
        """Custom rule not triggered when below threshold."""
        rules = [
            {"stat_name": "pass_yds", "operator": ">=", "threshold": 350, "points": 5}
        ]
        points = _calculate_custom({"pass_yds": 300}, rules)
        assert points == 0.0

    def test_custom_per_unit(self):
        """Custom rule: points per unit above threshold."""
        rules = [
            {"stat_name": "rush_yds", "operator": "per_unit", "threshold": 100, "points": 0.5}
        ]
        points = _calculate_custom({"rush_yds": 120}, rules)
        # 120 - 100 = 20 * 0.5 = 10
        assert points == 10.0

    def test_custom_with_multiplier(self):
        """Custom rule with multiplier."""
        rules = [
            {"stat_name": "rec", "operator": ">=", "threshold": 10, "points": 3, "multiplier": 2}
        ]
        points = _calculate_custom({"rec": 12}, rules)
        # 3 * 2 = 6
        assert points == 6.0

    def test_custom_multiple_rules(self):
        """Multiple custom rules combining."""
        rules = [
            {"stat_name": "rush_yds", "operator": ">=", "threshold": 100, "points": 3},
            {"stat_name": "rec", "operator": ">=", "threshold": 5, "points": 2},
        ]
        points = _calculate_custom({"rush_yds": 120, "rec": 7}, rules)
        assert points == 5.0

    def test_custom_empty_rules(self):
        points = _calculate_custom({"pass_yds": 400}, [])
        assert points == 0.0

    def test_custom_missing_stat(self):
        """Rule references a stat that player doesn't have."""
        rules = [{"stat_name": "made_up_stat", "operator": ">=", "threshold": 1, "points": 5}]
        points = _calculate_custom({"pass_yds": 300}, rules)
        assert points == 0.0

    def test_custom_eq_operator(self):
        rules = [{"stat_name": "rush_td", "operator": "==", "threshold": 3, "points": 5}]
        points = _calculate_custom({"rush_td": 3}, rules)
        assert points == 5.0

    def test_custom_lt_operator(self):
        rules = [{"stat_name": "int", "operator": "<", "threshold": 1, "points": 3}]
        points = _calculate_custom({"int": 0}, rules)
        assert points == 3.0

    def test_custom_invalid_rule(self):
        """Malformed rule (not a dict) should be skipped."""
        rules = ["invalid_rule", {"stat_name": "pass_td", "operator": ">=", "threshold": 2, "points": 3}]
        points = _calculate_custom({"pass_td": 3}, rules)
        assert points == 3.0


# ─── Weekly lineup scoring ──────────────────────────────────────────


class TestWeeklyScoring:
    def test_full_roster_weekly(self, default_scoring, qb_stats, rb_stats, wr_stats, te_stats, kicker_stats, defense_stats):
        """Calculate weekly score for a full starting lineup."""
        roster = ["player_qb", "player_rb", "player_wr", "player_te", "player_k", "player_def"]
        week_stats = {
            "player_qb": qb_stats,
            "player_rb": rb_stats,
            "player_wr": wr_stats,
            "player_te": te_stats,
            "player_k": {"fg_0_39": 1, "fg_40_49": 1, "fg_50_plus": 0, "xp": 2},
            "player_def": {"def_sack": 2, "def_int": 1, "def_fum_rec": 0, "def_td": 0},
        }
        positions = {
            "player_qb": "QB",
            "player_rb": "RB",
            "player_wr": "WR",
            "player_te": "TE",
            "player_k": "K",
            "player_def": "DEF",
        }

        result = calculate_weekly_score(roster, week_stats, default_scoring, positions)

        assert "total" in result
        assert "breakdown" in result
        assert len(result["breakdown"]) == 6
        assert result["total"] > 0

        # Each player should have score, stats, and position
        for pid in roster:
            bd = result["breakdown"][pid]
            assert "score" in bd
            assert "stats" in bd
            assert "position" in bd

    def test_empty_roster(self, default_scoring):
        """Empty roster should return 0."""
        result = calculate_weekly_score([], {}, default_scoring, {})
        assert result["total"] == 0.0
        assert result["breakdown"] == {}

    def test_player_without_stats(self, default_scoring):
        """Player in roster but missing from week_stats."""
        roster = ["player_a", "player_b"]
        week_stats = {"player_a": {"pass_yds": 200, "pass_td": 1}}
        positions = {"player_a": "QB", "player_b": "RB"}
        result = calculate_weekly_score(roster, week_stats, default_scoring, positions)
        assert result["breakdown"]["player_a"]["score"] > 0
        assert result["breakdown"]["player_b"]["score"] == 0.0


# ─── Optimal lineup calculation ──────────────────────────────────────


class TestOptimalLineup:
    def test_basic_optimal(self, default_scoring):
        """Basic optimal lineup with standard 1QB/2RB/2WR/1TE/1FLEX."""
        roster = {
            "qb1": {"stats": {"pass_yds": 300, "pass_td": 3}, "position": "QB", "name": "QB Elite"},
            "rb1": {"stats": {"rush_yds": 120, "rush_td": 1}, "position": "RB", "name": "RB Stud"},
            "rb2": {"stats": {"rush_yds": 80, "rush_td": 0, "rec": 3, "rec_yds": 25}, "position": "RB", "name": "RB Solid"},
            "rb3": {"stats": {"rush_yds": 15, "rush_td": 0}, "position": "RB", "name": "RB Bench"},
            "wr1": {"stats": {"rec": 8, "rec_yds": 110, "rec_td": 1}, "position": "WR", "name": "WR WR1"},
            "wr2": {"stats": {"rec": 5, "rec_yds": 70}, "position": "WR", "name": "WR WR2"},
            "wr3": {"stats": {"rec": 2, "rec_yds": 20}, "position": "WR", "name": "WR WR3"},
            "te1": {"stats": {"rec": 4, "rec_yds": 45, "rec_td": 1}, "position": "TE", "name": "TE Stud"},
            "te2": {"stats": {"rec": 1, "rec_yds": 8}, "position": "TE", "name": "TE Backup"},
            "k1": {"stats": {"fg_0_39": 2, "xp": 2}, "position": "K", "name": "K Kicker"},
            "def1": {"stats": {"def_sack": 3, "def_int": 2}, "position": "DEF", "name": "DST"},
        }

        result = calculate_optimal_lineup(roster, default_scoring)

        assert result["optimal_score"] > 0
        assert len(result["lineup"]) == 9  # 1QB + 2RB + 2WR + 1TE + 1FLEX + 1K + 1DEF
        assert len(result["benched"]) == 2  # rb3, wr3

        # Check that we have exactly 1 QB, 2 RB, 2 WR, 1 TE, 1 FLEX, 1 K, 1 DEF = 9 total
        slots = [slot["slot"] for slot in result["lineup"]]
        assert slots.count("QB") == 1
        assert slots.count("RB") == 2
        assert slots.count("WR") == 2
        assert slots.count("TE") == 1
        assert slots.count("FLEX") >= 0
        assert slots.count("K") == 1
        assert slots.count("DEF") == 1

    def test_flex_picks_best_remaining(self, default_scoring):
        """FLEX spot should pick the highest-scoring eligible player."""
        # Two good RBs, one good WR - FLEX should go to the best of the remaining
        roster = {
            "rb1": {"stats": {"rush_yds": 150, "rush_td": 2}, "position": "RB", "name": "RB Elite"},
            "rb2": {"stats": {"rush_yds": 100, "rush_td": 1}, "position": "RB", "name": "RB Good"},
            "rb3": {"stats": {"rush_yds": 5, "rush_td": 0}, "position": "RB", "name": "RB Trash"},
            "wr1": {"stats": {"rec": 6, "rec_yds": 90}, "position": "WR", "name": "WR Decent"},
        }
        # Only 1 RB slot needed (n_rb=1) but FLEX stays
        result = calculate_optimal_lineup(roster, default_scoring, n_qb=0, n_rb=1, n_wr=0, n_te=0, n_flex=1, n_k=0, n_def=0)

        # rb1 should be RB slot, rb2 should be FLEX (better than wr1)
        rb_slot = [s for s in result["lineup"] if s["slot"] == "RB"]
        flex_slot = [s for s in result["lineup"] if s["slot"] == "FLEX"]
        assert len(rb_slot) == 1
        assert len(flex_slot) == 1
        assert flex_slot[0]["player_id"] == "rb2"  # rb2 > wr1 in score

    def test_empty_roster_optimal(self, default_scoring):
        """Empty roster should return empty lineup."""
        result = calculate_optimal_lineup({}, default_scoring)
        assert result["optimal_score"] == 0.0
        assert result["lineup"] == []
        assert result["benched"] == []

    def test_no_k_or_def_required(self, default_scoring):
        """When n_k=0 and n_def=0, no K or DEF slots."""
        roster = {
            "qb1": {"stats": {"pass_yds": 300, "pass_td": 3}, "position": "QB", "name": "QB1"},
            "rb1": {"stats": {"rush_yds": 100, "rush_td": 1}, "position": "RB", "name": "RB1"},
            "wr1": {"stats": {"rec": 6, "rec_yds": 90, "rec_td": 1}, "position": "WR", "name": "WR1"},
        }
        result = calculate_optimal_lineup(roster, default_scoring, n_k=0, n_def=0, n_te=0, n_flex=0)
        slots = [s["slot"] for s in result["lineup"]]
        assert "K" not in slots
        assert "DEF" not in slots


# ─── Config validation ──────────────────────────────────────────────


class TestConfigValidation:
    def test_valid_default_config(self):
        """Default scoring config should be valid."""
        warnings = validate_scoring_config(DEFAULT_SCORING)
        assert warnings == []

    def test_empty_config(self):
        """Empty config should warn."""
        warnings = validate_scoring_config({})
        assert len(warnings) > 0
        assert "empty" in warnings[0].lower()

    def test_unknown_category(self):
        """Unknown category should warn."""
        warnings = validate_scoring_config({"unknown_cat": {"a": 1}})
        assert any("unknown" in w.lower() for w in warnings)

    def test_invalid_points(self):
        """Invalid points value should warn."""
        warnings = validate_scoring_config({"passing": {"pass_td": "free"}})
        assert any("invalid" in w.lower() for w in warnings)

    def test_custom_rules_not_list(self):
        """Custom category should be a list."""
        warnings = validate_scoring_config({"custom": "not_a_list"})
        assert any("custom" in w.lower() for w in warnings)

    def test_custom_rule_missing_stat(self):
        """Custom rule missing 'stat_name' should warn."""
        warnings = validate_scoring_config({"custom": [{"points": 5}]})
        assert any("stat_name" in w for w in warnings)

    def test_config_with_extra_leagues_rules(self):
        """A non-dict category (extra leagues has no dict for 'defense')."""
        clean_config = {
            "passing": {"pass_td": 4},
            "rushing": {"rush_td": 6},
        }
        warnings = validate_scoring_config(clean_config)
        assert warnings == []


# ─── Integration: Stat equality across all positions ────────────────


class TestIntegration:
    def test_qb_vs_rb_comparison(self, default_scoring):
        """Compare a QB's score to an RB's score using consistent rules."""
        qb = {"pass_yds": 250, "pass_td": 2, "int": 0}
        rb = {"rush_yds": 100, "rush_td": 1, "rec": 4, "rec_yds": 40}

        qb_score = calculate_player_score(qb, default_scoring, "QB")
        rb_score = calculate_player_score(rb, default_scoring, "RB")

        # QB: 250*0.04 (10) + 2*4 (8) = 18
        # RB: 100*0.1 (10) + 1*6 (6) + 4*1 (4) + 40*0.1 (4) + 3 (bonus) = 27
        assert qb_score == 18.0
        assert rb_score == 27.0

    def test_full_team_projection(self, default_scoring):
        """Simulate a full team's weekly scoring."""
        team = {
            "qb": {"pass_yds": 280, "pass_td": 2, "int": 1, "rush_yds": 20},
            "rb1": {"rush_yds": 85, "rush_td": 1, "rec": 3, "rec_yds": 20},
            "rb2": {"rush_yds": 60, "rush_td": 0, "rec": 5, "rec_yds": 45},
            "wr1": {"rec": 7, "rec_yds": 100, "rec_td": 1},
            "wr2": {"rec": 4, "rec_yds": 55, "rec_td": 0},
            "te": {"rec": 3, "rec_yds": 35, "rec_td": 0},
            "flex": {"rec": 6, "rec_yds": 80, "rec_td": 0},
            "k": {"fg_0_39": 1, "fg_40_49": 1, "xp": 3},
            "def": {"def_sack": 3, "def_int": 1, "def_td": 1},
        }
        positions = {
            "qb": "QB", "rb1": "RB", "rb2": "RB",
            "wr1": "WR", "wr2": "WR", "te": "TE", "flex": "WR",
            "k": "K", "def": "DEF",
        }
        roster = list(team.keys())
        result = calculate_weekly_score(roster, team, default_scoring, positions)

        # All 9 players should have scores
        assert len(result["breakdown"]) == 9
        assert result["total"] > 80  # Realistic fantasy total

    def test_standard_ppr_rules(self, default_scoring):
        """Verify the default config follows standard PPR rules."""
        config = default_scoring
        assert config["receiving"]["rec"] == 1.0  # 1 PPR
        assert config["passing"]["pass_td"] == 4  # 4pt pass TD
        assert config["rushing"]["rush_td"] == 6  # 6pt rush TD
        assert config["receiving"]["rec_td"] == 6  # 6pt rec TD
        assert config["passing"]["int"] == -2  # -2 for INT
