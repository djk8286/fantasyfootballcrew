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


# ─── Dual-Squad/Mirror awareness (Phase 7, "Dual-Squad/Mirror") ────────

@pytest.mark.asyncio
async def test_lineup_prompt_includes_partner_context():
    service = AIService()
    captured = {}

    async def spy(prompt: str) -> str:
        captured["prompt"] = prompt
        return "ok"

    service._call_llm = spy
    await service.analyze_lineup(
        roster={}, opponent_roster={}, matchups={}, scoring={},
        partner_context={"wins": 7, "losses": 2, "team_ids": ["a", "b"]},
    )
    assert "Linked Pair" in captured["prompt"]
    assert '"wins": 7' in captured["prompt"]


@pytest.mark.asyncio
async def test_lineup_prompt_renders_without_partner_context():
    """No partner_context passed at all -- must not KeyError on the new
    prompt field, same as every other optional prompt field here."""
    service = AIService()
    captured = {}

    async def spy(prompt: str) -> str:
        captured["prompt"] = prompt
        return "ok"

    service._call_llm = spy
    await service.analyze_lineup(roster={}, opponent_roster={}, matchups={}, scoring={})
    assert "Linked Pair" in captured["prompt"]


@pytest.mark.asyncio
async def test_trade_prompt_includes_both_teams_partner_context():
    service = AIService()
    captured = {}

    async def spy(prompt: str) -> str:
        captured["prompt"] = prompt
        return "ok"

    service._call_llm = spy
    await service.analyze_trade(
        team_a_players=[], team_b_players=[], scoring={},
        team_a_partner={"wins": 5, "team_ids": ["a", "b"]},
        team_b_partner={"wins": 1, "team_ids": ["c", "d"]},
    )
    assert '"wins": 5' in captured["prompt"]
    assert '"wins": 1' in captured["prompt"]


@pytest.mark.asyncio
async def test_trade_prompt_renders_without_partner_context():
    service = AIService()
    captured = {}

    async def spy(prompt: str) -> str:
        captured["prompt"] = prompt
        return "ok"

    service._call_llm = spy
    await service.analyze_trade(team_a_players=[], team_b_players=[], scoring={})
    assert "Linked Pair" in captured["prompt"]


# ─── Commissioner Digest (Phase 8, "AI-Assisted Commissioner Tools") ───

@pytest.mark.asyncio
async def test_digest_prompt_includes_standings_and_transactions():
    service = AIService()
    captured = {}

    async def spy(prompt: str) -> str:
        captured["prompt"] = prompt
        return "ok"

    service._call_llm = spy
    await service.generate_commissioner_digest(
        league_name="Test League", week=3, year=2026,
        standings=[{"team_name": "The Contenders", "wins": 2}],
        recent_transactions=[{"type": "trade", "status": "approved"}],
    )
    assert "Test League" in captured["prompt"]
    assert "The Contenders" in captured["prompt"]
    assert '"type": "trade"' in captured["prompt"]
    assert "POWER RANKINGS" in captured["prompt"]


@pytest.mark.asyncio
async def test_digest_prompt_renders_without_optional_context():
    """No combined_standings/recent_transactions/features passed at all
    -- must not KeyError on any optional prompt field."""
    service = AIService()
    captured = {}

    async def spy(prompt: str) -> str:
        captured["prompt"] = prompt
        return "ok"

    service._call_llm = spy
    await service.generate_commissioner_digest(league_name="Empty League", week=1, year=2026)
    assert "Empty League" in captured["prompt"]
    assert "Combined Pairs Standings" in captured["prompt"]


@pytest.mark.asyncio
async def test_digest_no_api_key_never_calls_network_path():
    service = AIService(api_key=None)
    result = await service.generate_commissioner_digest(league_name="X", week=1, year=2026)
    assert "not configured" in result


@pytest.mark.asyncio
async def test_digest_prompt_includes_tone_and_length_instructions():
    service = AIService()
    captured = {}

    async def spy(prompt: str) -> str:
        captured["prompt"] = prompt
        return "ok"

    service._call_llm = spy
    await service.generate_commissioner_digest(league_name="X", week=1, year=2026, tone="hype", length="short")
    assert "hype-man" in captured["prompt"]
    assert "2-3 short paragraphs" in captured["prompt"]


@pytest.mark.asyncio
async def test_digest_prompt_unrecognized_tone_and_length_fall_back_safely():
    service = AIService()
    captured = {}

    async def spy(prompt: str) -> str:
        captured["prompt"] = prompt
        return "ok"

    service._call_llm = spy
    # Must never KeyError, even with a nonsense value.
    await service.generate_commissioner_digest(league_name="X", week=1, year=2026, tone="nonsense", length="nonsense")
    assert "professional, measured tone" in captured["prompt"]
    assert "full, detailed digest" in captured["prompt"]


# ─── Trade Review Assistant (AI Co-Commissioner v1) ────────────────────

@pytest.mark.asyncio
async def test_trade_review_prompt_includes_teams_and_players():
    service = AIService()
    captured = {}

    async def spy(prompt: str) -> str:
        captured["prompt"] = prompt
        return "ok"

    service._call_llm = spy
    await service.generate_trade_review(
        league_name="Test League", proposer_name="Team Alpha", target_name="Team Beta",
        offered_players=["Player A (RB)"], requested_players=["Player B (WR)"],
        standings=[{"team_name": "Team Alpha", "wins": 3}],
    )
    assert "Team Alpha" in captured["prompt"]
    assert "Team Beta" in captured["prompt"]
    assert "Player A (RB)" in captured["prompt"]
    assert "RECOMMENDATION: APPROVE" in captured["prompt"]


@pytest.mark.asyncio
async def test_trade_review_prompt_renders_without_optional_context():
    service = AIService()
    captured = {}

    async def spy(prompt: str) -> str:
        captured["prompt"] = prompt
        return "ok"

    service._call_llm = spy
    await service.generate_trade_review(league_name="X", proposer_name="A", target_name="B")
    assert "FAIRNESS" in captured["prompt"]


@pytest.mark.asyncio
async def test_trade_review_no_api_key_never_calls_network_path():
    service = AIService(api_key=None)
    result = await service.generate_trade_review(league_name="X", proposer_name="A", target_name="B")
    assert "not configured" in result


# ─── Communication Helpers (AI Co-Commissioner v1, Phase 2) ────────────

@pytest.mark.asyncio
async def test_commissioner_message_prompt_uses_correct_message_type_framing():
    service = AIService()
    captured = {}

    async def spy(prompt: str) -> str:
        captured["prompt"] = prompt
        return "ok"

    service._call_llm = spy
    await service.generate_commissioner_message(
        league_name="Test League", message_type="inactivity_warning",
        context={"at_risk_teams": ["Ghost Team"]},
    )
    assert "Test League" in captured["prompt"]
    assert "inactive" in captured["prompt"].lower()
    assert "Ghost Team" in captured["prompt"]


@pytest.mark.asyncio
async def test_commissioner_message_prompt_unrecognized_type_falls_back_to_general():
    service = AIService()
    captured = {}

    async def spy(prompt: str) -> str:
        captured["prompt"] = prompt
        return "ok"

    service._call_llm = spy
    # Must never KeyError, even with a nonsense message_type.
    await service.generate_commissioner_message(league_name="X", message_type="nonsense")
    assert "general announcement" in captured["prompt"].lower()


@pytest.mark.asyncio
async def test_commissioner_message_no_api_key_never_calls_network_path():
    service = AIService(api_key=None)
    result = await service.generate_commissioner_message(league_name="X", message_type="general")
    assert "not configured" in result


# ─── AI Co-Commissioner Chat (deferred item 7) ──────────────────────────

@pytest.mark.asyncio
async def test_chat_system_prompt_includes_league_name_and_context():
    service = AIService(api_key="fake-key", provider="openai")
    captured = {}

    async def spy(system, history):
        captured["system"] = system
        captured["history"] = history
        return "ok"

    service._call_openai_chat = spy
    await service.chat(
        league_name="Test League",
        context={"standings": [{"team_name": "The Contenders"}]},
        history=[{"role": "user", "content": "How healthy is the league?"}],
    )
    assert "Test League" in captured["system"]
    assert "The Contenders" in captured["system"]
    assert captured["history"] == [{"role": "user", "content": "How healthy is the league?"}]


@pytest.mark.asyncio
async def test_chat_no_api_key_never_calls_network_path():
    service = AIService(api_key=None)
    result = await service.chat(league_name="X", context={}, history=[{"role": "user", "content": "hi"}])
    assert "not configured" in result


@pytest.mark.asyncio
async def test_call_anthropic_chat_puts_system_at_top_level_not_in_messages(monkeypatch):
    """Regression pin for the one real shape difference between the
    two providers' chat APIs -- Anthropic's `system` is a top-level
    request field, not a {"role": "system"} entry inside `messages`."""
    service = AIService(api_key="fake-key", provider="anthropic")
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"content": [{"text": "ok"}]}

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers, json):
            captured["json"] = json
            return FakeResponse()

    import app.services.ai_service as ai_service_module
    monkeypatch.setattr(ai_service_module.httpx, "AsyncClient", FakeAsyncClient)

    result = await service._call_anthropic_chat("SYSTEM PROMPT HERE", [{"role": "user", "content": "hi"}])

    assert result == "ok"
    assert captured["json"]["system"] == "SYSTEM PROMPT HERE"
    assert captured["json"]["messages"] == [{"role": "user", "content": "hi"}]
    assert all(m.get("role") != "system" for m in captured["json"]["messages"])
