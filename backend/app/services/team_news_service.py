"""
Per-Team Player News (2026-09-22, sources reworked 2026-10-18) -- a
daily-refreshed digest scoped to ONE fantasy team's actual roster.
Inputs are all real data:
  - published ESPN articles about rostered players (player_news table,
    fetched by espn_news_service.py -- real URLs, never AI-written), and
  - this app's own free, structured detection of injury-status/team
    changes since the last check.
If an AI key is configured, one LLM call per team per day summarizes
those inputs (and only those). With no key, the digest is assembled
directly from the same data -- the feature works without AI. Links are
never part of `content`; the API returns the articles alongside it.
"""
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.team import Team
from app.models.player import Player
from app.models.team_player_news import TeamPlayerNews
from app.services.ai_service import AIService
from app.services import espn_news_service


def _get_ai_service() -> AIService:
    """Same factory every other AI-calling service module duplicates
    (it's 3 lines) rather than shares -- see ai_history_service.py's
    own copy for the precedent."""
    if settings.OPENAI_API_KEY:
        return AIService(api_key=settings.OPENAI_API_KEY, provider="openai")
    if settings.ANTHROPIC_API_KEY:
        return AIService(api_key=settings.ANTHROPIC_API_KEY, provider="anthropic")
    return AIService(api_key=None)


async def _roster_players(team: Team, db: AsyncSession) -> list[Player]:
    if not team.roster:
        return []
    result = await db.execute(select(Player).where(Player.id.in_(team.roster)))
    return list(result.scalars().all())


def _detect_changes(players: list[Player], previous_snapshot: dict) -> list[dict[str, Any]]:
    """Free (no LLM) diff of each rostered player's injury_status/team
    against the snapshot taken at the last generation. A player with no
    prior snapshot entry (new to this roster, or this is the very
    first run for this team) is reported as "added to roster" rather
    than silently skipped -- that's real, relevant news for this panel
    too, not just injury/team changes."""
    changes: list[dict[str, Any]] = []
    for p in players:
        prev = previous_snapshot.get(p.id)
        name = f"{p.first_name} {p.last_name}"
        if prev is None:
            changes.append({"player": name, "change": "added to this roster"})
            continue
        if prev.get("injury_status") != p.injury_status:
            changes.append({
                "player": name,
                "change": f"injury status changed from {prev.get('injury_status') or 'none'} to {p.injury_status or 'none'}",
            })
        if prev.get("team") != p.team:
            changes.append({
                "player": name,
                "change": f"NFL team changed from {prev.get('team') or 'Free Agent'} to {p.team or 'Free Agent'}",
            })
    return changes


def _ai_configured(service: AIService) -> bool:
    return bool(service.api_key)


def _plain_digest(changes: list[dict[str, Any]], articles: list[dict[str, Any]]) -> str:
    """No-AI digest: the detected changes as-is. Headlines are not
    repeated here -- the API/UI already lists them with their real
    links. With nothing changed but articles present, point at them."""
    lines = [f"{c['player']}: {c['change']}." for c in changes]
    if not lines and articles:
        return f"No injury or team changes since the last check. {len(articles)} recent article(s) about this roster are listed above."
    if not lines:
        return "Nothing new detected on this roster since the last check."
    return "\n".join(lines)


def _snapshot(players: list[Player]) -> dict[str, dict]:
    return {p.id: {"injury_status": p.injury_status, "team": p.team} for p in players}


async def get_team_news(team_id: str, db: AsyncSession) -> TeamPlayerNews | None:
    result = await db.execute(select(TeamPlayerNews).where(TeamPlayerNews.team_id == team_id))
    return result.scalar_one_or_none()


async def generate_and_save_team_news(team: Team, db: AsyncSession) -> TeamPlayerNews | None:
    """No-ops (returns None) for a team with an empty roster -- nothing
    to report news about, same "no-op rather than error" convention
    team_recap_service.generate_and_save_recap already follows for a
    league with no scored data yet."""
    players = await _roster_players(team, db)
    if not players:
        return None

    existing = await get_team_news(team.id, db)
    previous_snapshot = existing.player_snapshot if existing else {}
    changes = _detect_changes(players, previous_snapshot)

    players_payload = [
        {
            "name": f"{p.first_name} {p.last_name}", "position": p.position,
            "team": p.team or "Free Agent", "injury_status": p.injury_status or "none reported",
        }
        for p in players
    ]

    recent = await espn_news_service.recent_news_for_players([p.id for p in players], db, days=7, limit=15)
    articles_payload = [
        {
            "player": f"{p.first_name} {p.last_name}", "headline": n.headline,
            "description": n.description, "published_at": n.published_at,
        }
        for n, p in recent
    ]

    service = _get_ai_service()
    if _ai_configured(service):
        content = await service.generate_team_player_news(
            team_name=team.name, players=players_payload, detected_changes=changes,
            articles=articles_payload,
        )
    else:
        content = _plain_digest(changes, articles_payload)

    if existing:
        existing.content = content
        existing.player_snapshot = _snapshot(players)
        news = existing
    else:
        news = TeamPlayerNews(
            team_id=team.id, league_id=team.league_id, content=content,
            player_snapshot=_snapshot(players),
        )
        db.add(news)

    await db.commit()
    await db.refresh(news)
    return news
