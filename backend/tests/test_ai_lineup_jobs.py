"""QA 2026-10-19 NEW-1: Analyze Lineup ran as one 20-40 s request, so the
result was lost if the page navigated away (it still landed in history).
It now runs as a background job the page polls."""
import asyncio
import uuid

import pytest
from sqlalchemy import select

from app.api.v1 import ai as ai_api
from app.models.ai_analysis_history import AIAnalysisHistory
from app.models.ai_usage_event import AIUsageEvent
from app.models.league import League, LeagueVisibility
from app.models.team import Team
from app.services import ai_cost_service, ai_jobs
from tests.test_ai_usage_recording import _make_user


class _SlowFakeAI:
    def __init__(self, fail=False):
        self.fail = fail

    async def analyze_lineup(self, **inputs):
        await asyncio.sleep(0.05)
        ev = ai_cost_service.current_usage_event()  # metered like AIService does
        if ev is not None:
            ev.model, ev.input_tokens, ev.output_tokens, ev.cost_usd = "fake-model", 1200, 300, 0.0123
        if self.fail:
            raise RuntimeError("provider exploded with secret details")
        assert "roster" in inputs and "scoring" in inputs
        return "Start your studs."


async def _league_and_team(factory, owner_id):
    async with factory() as db:
        league = League(id=str(uuid.uuid4()), name="Jobs League", commissioner_id=owner_id,
                        visibility=LeagueVisibility.OPEN, scoring_config={}, roster_slots={})
        db.add(league)
        team = Team(id=str(uuid.uuid4()), name="Job Team", league_id=league.id, owner_id=owner_id, roster=[])
        db.add(team)
        await db.commit()
        return league.id, team.id


async def _poll(client, job_id, headers):
    for _ in range(100):
        r = await client.get(f"/ai/jobs/{job_id}", headers=headers)
        assert r.status_code == 200, r.text
        if r.json()["status"] != "pending":
            return r.json()
        await asyncio.sleep(0.02)
    raise AssertionError("job never finished")


@pytest.mark.asyncio
async def test_lineup_job_returns_immediately_then_resolves(client, db_session_factory, monkeypatch):
    monkeypatch.setattr(ai_api, "_get_ai_service", lambda: _SlowFakeAI())
    owner, token = await _make_user(db_session_factory)
    league_id, team_id = await _league_and_team(db_session_factory, owner.id)
    h = {"Authorization": f"Bearer {token}"}

    r = await client.post("/ai/lineup/jobs", json={"team_id": team_id}, headers=h)
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "pending"
    job_id = r.json()["job_id"]

    # Someone else can't read it (same 404 as an unknown id).
    _other, other_token = await _make_user(db_session_factory)
    assert (await client.get(f"/ai/jobs/{job_id}", headers={"Authorization": f"Bearer {other_token}"})).status_code == 404
    assert (await client.get(f"/ai/jobs/{uuid.uuid4()}", headers=h)).status_code == 404

    pending = (await client.get(f"/ai/jobs/{job_id}", headers=h)).json()
    assert pending["status"] == "pending"
    # Let the job finish before polling again: the test DB is one shared
    # SQLite connection (StaticPool), so overlapping sessions can roll back
    # each other's writes -- an artifact of the fixture, not of Postgres.
    await asyncio.wait_for(ai_jobs._jobs[job_id].task, timeout=5)
    done = await _poll(client, job_id, h)
    assert done == {"job_id": job_id, "kind": "lineup", "status": "done", "analysis": "Start your studs.", "error": None}

    async with db_session_factory() as db:
        hist = (await db.execute(select(AIAnalysisHistory).where(AIAnalysisHistory.user_id == owner.id))).scalars().all()
        usage = (await db.execute(select(AIUsageEvent).where(AIUsageEvent.user_id == owner.id,
                                                             AIUsageEvent.endpoint == "lineup"))).scalars().all()
    assert [h.result for h in hist] == ["Start your studs."]
    assert hist[0].league_id == league_id
    assert len(usage) == 1  # tokens/cost metered in the background still reach the row
    assert (usage[0].model, usage[0].input_tokens, usage[0].output_tokens) == ("fake-model", 1200, 300)
    assert float(usage[0].cost_usd) == pytest.approx(0.0123)


@pytest.mark.asyncio
async def test_lineup_job_failure_is_generic_and_owner_only(client, db_session_factory, monkeypatch):
    monkeypatch.setattr(ai_api, "_get_ai_service", lambda: _SlowFakeAI(fail=True))
    owner, token = await _make_user(db_session_factory)
    _league_id, team_id = await _league_and_team(db_session_factory, owner.id)
    h = {"Authorization": f"Bearer {token}"}
    r = await client.post("/ai/lineup/jobs", json={"team_id": team_id}, headers=h)
    done = await _poll(client, r.json()["job_id"], h)
    assert done["status"] == "error"
    assert "secret" not in done["error"]


@pytest.mark.asyncio
async def test_lineup_job_requires_owning_the_team(client, db_session_factory, monkeypatch):
    monkeypatch.setattr(ai_api, "_get_ai_service", lambda: _SlowFakeAI())
    owner, _ = await _make_user(db_session_factory)
    _league_id, team_id = await _league_and_team(db_session_factory, owner.id)
    _intruder, token = await _make_user(db_session_factory)
    r = await client.post("/ai/lineup/jobs", json={"team_id": team_id}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code in (403, 404)
    assert (await client.post("/ai/lineup/jobs", json={"team_id": team_id})).status_code == 401


@pytest.mark.asyncio
async def test_job_timeout_marks_error(monkeypatch):
    monkeypatch.setattr(ai_jobs, "JOB_TIMEOUT_S", 0.05)

    async def _hang():
        await asyncio.sleep(5)
        return "never"

    job = ai_jobs.start("u1", "lineup", _hang)
    await job.task
    assert job.status == "error" and "too long" in job.error
    assert ai_jobs.get(job.id, "someone-else") is None
