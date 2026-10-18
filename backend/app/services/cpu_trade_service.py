"""CPU trade responses (QA round 2 #6).

CPU-managed teams have nobody to answer a trade offer, so offers to them sat
PENDING forever. They now respond immediately with a simple value check:
each player is worth more the better their Sleeper overall rank
(Player.search_rank, the same signal the draft AI ranks by). The CPU accepts
when what it receives is worth at least what it gives up (times a small
margin); otherwise it declines.

An accepted offer still goes through the league's normal commissioner review
(trades in this app always do); a declined one is closed immediately.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.player import Player

UNRANKED = 1000
ACCEPT_MARGIN = 1.05  # CPU wants a slight edge


def player_value(player: Player | None) -> float:
    rank = (player.search_rank if player and player.search_rank else UNRANKED)
    rank = min(max(int(rank), 1), UNRANKED)
    return 1000.0 / (rank + 9)  # rank 1 -> 100, rank 50 -> ~17, unranked -> ~1


async def evaluate_cpu_response(db: AsyncSession, offered_ids: list[str], requested_ids: list[str]) -> dict:
    ids = list({*offered_ids, *requested_ids})
    players = {}
    if ids:
        res = await db.execute(select(Player).where(Player.id.in_(ids)))
        players = {p.id: p for p in res.scalars().all()}
    receives = sum(player_value(players.get(i)) for i in offered_ids)
    gives = sum(player_value(players.get(i)) for i in requested_ids)
    accept = receives >= gives * ACCEPT_MARGIN and receives > 0
    return {
        "accepted": accept,
        "value_received": round(receives, 1),
        "value_given": round(gives, 1),
        "reason": (
            "CPU accepted: the offer meets its value threshold."
            if accept else
            "CPU declined: it would give up more value than it gets back."
        ),
    }
