"""
Real player news from ESPN (espn_news_service.py) -- all ESPN traffic is
mocked with pytest-httpx; the payloads mirror the live feed's real shape
(captured 2026-10-18).
"""
import re
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from app.models.league import League, LeagueVisibility
from app.models.player import Player
from app.models.player_news import PlayerNews
from app.models.team import Team
from app.models.user import User
from app.services import espn_news_service as svc
from app.services.team_news_service import generate_and_save_team_news

FEED_RE = re.compile(r"https://site\.api\.espn\.com/apis/site/v2/sports/football/nfl/news.*")


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _article(aid, headline, athlete_ids, published=None, url=None):
    published = published or datetime.now(timezone.utc) - timedelta(hours=2)
    cats = [{"type": "league", "leagueId": 28, "description": "NFL"}]
    cats += [{"type": "athlete", "athleteId": int(x), "athlete": {"id": int(x), "description": f"A{x}"}} for x in athlete_ids]
    return {
        "id": aid, "headline": headline, "description": f"desc {aid}", "published": _iso(published),
        "type": "Story", "categories": cats,
        "links": {"web": {"href": url or f"https://www.espn.com/nfl/story/_/id/{aid}/x"}},
    }


async def _player(db, espn_id, first="Pat", last="Player"):
    p = Player(id=str(uuid.uuid4()), sleeper_id=f"s{uuid.uuid4().hex[:8]}", first_name=first,
               last_name=last, position="QB", team="KC", espn_id=espn_id)
    db.add(p)
    await db.commit()
    return p


def test_parse_articles_keeps_only_athlete_tagged_with_url_and_time():
    payload = {"articles": [
        _article(1, "Tagged", ["111"]),
        _article(2, "No athlete", []),
        {**_article(3, "No url", ["111"]), "links": {}},
        {**_article(4, "Bad time", ["111"]), "published": None},
        _article(5, "http url", ["222"], url="http://www.espn.com/nfl/story/_/id/5/x"),
    ]}
    out = svc.parse_articles(payload)
    assert [a["external_id"] for a in out] == ["1", "5"]
    assert out[0]["athlete_ids"] == ["111"]
    assert out[0]["url"].startswith("https://www.espn.com/")
    assert out[1]["url"].startswith("https://"), "http links upgraded to https"


@pytest.mark.asyncio
async def test_refresh_saves_real_links_dedupes_across_feeds_and_reruns(db_session_factory, httpx_mock):
    league_wide = {"articles": [_article(10, "QB news", ["111"]), _article(11, "Pat Player and Sam Player swap teams", ["111", "222"])]}
    team_feed = {"articles": [_article(11, "Pat Player and Sam Player swap teams", ["111", "222"]), _article(12, "Unknown athlete", ["999"])]}
    httpx_mock.add_response(url=re.compile(FEED_RE.pattern + r"team=7.*"), json=team_feed, is_reusable=True)
    httpx_mock.add_response(url=re.compile(r".*/nfl/news\?limit=50$"), json=league_wide, is_reusable=True)

    async with db_session_factory() as db:
        p1 = await _player(db, "111")
        p2 = await _player(db, "222", first="Sam")
        stats = await svc.refresh_player_news(db, team_ids=[7])
        assert stats == {"articles": 3, "added": 3, "failed_feeds": 0}
        # Re-running the same pass adds nothing (dedupe on article+player).
        again = await svc.refresh_player_news(db, team_ids=[7])
        assert again["added"] == 0

        rows = (await db.execute(select(PlayerNews))).scalars().all()
        assert sorted((r.external_id, r.player_id) for r in rows) == sorted([("10", p1.id), ("11", p1.id), ("11", p2.id)])
        assert all(r.url.startswith("https://www.espn.com/nfl/story/") and r.source == "ESPN" for r in rows)


@pytest.mark.asyncio
async def test_refresh_survives_one_failing_feed_but_raises_when_all_fail(db_session_factory, httpx_mock):
    httpx_mock.add_exception(httpx.ReadTimeout("slow"), url=re.compile(FEED_RE.pattern + r"team=7.*"))
    httpx_mock.add_response(url=re.compile(r".*/nfl/news\?limit=50$"), json={"articles": [_article(20, "ok", ["111"])]})
    async with db_session_factory() as db:
        await _player(db, "111")
        stats = await svc.refresh_player_news(db, team_ids=[7])
        assert stats["failed_feeds"] == 1 and stats["added"] == 1

    httpx_mock.add_response(url=re.compile(FEED_RE.pattern), status_code=503, is_reusable=True)
    async with db_session_factory() as db:
        with pytest.raises(RuntimeError):
            await svc.refresh_player_news(db, team_ids=[])


@pytest.mark.asyncio
async def test_refresh_prunes_old_articles(db_session_factory, httpx_mock):
    old = datetime.now(timezone.utc) - timedelta(days=svc.RETENTION_DAYS + 2)
    httpx_mock.add_response(url=re.compile(FEED_RE.pattern), json={"articles": [_article(30, "old", ["111"], published=old)]})
    async with db_session_factory() as db:
        await _player(db, "111")
        await svc.refresh_player_news(db, team_ids=[])
        assert (await db.execute(select(PlayerNews))).scalars().all() == []


async def _team_with_news(db_session_factory, with_article=True):
    async with db_session_factory() as db:
        u = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@t.local", username=f"u{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(u)
        await db.flush()
        league = League(id=str(uuid.uuid4()), name="L", commissioner_id=u.id, visibility=LeagueVisibility.OPEN,
                        scoring_config={}, roster_slots={})
        db.add(league)
        p = await _player(db, "111", first="Real", last="News")
        team = Team(id=str(uuid.uuid4()), name="T", league_id=league.id, owner_id=u.id, roster=[p.id])
        db.add(team)
        if with_article:
            db.add(PlayerNews(player_id=p.id, source="ESPN", external_id="40", headline="Real headline",
                              url="https://www.espn.com/nfl/story/_/id/40/x",
                              published_at=datetime.now(timezone.utc) - timedelta(hours=1)))
        await db.commit()
        return team


@pytest.mark.asyncio
async def test_team_news_endpoint_returns_real_articles_even_before_digest(client, db_session_factory):
    team = await _team_with_news(db_session_factory)
    r = await client.get(f"/teams/{team.id}/news")
    assert r.status_code == 200
    body = r.json()
    assert body["content"] is None
    assert body["articles"][0]["headline"] == "Real headline"
    assert body["articles"][0]["url"] == "https://www.espn.com/nfl/story/_/id/40/x"
    assert body["articles"][0]["player_name"] == "Real News"


@pytest.mark.asyncio
async def test_digest_without_ai_key_is_built_from_real_data(db_session_factory, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None, raising=False)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None, raising=False)
    team = await _team_with_news(db_session_factory)
    async with db_session_factory() as db:
        news = await generate_and_save_team_news(team, db)
    assert "Real News: added to this roster." in news.content
    assert "http" not in news.content
    assert "not configured" not in news.content


@pytest.mark.asyncio
async def test_digest_with_ai_only_sees_fetched_articles(db_session_factory, monkeypatch):
    from app.core.config import settings
    from app.services.ai_service import AIService
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "fake", raising=False)
    captured = {}

    async def spy(self, prompt):
        captured["prompt"] = prompt
        return "Summary."

    async def no_search(self, *a, **k):
        raise AssertionError("team news must never use web search")

    monkeypatch.setattr(AIService, "_call_llm", spy)
    monkeypatch.setattr(AIService, "_call_openai_search", no_search)
    team = await _team_with_news(db_session_factory)
    async with db_session_factory() as db:
        news = await generate_and_save_team_news(team, db)
    assert news.content == "Summary."
    assert "Real headline" in captured["prompt"]
    assert "Never include" in captured["prompt"]


@pytest.mark.asyncio
async def test_team_news_lists_a_multi_player_article_once(client, db_session_factory):
    team = await _team_with_news(db_session_factory)
    async with db_session_factory() as db:
        p2 = await _player(db, "222", first="Second", last="Guy")
        first = (await db.execute(select(PlayerNews).where(PlayerNews.external_id == "40"))).scalar_one()
        first.headline = "Real News and Second Guy headline"
        t = await db.get(Team, team.id)
        t.roster = [*t.roster, p2.id]
        db.add(PlayerNews(player_id=p2.id, source="ESPN", external_id="40", headline="Real News and Second Guy headline",
                          url="https://www.espn.com/nfl/story/_/id/40/x",
                          published_at=datetime.now(timezone.utc) - timedelta(hours=1)))
        await db.commit()
    body = (await client.get(f"/teams/{team.id}/news")).json()
    assert len(body["articles"]) == 1
    assert sorted(body["articles"][0]["player_names"]) == ["Real News", "Second Guy"]


# ─── Tags only when the article really mentions the player (QA 2026-10-20) ──

@pytest.mark.parametrize("first,last,headline,desc,sole,others,expected", [
    # Generic round-up tagged with a dozen athletes: not "news about" him.
    ("Kyler", "Murray", "Knockout league pickups: Trio of Lions among best pickups for Week 7",
     "Who to add this week.", False, ["Goff", "LaPorta"], False),
    ("Jared", "Goff", "Knockout league pickups: Trio of Lions among best pickups for Week 7",
     "Jared Goff headlines the adds.", False, ["Murray"], True),
    # ESPN's only athlete tag: trusted even when the headline uses a nickname.
    ("Cameron", "Heyward", "Cam Heyward details Steelers' preparation for Paris game", "", True, [], True),
    # Last name alone, possessive, punctuation and suffixes.
    ("Jalen", "Hurts", "Saturday sounds off on Sirianni having to field questions about Hurts flying", "", False, ["Saturday"], True),
    ("Davante", "Adams", "What does Davante Adams' injury mean for other Rams pass catchers?", "", False, ["Higbee"], True),
    ("Amon-Ra", "St. Brown", "Amon-Ra St. Brown leads Lions", "", False, ["Goff"], True),
    ("Kenneth", "Walker III", "Rest-of-season rankings: Kenneth Walker rises", "", False, ["Hurts"], True),
    # Shared last name among the tags: needs the full name.
    ("Josh", "Allen", "Allen leads the MVP race", "", False, ["Allen"], False),
    ("Josh", "Allen", "Josh Allen leads the MVP race", "", False, ["Allen"], True),
    # Substrings don't count.
    ("Mike", "Evans", "Evansville native signs", "", False, ["X"], False),
])
def test_article_mentions(first, last, headline, desc, sole, others, expected):
    assert svc.article_mentions(first, last, headline, desc, sole_tag=sole, other_last_names=others) is expected


@pytest.mark.asyncio
async def test_refresh_skips_roundup_tags_that_dont_name_the_player(db_session_factory, httpx_mock):
    roundup = _article(60, "Knockout league pickups: Jared Goff among best adds", ["111", "222", "333"])
    roundup["description"] = "Three Lions to add."
    httpx_mock.add_response(url=re.compile(FEED_RE.pattern), json={"articles": [roundup]}, is_reusable=True)
    async with db_session_factory() as db:
        goff = await _player(db, "111", first="Jared", last="Goff")
        await _player(db, "222", first="Kyler", last="Murray")
        await _player(db, "333", first="Sam", last="LaPorta")
        stats = await svc.refresh_player_news(db, team_ids=[])
        rows = (await db.execute(select(PlayerNews))).scalars().all()
    assert stats["added"] == 1
    assert [(r.external_id, r.player_id) for r in rows] == [("60", goff.id)]


@pytest.mark.asyncio
async def test_old_untrue_tags_are_hidden_when_read(db_session_factory):
    """Rows saved before the check existed are filtered on the way out."""
    async with db_session_factory() as db:
        murray = await _player(db, "222", first="Kyler", last="Murray")
        goff = await _player(db, "111", first="Jared", last="Goff")
        when = datetime.now(timezone.utc) - timedelta(hours=1)
        for p in (murray, goff):
            db.add(PlayerNews(player_id=p.id, source="ESPN", external_id="70",
                              headline="Free-agent pickups for Week 7: Jared Goff and more",
                              url="https://www.espn.com/nfl/story/_/id/70/x", published_at=when))
        db.add(PlayerNews(player_id=murray.id, source="ESPN", external_id="71",
                          headline="Cardinals QB day-to-day with foot injury",
                          url="https://www.espn.com/nfl/story/_/id/71/x", published_at=when))
        await db.commit()
        got = await svc.recent_news_for_players([murray.id, goff.id], db)
    assert sorted((n.external_id, p.last_name) for n, p in got) == [("70", "Goff"), ("71", "Murray")]
