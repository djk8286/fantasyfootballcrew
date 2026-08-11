"""
Shared fixtures for scoring engine tests.
"""
import pytest
from typing import Dict, Any

# Import the REAL default config rather than keeping a hand-duplicated copy
# here. A duplicate is exactly how this file went stale: scoring_engine's
# DEFAULT_SCORING keys were corrected to match Sleeper's actual API field
# names (see the comment above DEFAULT_SCORING in scoring_engine.py --
# pass_yds -> pass_yd, int -> pass_int, def_sack -> sack, etc.), but this
# file kept its own pre-rename copy, so every fixture below was silently
# testing against stat keys the real bonus/long-TD lookups (which use the
# real keys internally) could never match.
from app.services.scoring_engine import DEFAULT_SCORING


@pytest.fixture
def default_scoring() -> Dict[str, Any]:
    """Standard PPR scoring config (the app's real default, not a copy)."""
    return dict(DEFAULT_SCORING)


@pytest.fixture
def qb_stats() -> Dict[str, Any]:
    """Sample QB weekly stats: 300 yds, 3 TDs, 1 INT, 15 rush yds."""
    return {
        "pass_yd": 300,
        "pass_td": 3,
        "pass_int": 1,
        "pass_2pt": 0,
        "rush_yd": 15,
        "rush_td": 0,
    }


@pytest.fixture
def rb_stats() -> Dict[str, Any]:
    """Sample RB weekly stats: 100 rush yds, 1 TD, 4 rec, 30 rec yds."""
    return {
        "rush_yd": 100,
        "rush_td": 1,
        "rec": 4,
        "rec_yd": 30,
        "rec_td": 0,
    }


@pytest.fixture
def wr_stats() -> Dict[str, Any]:
    """Sample WR weekly stats: 8 rec, 120 yds, 1 TD."""
    return {
        "rec": 8,
        "rec_yd": 120,
        "rec_td": 1,
        "rush_yd": 0,
        "rush_td": 0,
    }


@pytest.fixture
def te_stats() -> Dict[str, Any]:
    """Sample TE weekly stats: 5 rec, 60 yds, 1 TD."""
    return {
        "rec": 5,
        "rec_yd": 60,
        "rec_td": 1,
    }


@pytest.fixture
def kicker_stats() -> Dict[str, Any]:
    """Sample K weekly stats: 2 FG (30-39), 1 FG (40-49), 3 XP."""
    return {
        "fgm_30_39": 2,
        "fgm_40_49": 1,
        "fgm_50_59": 0,
        "xpm": 3,
    }


@pytest.fixture
def defense_stats() -> Dict[str, Any]:
    """Sample DEF weekly stats: 3 sacks, 2 INTs, 1 fum rec, 1 TD, 45 return yds."""
    return {
        "sack": 3,
        "int": 2,
        "fum_rec": 1,
        "safe": 0,
        "def_td": 1,
        "st_fum_rec": 0,
        "st_td": 0,
        "kr_yd": 45,
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
