"""GET /players/{id}/detail -- public player page payload; rostered_by only for logged-in viewers."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.league import League
from app.models.player import Player
from app.models.player_news import PlayerNews
from app.models.team import Team
from app.models.user import User
from app.services.auth_service import create_access_token


async def _setup(f):
    async with f() as db:
        me = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@t.local", username=f"u{uuid.uuid4().hex[:8]}", hashed_password="x")
        other = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@t.local", username=f"u{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add_all([me, other])
        await db.flush()
        p = Player(id=str(uuid.uuid4()), sleeper_id="4046", first_name="Pat", last_name="Mahomes", position="QB",
                   team="KC", number=15, age=31, stats_year=2026,
                   stats={"pass_yd": 1000, "pass_td": 8},
                   week_stats={"1": {"pass_yd": 300, "pass_td": 2}, "2": {"pass_yd": 250, "pass_td": 3}})
        db.add(p)
        mine = League(id=str(uuid.uuid4()), name="My League", commissioner_id=other.id, scoring_config={}, roster_slots={})
        theirs = League(id=str(uuid.uuid4()), name="Stranger League", commissioner_id=other.id, scoring_config={}, roster_slots={})
        db.add_all([mine, theirs])
        await db.flush()
        db.add_all([
            Team(id=str(uuid.uuid4()), name="My Team", league_id=mine.id, owner_id=me.id, roster=[]),
            Team(id=str(uuid.uuid4()), name="Rival", league_id=mine.id, owner_id=other.id, roster=[p.id]),
            Team(id=str(uuid.uuid4()), name="Elsewhere", league_id=theirs.id, owner_id=other.id, roster=[p.id]),
            PlayerNews(player_id=p.id, source="ESPN", external_id="1", headline="Mahomes news",
                       url="https://www.espn.com/nfl/story/_/id/1/x",
                       published_at=datetime.now(timezone.utc) - timedelta(days=1)),
        ])
        await db.commit()
        return p.id, create_access_token({"sub": me.id, "email": me.email, "token_version": 0})


@pytest.mark.asyncio
async def test_detail_public_payload_logged_out(client, db_session_factory):
    pid, _ = await _setup(db_session_factory)
    client.headers.pop("Authorization", None)
    r = await client.get(f"/players/{pid}/detail")
    assert r.status_code == 200
    d = r.json()
    assert d["first_name"] == "Pat" and d["number"] == 15
    assert d["avatar_url"] and "4046" in d["avatar_url"]
    assert [w["week"] for w in d["weekly_points"]] == [1, 2]
    assert all(w["points"] > 0 for w in d["weekly_points"])
    assert d["season_points"] is not None
    assert d["news"][0]["url"] == "https://www.espn.com/nfl/story/_/id/1/x"
    assert d["rostered_by"] is None


@pytest.mark.asyncio
async def test_detail_rostered_by_only_viewers_leagues(client, db_session_factory):
    pid, token = await _setup(db_session_factory)
    client.headers["Authorization"] = f"Bearer {token}"
    d = (await client.get(f"/players/{pid}/detail")).json()
    assert [(t["team_name"], t["league_name"], t["is_mine"]) for t in d["rostered_by"]] == [("Rival", "My League", False)]


@pytest.mark.asyncio
async def test_detail_404(client):
    assert (await client.get("/players/nope/detail")).status_code == 404
