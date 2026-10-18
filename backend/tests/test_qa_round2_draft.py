"""QA round 2: server-side draft advancement (no browser tab), pause/resume,
and a full CPU draft completing quickly."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.draft import Draft, DraftPick, DraftRunStatus
from app.models.player import Player
from app.models.user import User
from app.services.auth_service import create_access_token
from app.services.draft_manager import quickstart_mock_draft


async def _seed(factory, n_players=40):
    async with factory() as db:
        user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@t.local",
                    username=f"u{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(user)
        for i in range(n_players):
            pos = ["QB", "RB", "WR", "TE"][i % 4]
            db.add(Player(id=str(uuid.uuid4()), sleeper_id=str(uuid.uuid4()), first_name=f"P{i}",
                          last_name=pos, position=pos, search_rank=i + 1))
        await db.commit()
        return user


async def _backdate(factory, draft_id, seconds=5):
    async with factory() as db:
        d = (await db.execute(select(Draft).where(Draft.id == draft_id))).scalar_one()
        d.current_pick_started_at = datetime.now(timezone.utc) - timedelta(seconds=seconds)
        await db.commit()


@pytest.mark.asyncio
async def test_watchdog_completes_cpu_draft_without_client(db_session_factory, monkeypatch):
    import app.services.scheduler as sched
    from app.core.config import settings
    monkeypatch.setattr(sched, "async_session", db_session_factory)
    monkeypatch.setattr(settings, "CPU_PICK_DELAY_S", 0.0)
    user = await _seed(db_session_factory)
    async with db_session_factory() as db:
        # User drafts last, so the 3 CPU picks of round 1 go first.
        draft, my_team = await quickstart_mock_draft(db, user.id, num_teams=4, total_rounds=2, draft_position=4)
    for _ in range(3):
        await sched._process_expired_draft_picks_once()
    async with db_session_factory() as db:
        picks = (await db.execute(select(DraftPick).where(DraftPick.draft_id == draft.id))).scalars().all()
        assert len(picks) == 3
        assert all(p.team_id != my_team for p in picks)
    # The human's pick waits for their timer, then the watchdog forces it and finishes.
    await sched._process_expired_draft_picks_once()
    async with db_session_factory() as db:
        assert len((await db.execute(select(DraftPick).where(DraftPick.draft_id == draft.id))).scalars().all()) == 3
    await _backdate(db_session_factory, draft.id, seconds=10_000)
    for _ in range(10):
        await sched._process_expired_draft_picks_once()
        await _backdate(db_session_factory, draft.id, seconds=10_000)
    async with db_session_factory() as db:
        d = (await db.execute(select(Draft).where(Draft.id == draft.id))).scalar_one()
        assert d.status == DraftRunStatus.COMPLETED


@pytest.mark.asyncio
async def test_watchdog_respects_cpu_delay(db_session_factory, monkeypatch):
    import app.services.scheduler as sched
    from app.core.config import settings
    monkeypatch.setattr(sched, "async_session", db_session_factory)
    monkeypatch.setattr(settings, "CPU_PICK_DELAY_S", 30.0)
    user = await _seed(db_session_factory)
    async with db_session_factory() as db:
        draft, _ = await quickstart_mock_draft(db, user.id, num_teams=4, total_rounds=2, draft_position=4)
    await sched._process_expired_draft_picks_once()
    async with db_session_factory() as db:
        assert (await db.execute(select(DraftPick).where(DraftPick.draft_id == draft.id))).scalars().all() == []


@pytest.mark.asyncio
async def test_pause_blocks_picks_and_resume_restores(client, db_session_factory, monkeypatch):
    import app.services.scheduler as sched
    from app.core.config import settings
    monkeypatch.setattr(sched, "async_session", db_session_factory)
    monkeypatch.setattr(settings, "CPU_PICK_DELAY_S", 0.0)
    user = await _seed(db_session_factory)
    token = create_access_token({"sub": user.id, "email": user.email})
    h = {"Authorization": f"Bearer {token}"}
    async with db_session_factory() as db:
        draft, _ = await quickstart_mock_draft(db, user.id, num_teams=4, total_rounds=2, draft_position=4)
    r = await client.post(f"/drafts/{draft.id}/pause", headers=h)
    assert r.status_code == 200, r.text
    await sched._process_expired_draft_picks_once()
    r = await client.post(f"/drafts/{draft.id}/auto-pick", headers=h)
    assert r.status_code >= 400
    async with db_session_factory() as db:
        assert (await db.execute(select(DraftPick).where(DraftPick.draft_id == draft.id))).scalars().all() == []
    state = (await client.get(f"/drafts/{draft.id}/state", headers=h)).json()
    assert state["draft"]["is_paused"] is True
    r = await client.post(f"/drafts/{draft.id}/resume", headers=h)
    assert r.status_code == 200
    await _backdate(db_session_factory, draft.id, seconds=2)
    await sched._process_expired_draft_picks_once()
    async with db_session_factory() as db:
        assert len((await db.execute(select(DraftPick).where(DraftPick.draft_id == draft.id))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_pause_is_commissioner_only(client, db_session_factory):
    user = await _seed(db_session_factory)
    async with db_session_factory() as db:
        other = User(id=str(uuid.uuid4()), email="o@t.local", username="other1", hashed_password="x")
        db.add(other)
        await db.commit()
        draft, _ = await quickstart_mock_draft(db, user.id, num_teams=4, total_rounds=2)
    t = create_access_token({"sub": other.id, "email": other.email})
    r = await client.post(f"/drafts/{draft.id}/pause", headers={"Authorization": f"Bearer {t}"})
    assert r.status_code == 403
