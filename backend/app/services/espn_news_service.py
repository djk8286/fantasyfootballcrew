"""
Real player news from ESPN (2026-10-18) -- replaces the AI web-search
headlines team_news_service used to ask an LLM for (those links could be
invented or stale). Pulls ESPN's public NFL news feed, keeps only
articles ESPN itself tags with an athlete, joins those athletes to our
players via Player.espn_id (synced from Sleeper), and stores the
headline/URL/published time verbatim in player_news.

Endpoint notes, verified live 2026-10-18 from the box:
  - site.api.espn.com/apis/site/v2/sports/football/nfl/news?limit=50
    -> 200, ~50 newest articles, each with categories[] including
       {"type": "athlete", "athleteId": ...} tags.
  - same URL with ?team=<espn team id> -> 200, ~50 articles for that team
    (much better depth per player than the league-wide feed alone).
  - ?athletes=<id> / ?player=<id> are silently ignored (same as no filter),
    and site.web.api.espn.com/.../athletes/<id>/news 404s -- so there is
    no per-athlete endpoint; per-team feeds are the finest grain.
These are unofficial, undocumented endpoints (no published ToS/SLA):
every call has a hard timeout, one failing feed never fails the pass,
and the scheduler polls at most every few hours (REFRESH_INTERVAL_S).
"""
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.player import Player
from app.models.player_news import PlayerNews

ESPN_NEWS_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news"
SOURCE = "ESPN"
HTTP_TIMEOUT_S = 15
REFRESH_INTERVAL_S = 3 * 60 * 60
RETENTION_DAYS = 30
# ESPN's NFL team ids (1-30, then 33 BAL and 34 HOU; 31/32 are unused).
ESPN_TEAM_IDS = [*range(1, 31), 33, 34]
# Small pause between feed requests -- 33 requests per pass, spread out.
REQUEST_SPACING_S = 0.5


def _parse_published(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_articles(payload: dict) -> list[dict[str, Any]]:
    """ESPN feed JSON -> [{external_id, headline, description, url,
    published_at, athlete_ids}], skipping anything without a real web
    URL, a publish time, or at least one athlete tag."""
    out: list[dict[str, Any]] = []
    for a in payload.get("articles") or []:
        url = ((a.get("links") or {}).get("web") or {}).get("href")
        published = _parse_published(a.get("published"))
        athlete_ids = sorted({
            str(c.get("athleteId") or (c.get("athlete") or {}).get("id"))
            for c in a.get("categories") or []
            if c.get("type") == "athlete" and (c.get("athleteId") or (c.get("athlete") or {}).get("id"))
        })
        if not (a.get("id") and a.get("headline") and url and published and athlete_ids):
            continue
        if not url.startswith("https://"):
            url = "https://" + url.split("://", 1)[-1]
        out.append({
            "external_id": str(a["id"]),
            "headline": a["headline"].strip(),
            "description": (a.get("description") or "").strip() or None,
            "url": url,
            "published_at": published,
            "athlete_ids": athlete_ids,
        })
    return out


async def fetch_feed(client: httpx.AsyncClient, team_id: int | None = None) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": 50}
    if team_id is not None:
        params["team"] = team_id
    resp = await client.get(ESPN_NEWS_URL, params=params)
    resp.raise_for_status()
    return parse_articles(resp.json())


async def save_articles(articles: list[dict[str, Any]], db: AsyncSession) -> int:
    """Upsert-by-skip: (source, external_id, player_id) already stored ->
    left alone. Returns the number of new rows."""
    espn_ids = {aid for a in articles for aid in a["athlete_ids"]}
    if not espn_ids:
        return 0
    rows = (await db.execute(select(Player.id, Player.espn_id).where(Player.espn_id.in_(espn_ids)))).all()
    players_by_espn: dict[str, list[str]] = {}
    for pid, eid in rows:
        players_by_espn.setdefault(eid, []).append(pid)

    ext_ids = {a["external_id"] for a in articles}
    existing = {
        (ext, pid)
        for ext, pid in (await db.execute(
            select(PlayerNews.external_id, PlayerNews.player_id).where(
                PlayerNews.source == SOURCE, PlayerNews.external_id.in_(ext_ids)
            )
        )).all()
    }

    added = 0
    for a in articles:
        for eid in a["athlete_ids"]:
            for pid in players_by_espn.get(eid, []):
                if (a["external_id"], pid) in existing:
                    continue
                existing.add((a["external_id"], pid))
                db.add(PlayerNews(
                    player_id=pid, source=SOURCE, external_id=a["external_id"],
                    headline=a["headline"][:500], description=a["description"],
                    url=a["url"], published_at=a["published_at"],
                ))
                added += 1
    await db.commit()
    return added


async def refresh_player_news(db: AsyncSession, team_ids: list[int] | None = None) -> dict[str, int]:
    """One polite pass: league-wide feed + every team feed, deduped across
    feeds, then prune anything older than RETENTION_DAYS. A failing feed
    is counted and skipped; only "every feed failed" raises (so run_job
    records a real failure rather than a silent empty success)."""
    team_ids = ESPN_TEAM_IDS if team_ids is None else team_ids
    by_id: dict[str, dict[str, Any]] = {}
    failed = 0
    feeds: list[int | None] = [None, *team_ids]
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S, headers={"User-Agent": "FantasyFootballCrew/1.0"}) as client:
        for i, tid in enumerate(feeds):
            if i:
                await asyncio.sleep(REQUEST_SPACING_S)
            try:
                for a in await fetch_feed(client, tid):
                    by_id.setdefault(a["external_id"], a)
            except (httpx.HTTPError, ValueError) as e:
                failed += 1
                print(f"[espn_news] feed team={tid} failed: {e!r}")
    if failed == len(feeds):
        raise RuntimeError(f"All {failed} ESPN news feeds failed")

    added = await save_articles(list(by_id.values()), db)
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    await db.execute(delete(PlayerNews).where(PlayerNews.published_at < cutoff))
    await db.commit()
    return {"articles": len(by_id), "added": added, "failed_feeds": failed}


async def recent_news_for_players(
    player_ids: list[str], db: AsyncSession, days: int = 7, limit: int = 20
) -> list[tuple[PlayerNews, Player]]:
    """Newest-first articles for these players within `days`."""
    if not player_ids:
        return []
    since = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(PlayerNews, Player)
        .join(Player, Player.id == PlayerNews.player_id)
        .where(PlayerNews.player_id.in_(player_ids), PlayerNews.published_at >= since)
        .order_by(PlayerNews.published_at.desc())
        .limit(limit)
    )
    return [(n, p) for n, p in result.all()]


def serialize(news: PlayerNews, player: Player) -> dict[str, Any]:
    return {
        "id": news.id, "player_id": player.id,
        "player_name": f"{player.first_name} {player.last_name}",
        "headline": news.headline, "url": news.url, "source": news.source,
        "published_at": news.published_at,
    }


def serialize_grouped(rows: list[tuple[PlayerNews, Player]], limit: int = 10) -> list[dict[str, Any]]:
    """One entry per article (an article tagging three rostered players
    is listed once, with all three names), newest first."""
    out: list[dict[str, Any]] = []
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for n, p in rows:
        key = (n.source, n.external_id)
        name = f"{p.first_name} {p.last_name}"
        if key in by_key:
            entry = by_key[key]
            if name not in entry["player_names"]:
                entry["player_names"].append(name)
                entry["player_name"] = ", ".join(entry["player_names"])
            continue
        if len(out) >= limit:
            continue
        entry = {**serialize(n, p), "player_names": [name]}
        by_key[key] = entry
        out.append(entry)
    return out
