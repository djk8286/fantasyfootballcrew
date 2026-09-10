"""
Tests for GET /nfl/current-week (2026-09-10) -- the single real source of
"what week is it" every page now uses (league page's live-score panel,
Schedule/Standings default week), replacing each page's own fragile
frontend heuristic.
"""
import pytest
import app.api.v1.nfl as nfl_module


@pytest.mark.asyncio
async def test_current_week_returns_live_state(client, monkeypatch):
    nfl_module._state_cache = None
    nfl_module._state_cache_at = 0.0

    async def _fake_fetch_nfl_state():
        return {"season": "2026", "week": "1", "season_type": "regular"}
    monkeypatch.setattr(nfl_module, "fetch_nfl_state", _fake_fetch_nfl_state)

    r = await client.get("/nfl/current-week")
    assert r.status_code == 200
    assert r.json() == {"season": 2026, "week": 1, "season_type": "regular"}


@pytest.mark.asyncio
async def test_current_week_is_cached_briefly(client, monkeypatch):
    nfl_module._state_cache = None
    nfl_module._state_cache_at = 0.0

    calls = {"count": 0}

    async def _fake_fetch_nfl_state():
        calls["count"] += 1
        return {"season": "2026", "week": "1", "season_type": "regular"}
    monkeypatch.setattr(nfl_module, "fetch_nfl_state", _fake_fetch_nfl_state)

    await client.get("/nfl/current-week")
    await client.get("/nfl/current-week")
    await client.get("/nfl/current-week")
    assert calls["count"] == 1  # second/third calls served from cache
