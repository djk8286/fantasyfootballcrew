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
)
from app.services.draft_manager import _SEQUENTIAL_RANKINGS


def _settings(**overrides):
    merged = dict(DEFAULT_SALARY_CAP_SETTINGS)
    merged.update(overrides)
    return merged


class _FakePlayer:
    def __init__(self, first_name, last_name):
        self.first_name = first_name
        self.last_name = last_name


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


def test_compute_waiver_salary_ranked_player_is_less_than_equivalent_pick_slot_salary():
    settings = _settings(top_salary=50.0, bottom_salary=1.0, waiver_salary_pct=0.6)
    # Real ranked star name, guaranteed to exist in the ranking list.
    ranked_name = _SEQUENTIAL_RANKINGS[0][1]
    first, last = ranked_name.split(" ", 1)
    player = _FakePlayer(first, last)

    waiver_salary = compute_waiver_salary(player, settings)
    equivalent_pick_salary = compute_pick_slot_salary(1, len(_SEQUENTIAL_RANKINGS), settings)

    assert waiver_salary < equivalent_pick_salary
    assert waiver_salary == round(equivalent_pick_salary * 0.6, 2)


def test_compute_waiver_salary_unranked_player_falls_back_to_tier_scale():
    settings = _settings(top_salary=50.0, bottom_salary=1.0, waiver_salary_pct=0.6)
    player = _FakePlayer("Totally", "Unranked-Nobody-XYZ")

    waiver_salary = compute_waiver_salary(player, settings)
    # Unranked -> tier 5 of 5 -> bottom of the 5-slot interpolation, scaled.
    expected = round(compute_pick_slot_salary(5, 5, settings) * 0.6, 2)
    assert waiver_salary == expected
    assert waiver_salary < compute_pick_slot_salary(1, len(_SEQUENTIAL_RANKINGS), settings)


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
