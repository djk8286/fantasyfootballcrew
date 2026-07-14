"""
Shared fixtures for scoring engine tests.
"""
import pytest
from typing import Dict, Any

# Default PPR scoring config used across many tests
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


@pytest.fixture
def default_scoring() -> Dict[str, Any]:
    """Standard PPR scoring config."""
    return dict(DEFAULT_SCORING)


@pytest.fixture
def qb_stats() -> Dict[str, Any]:
    """Sample QB weekly stats: 300 yds, 3 TDs, 1 INT, 15 rush yds."""
    return {
        "pass_yds": 300,
        "pass_td": 3,
        "int": 1,
        "pass_2pt": 0,
        "rush_yds": 15,
        "rush_td": 0,
    }


@pytest.fixture
def rb_stats() -> Dict[str, Any]:
    """Sample RB weekly stats: 100 rush yds, 1 TD, 4 rec, 30 rec yds."""
    return {
        "rush_yds": 100,
        "rush_td": 1,
        "rec": 4,
        "rec_yds": 30,
        "rec_td": 0,
    }


@pytest.fixture
def wr_stats() -> Dict[str, Any]:
    """Sample WR weekly stats: 8 rec, 120 yds, 1 TD."""
    return {
        "rec": 8,
        "rec_yds": 120,
        "rec_td": 1,
        "rush_yds": 0,
        "rush_td": 0,
    }


@pytest.fixture
def te_stats() -> Dict[str, Any]:
    """Sample TE weekly stats: 5 rec, 60 yds, 1 TD."""
    return {
        "rec": 5,
        "rec_yds": 60,
        "rec_td": 1,
    }


@pytest.fixture
def kicker_stats() -> Dict[str, Any]:
    """Sample K weekly stats: 2 FG (0-39), 1 FG (40-49), 3 XP."""
    return {
        "fg_0_39": 2,
        "fg_40_49": 1,
        "fg_50_plus": 0,
        "xp": 3,
    }


@pytest.fixture
def defense_stats() -> Dict[str, Any]:
    """Sample DEF weekly stats: 3 sacks, 2 INTs, 1 fum rec, 1 TD."""
    return {
        "def_sack": 3,
        "def_int": 2,
        "def_fum_rec": 1,
        "def_safety": 0,
        "def_td": 1,
        "st_fum_rec": 0,
        "st_td": 0,
        "def_ret_yds": 45,
    }


@pytest.fixture
def empty_stats() -> Dict[str, Any]:
    """Empty stats dict for edge case testing."""
    return {}


@pytest.fixture
def custom_rule_no_td_bonus() -> Dict[str, Any]:
    """A scoring config that disables the long TD bonus."""
    config = dict(DEFAULT_SCORING)
    config["bonus"] = {
        "pass_300_yds": 3,
        "rush_100_yds": 3,
        "rec_100_yds": 3,
    }
    return config
