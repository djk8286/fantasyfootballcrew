"""
Smart Trade Review Assistant (AI Co-Commissioner v1).

Commissioner-facing AI analysis of a pending trade -- fairness, league
impact, and a collusion-pattern check, with a clear APPROVE/REVIEW
CLOSELY/VETO recommendation. Distinct from ai.py's analyze_trade
(which grades a trade for the two trading parties' own benefit); this
one is about whether the COMMISSIONER should approve it. The result is
stored directly on the Transaction row's own `details` JSON blob
(`details["ai_review"]`) rather than a new table -- a top-level key
assignment on an already-MutableDict-backed column is exactly the
mutation SQLAlchemy's mutable extension tracks correctly, and it puts
the AI's prior take on the exact same row as the human's eventual
`status`/`reviewed_by` decision, satisfying "log the AI recommendation
alongside the final human decision" for free.
"""
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.models.league import League
from app.models.team import Team
from app.models.player import Player
from app.models.transaction import Transaction, TransactionType
from app.services.ai_service import AIService
from app.services.standings_service import get_standings

_RECOMMENDATION_RE = re.compile(r"^RECOMMENDATION:\s*(APPROVE|REVIEW CLOSELY|VETO)", re.MULTILINE)


def _get_ai_service() -> AIService:
    """Same factory ai.py/commissioner_digest_service.py both use --
    duplicated (it's 3 lines) rather than shared."""
    if settings.OPENAI_API_KEY:
        return AIService(api_key=settings.OPENAI_API_KEY, provider="openai")
    if settings.ANTHROPIC_API_KEY:
        return AIService(api_key=settings.ANTHROPIC_API_KEY, provider="anthropic")
    return AIService(api_key=None)


async def build_trade_review_context(trade: Transaction, league: League, proposer: Team, target: Team, db: AsyncSession) -> dict[str, Any]:
    details = trade.details or {}
    offered_ids = details.get("offered_player_ids") or []
    requested_ids = details.get("requested_player_ids") or []

    players_result = await db.execute(select(Player).where(Player.id.in_(offered_ids + requested_ids)))
    player_map = {p.id: f"{p.first_name} {p.last_name} ({p.position})" for p in players_result.scalars().all()}

    standings = await get_standings(league.id, db)

    # Collusion-pattern context: prior trades specifically between these
    # two teams (either direction -- proposer/target roles can swap
    # trade to trade).
    recent_result = await db.execute(
        select(Transaction).where(
            Transaction.league_id == league.id,
            Transaction.type == TransactionType.TRADE,
            Transaction.id != trade.id,
        ).order_by(Transaction.processed_at.desc()).limit(10)
    )
    both_ids = {proposer.id, target.id}
    recent_trades_between_teams = [
        {"status": t.status.value, "details": t.details, "processed_at": str(t.processed_at)}
        for t in recent_result.scalars().all()
        if {t.team_id, (t.details or {}).get("target_team_id")} == both_ids
    ]

    return {
        "league_name": league.name,
        "proposer_name": proposer.name,
        "target_name": target.name,
        "offered_players": [player_map.get(pid, pid) for pid in offered_ids],
        "requested_players": [player_map.get(pid, pid) for pid in requested_ids],
        "standings": standings,
        "recent_trades_between_teams": recent_trades_between_teams,
        "scoring_config": league.scoring_config or {},
    }


async def generate_and_save_trade_review(trade: Transaction, league: League, proposer: Team, target: Team, analyzed_by: str, db: AsyncSession) -> dict[str, Any]:
    """Calls the LLM and persists the result onto trade.details. Never
    touches trade.status/reviewed_by -- review_trade's own approve/deny
    flow is completely independent of whether this was ever called."""
    context = await build_trade_review_context(trade, league, proposer, target, db)
    service = _get_ai_service()
    content = await service.generate_trade_review(**context)

    match = _RECOMMENDATION_RE.match(content)
    recommendation = match.group(1) if match else None

    review = {
        "content": content,
        "recommendation": recommendation,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "analyzed_by": analyzed_by,
    }
    # Top-level key assignment on the MutableDict-backed column -- this
    # IS the mutation SQLAlchemy's mutable extension tracks correctly,
    # unlike mutating a nested dict already read out of it.
    trade.details = {**(trade.details or {}), "ai_review": review}
    await db.commit()
    return review
