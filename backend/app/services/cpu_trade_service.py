"""CPU trade responses (QA round 2 #6).

CPU-managed teams have nobody to answer a trade offer, so offers to them sat
PENDING forever. They now respond immediately with a simple value check:
each player is worth more the better their Sleeper overall rank
(Player.search_rank, the same signal the draft AI ranks by). The CPU accepts
when what it receives is worth at least what it gives up (times a small
margin); otherwise it declines.

An accepted offer still goes through the league's normal commissioner review
(trades in this app always do); a declined one is closed immediately.

QA 2026-10-19 (LI9, "still pending"): the reply only ever ran inside
propose_trade, so any offer that was already PENDING when its target became
CPU-managed never got one -- offers made before the reply shipped, and offers
to a team whose owner later released it / deleted their account (both flip
is_cpu on). answer_pending_cpu_trades() sweeps those: the scheduler runs it
every tick and the trade list runs it for its league before reading, so a CPU
answers within one scheduler interval at most.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.player import Player
from app.models.team import Team
from app.models.transaction import Transaction, TransactionStatus, TransactionType

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


def apply_cpu_verdict(details: dict, verdict: dict) -> TransactionStatus:
    """Record a CPU verdict on a trade's details (in place); returns the
    status the trade should now have (DENIED when declined, else PENDING
    for the usual commissioner review)."""
    details["cpu_response"] = "accepted" if verdict["accepted"] else "rejected"
    details["cpu_reason"] = verdict["reason"]
    details["cpu_value"] = {"received": verdict["value_received"], "given": verdict["value_given"]}
    return TransactionStatus.PENDING if verdict["accepted"] else TransactionStatus.DENIED


async def answer_pending_cpu_trades(db: AsyncSession, league_id: str | None = None) -> int:
    """Give a CPU reply to every PENDING trade aimed at a CPU-managed team
    that doesn't have one yet. Flushes but doesn't commit. Returns how many
    trades were answered."""
    q = select(Transaction).where(
        Transaction.type == TransactionType.TRADE,
        Transaction.status == TransactionStatus.PENDING,
    )
    if league_id is not None:
        q = q.where(Transaction.league_id == league_id)
    unanswered = [
        t for t in (await db.execute(q)).scalars().all()
        if (t.details or {}).get("target_team_id") and "cpu_response" not in (t.details or {})
    ]
    if not unanswered:
        return 0
    target_ids = {t.details["target_team_id"] for t in unanswered}
    cpu_ids = set((await db.execute(
        select(Team.id).where(Team.id.in_(target_ids), Team.is_cpu.is_(True))
    )).scalars().all())
    answered = 0
    for t in unanswered:
        if t.details["target_team_id"] not in cpu_ids:
            continue
        details = dict(t.details)
        verdict = await evaluate_cpu_response(
            db, list(details.get("offered_player_ids") or []), list(details.get("requested_player_ids") or [])
        )
        t.status = apply_cpu_verdict(details, verdict)
        t.details = details  # reassign so the JSON column is marked dirty
        answered += 1
    if answered:
        await db.flush()
    return answered
