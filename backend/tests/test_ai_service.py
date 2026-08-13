"""
Tests for AIService's prompt rendering (Phase 2 Step 3, "Front-Office
finish-out" -- threading coaching staff context into the lineup/trade
prompts). First coverage this service has had at all. Instantiated with
no api_key so _call_llm returns its static no-key fallback string with
zero network call -- these tests replace _call_llm with a spy to inspect
the actually-rendered prompt instead, which is the real thing under test.
"""
import pytest
from app.services.ai_service import AIService


@pytest.mark.asyncio
async def test_lineup_prompt_includes_coaching_staff():
    service = AIService()
    captured = {}

    async def spy(prompt: str) -> str:
        captured["prompt"] = prompt
        return "ok"

    service._call_llm = spy
    await service.analyze_lineup(
        roster={}, opponent_roster={}, matchups={}, scoring={},
        coaching_staff=[{"position": "HC", "name": "Belichick", "bonus_type": "win_bonus", "bonus_value": 5}],
    )
    assert "Belichick" in captured["prompt"]
    assert "win_bonus" in captured["prompt"]


@pytest.mark.asyncio
async def test_lineup_prompt_renders_without_coaching_staff():
    """No coaching_staff passed at all -- must not KeyError on the new
    prompt field, same as every other optional prompt field here."""
    service = AIService()
    captured = {}

    async def spy(prompt: str) -> str:
        captured["prompt"] = prompt
        return "ok"

    service._call_llm = spy
    await service.analyze_lineup(roster={}, opponent_roster={}, matchups={}, scoring={})
    assert "Coaching Staff" in captured["prompt"]
    assert captured["prompt"].count("[]") >= 1


@pytest.mark.asyncio
async def test_trade_prompt_includes_both_teams_coaching_staff():
    service = AIService()
    captured = {}

    async def spy(prompt: str) -> str:
        captured["prompt"] = prompt
        return "ok"

    service._call_llm = spy
    await service.analyze_trade(
        team_a_players=[], team_b_players=[], scoring={},
        team_a_coaching=[{"position": "HC", "name": "Belichick"}],
        team_b_coaching=[{"position": "OC", "name": "Reid"}],
    )
    assert "Belichick" in captured["prompt"]
    assert "Reid" in captured["prompt"]


@pytest.mark.asyncio
async def test_no_api_key_never_calls_call_llm_network_path():
    """Confirms the no-key fallback is safe to rely on in tests that
    don't monkeypatch _call_llm at all -- no real HTTP request fires."""
    service = AIService(api_key=None)
    result = await service.analyze_lineup(roster={}, opponent_roster={}, matchups={}, scoring={})
    assert "not configured" in result


# ─── Salary-Cap awareness (Phase 5, "Salary-Cap + Contract Leagues") ────

@pytest.mark.asyncio
async def test_lineup_prompt_includes_salary_context():
    service = AIService()
    captured = {}

    async def spy(prompt: str) -> str:
        captured["prompt"] = prompt
        return "ok"

    service._call_llm = spy
    await service.analyze_lineup(
        roster={}, opponent_roster={}, matchups={}, scoring={},
        salary_context={"cap_total": 200.0, "cap_space": 45.5},
    )
    assert "45.5" in captured["prompt"]
    assert "Salary Cap" in captured["prompt"]


@pytest.mark.asyncio
async def test_lineup_prompt_renders_without_salary_context():
    """No salary_context passed at all -- must not KeyError on the new
    prompt field, same as every other optional prompt field here."""
    service = AIService()
    captured = {}

    async def spy(prompt: str) -> str:
        captured["prompt"] = prompt
        return "ok"

    service._call_llm = spy
    await service.analyze_lineup(roster={}, opponent_roster={}, matchups={}, scoring={})
    assert "Salary Cap" in captured["prompt"]


@pytest.mark.asyncio
async def test_trade_prompt_includes_both_teams_salary_context():
    service = AIService()
    captured = {}

    async def spy(prompt: str) -> str:
        captured["prompt"] = prompt
        return "ok"

    service._call_llm = spy
    await service.analyze_trade(
        team_a_players=[], team_b_players=[], scoring={},
        team_a_salary={"cap_space": 12.0},
        team_b_salary={"cap_space": -3.5},
    )
    assert "12.0" in captured["prompt"]
    assert "-3.5" in captured["prompt"]


@pytest.mark.asyncio
async def test_trade_prompt_renders_without_salary_context():
    service = AIService()
    captured = {}

    async def spy(prompt: str) -> str:
        captured["prompt"] = prompt
        return "ok"

    service._call_llm = spy
    await service.analyze_trade(team_a_players=[], team_b_players=[], scoring={})
    assert "Salary Cap" in captured["prompt"]
