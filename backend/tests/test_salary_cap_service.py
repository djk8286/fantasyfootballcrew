"""
Tests for salary_cap_service's pure formulas and settings merge (Phase 5
Step 2, "Salary-Cap + Contract Leagues"). No DB needed for the
interpolation formulas themselves -- team_cap_summary/release_player
(which do touch the DB) are covered by later steps' integration tests
(test_salary_cap_draft.py, test_salary_cap_waivers.py) once there's
real Contract data to exercise them against.
"""
from app.models.league import League
from app.services.salary_cap_service import (
    DEFAULT_SALARY_CAP_SETTINGS,
    get_salary_cap_settings,
    compute_pick_slot_salary,
    compute_waiver_salary,
    WAIVER_SALARY_SCALE_MAX,
)


def _settings(**overrides):
    merged = dict(DEFAULT_SALARY_CAP_SETTINGS)
    merged.update(overrides)
    return merged


class _FakePlayer:
    def __init__(self, first_name, last_name, position="RB", last_season_stats=None):
        self.first_name = first_name
        self.last_name = last_name
        self.position = position
        self.last_season_stats = last_season_stats or {}


def test_compute_pick_slot_salary_top_pick_gets_top_salary():
    settings = _settings(top_salary=50.0, bottom_salary=1.0)
    assert compute_pick_slot_salary(1, 100, settings) == 50.0


def test_compute_pick_slot_salary_last_pick_gets_bottom_salary():
    settings = _settings(top_salary=50.0, bottom_salary=1.0)
    assert compute_pick_slot_salary(100, 100, settings) == 1.0


def test_compute_pick_slot_salary_midpoint_is_linear():
    settings = _settings(top_salary=100.0, bottom_salary=0.0)
    # Pick 51 of 101 total picks -- exact midpoint (frac = 0.5).
    assert compute_pick_slot_salary(51, 101, settings) == 50.0


def test_compute_pick_slot_salary_strictly_decreasing():
    settings = _settings(top_salary=50.0, bottom_salary=1.0)
    salaries = [compute_pick_slot_salary(p, 20, settings) for p in range(1, 21)]
    assert salaries == sorted(salaries, reverse=True)
    assert salaries[0] > salaries[-1]


def test_compute_pick_slot_salary_handles_single_pick_league():
    settings = _settings(top_salary=50.0, bottom_salary=1.0)
    assert compute_pick_slot_salary(1, 1, settings) == 50.0


def test_compute_waiver_salary_elite_production_approaches_top_salary():
    settings = _settings(top_salary=50.0, bottom_salary=1.0, waiver_salary_pct=0.6)
    # Real elite-level 2025 RB season line -- scores well above
    # WAIVER_SALARY_SCALE_MAX, so this clamps at the top of the scale.
    star = _FakePlayer("Star", "Runner", position="RB", last_season_stats={
        "rush_yd": 2000, "rush_td": 20, "rec": 60, "rec_yd": 500, "rec_td": 4,
    })
    waiver_salary = compute_waiver_salary(star, settings)
    assert waiver_salary == round(settings["top_salary"] * settings["waiver_salary_pct"], 2)


def test_compute_waiver_salary_zero_production_falls_back_to_bottom_salary():
    settings = _settings(top_salary=50.0, bottom_salary=1.0, waiver_salary_pct=0.6)
    player = _FakePlayer("Totally", "Unranked-Nobody-XYZ", last_season_stats={})

    waiver_salary = compute_waiver_salary(player, settings)
    expected = round(settings["bottom_salary"] * settings["waiver_salary_pct"], 2)
    assert waiver_salary == expected


def test_compute_waiver_salary_scales_between_bottom_and_top_with_production():
    settings = _settings(top_salary=50.0, bottom_salary=1.0, waiver_salary_pct=0.6)
    zero = _FakePlayer("No", "Stats", last_season_stats={})
    modest = _FakePlayer("Modest", "Producer", position="RB", last_season_stats={
        "rush_yd": int(WAIVER_SALARY_SCALE_MAX / 2 / 0.1),  # ~half the scale's max score
    })
    assert compute_waiver_salary(zero, settings) < compute_waiver_salary(modest, settings)
    assert compute_waiver_salary(modest, settings) < round(settings["top_salary"] * settings["waiver_salary_pct"], 2)


def test_get_salary_cap_settings_merges_with_defaults():
    league = League(id="x", name="Test", commissioner_id="c")
    league.salary_cap_settings = {"enabled": True, "cap_total": 300.0}
    merged = get_salary_cap_settings(league)
    assert merged["enabled"] is True
    assert merged["cap_total"] == 300.0
    # Untouched fields fall back to defaults.
    assert merged["max_roster_size"] == DEFAULT_SALARY_CAP_SETTINGS["max_roster_size"]
    assert merged["top_salary"] == DEFAULT_SALARY_CAP_SETTINGS["top_salary"]


def test_get_salary_cap_settings_defaults_when_unset():
    league = League(id="x", name="Test", commissioner_id="c")
    league.salary_cap_settings = None
    merged = get_salary_cap_settings(league)
    assert merged == DEFAULT_SALARY_CAP_SETTINGS
    assert merged["enabled"] is False
