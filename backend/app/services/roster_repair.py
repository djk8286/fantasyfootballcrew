"""Startup repair: a player on more than one roster in a league.

Idempotent (does nothing once every player is on at most one roster per
league), run once per process start like the season-stats and
default-lineup repairs (scheduler.run_scheduler).

Which team keeps a duplicated player is decided deterministically from
how each holder got him, best evidence first:

  0. drafted him (a DraftPick in that league's draft)
  1. received him in an approved trade
  2. added him with an approved waiver claim
  3. no record

ties broken by the earliest time for that evidence (pick time, trade
time, waiver grant time, falling back to claim time for older claims
that didn't record one), then team id. A waiver grant ranks after a
draft pick or trade because waiver processing was the path that never
re-checked whether the player was still a free agent (fixed alongside
this repair, see roster_guard); claims granted before that fix didn't
record when they were granted, so their claim time (filed while the
player was still free) can't be compared with a pick.

For every other holder: the player is removed from that roster
(roster_version bumped), his active contract with that team (cap
leagues) is deactivated without dead money, an approved waiver claim
that added him is marked DENIED with the reason in details.voided, and
each change is logged.
Saved lineups aren't edited; scoring already ignores starters who
aren't on the roster. A player listed twice on one roster is collapsed
to one entry.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contract import Contract
from app.models.draft import Draft, DraftPick
from app.models.team import Team
from app.models.transaction import Transaction, TransactionStatus, TransactionType
from app.services.roster_guard import lock_league_rosters

_FAR_FUTURE = datetime.max.replace(tzinfo=timezone.utc)


def _utc(dt: Any) -> datetime:
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except ValueError:
            return _FAR_FUTURE
    if not isinstance(dt, datetime):
        return _FAR_FUTURE
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _evidence(db: AsyncSession, league_id: str, player_id: str, team_ids: set[str]) -> dict[str, tuple]:
    """team_id -> (rank, time) of the best evidence that team acquired the player."""
    best: dict[str, tuple] = {}

    def offer(team_id: str, rank: int, when: Any) -> None:
        if team_id not in team_ids:
            return
        key = (rank, _utc(when))
        if team_id not in best or key < best[team_id]:
            best[team_id] = key

    picks = await db.execute(
        select(DraftPick.team_id, DraftPick.drafted_at)
        .join(Draft, Draft.id == DraftPick.draft_id)
        .where(Draft.league_id == league_id, DraftPick.player_id == player_id)
    )
    for team_id, at in picks.all():
        offer(team_id, 0, at)

    txs = await db.execute(select(Transaction).where(
        Transaction.league_id == league_id,
        Transaction.status == TransactionStatus.APPROVED,
        Transaction.type.in_([TransactionType.TRADE, TransactionType.WAIVER]),
    ))
    for tx in txs.scalars().all():
        d = tx.details or {}
        if tx.type == TransactionType.TRADE:
            if player_id in (d.get("requested_player_ids") or []):
                offer(tx.team_id, 1, tx.processed_at)
            if player_id in (d.get("offered_player_ids") or []) and d.get("target_team_id"):
                offer(d["target_team_id"], 1, tx.processed_at)
        elif d.get("add_player_id") == player_id and not d.get("voided"):
            offer(tx.team_id, 2, d.get("granted_at") or tx.processed_at)
    return best


async def repair_duplicate_rostered_players(db: AsyncSession) -> list[dict]:
    """Resolve every duplicate; returns one entry per change made."""
    changes: list[dict] = []
    league_ids = [r[0] for r in (await db.execute(select(Team.league_id).distinct())).all()]
    for league_id in league_ids:
        teams = list((await db.execute(
            select(Team).where(Team.league_id == league_id).execution_options(populate_existing=True)
        )).scalars().all())
        holders: dict[str, list[Team]] = {}
        self_dupes = False
        for t in teams:
            roster = list(t.roster or [])
            self_dupes |= len(roster) != len(set(roster))
            for pid in dict.fromkeys(roster):
                holders.setdefault(pid, []).append(t)
        dupes = {pid: ts for pid, ts in holders.items() if len(ts) > 1}
        if not dupes and not self_dupes:
            continue

        await lock_league_rosters(db, league_id)
        new_rosters = {t.id: list(dict.fromkeys(t.roster or [])) for t in teams}
        for t in teams:
            if len(new_rosters[t.id]) != len(t.roster or []):
                changes.append({"league_id": league_id, "player_id": None, "removed_from": t.id,
                                "kept_on": t.id, "reason": "listed twice on one roster"})

        now = datetime.now(timezone.utc).isoformat()
        for pid, ts in sorted(dupes.items()):
            ev = await _evidence(db, league_id, pid, {t.id for t in ts})
            ranked = sorted(ts, key=lambda t: (*ev.get(t.id, (3, _FAR_FUTURE)), t.id))
            keep = ranked[0]
            for loser in ranked[1:]:
                new_rosters[loser.id] = [x for x in new_rosters[loser.id] if x != pid]
                await db.execute(update(Contract).where(
                    Contract.team_id == loser.id, Contract.player_id == pid, Contract.is_active == True  # noqa: E712
                ).values(is_active=False))
                claims = await db.execute(select(Transaction).where(
                    Transaction.league_id == league_id, Transaction.team_id == loser.id,
                    Transaction.type == TransactionType.WAIVER, Transaction.status == TransactionStatus.APPROVED,
                ))
                for c in claims.scalars().all():
                    if (c.details or {}).get("add_player_id") == pid and not (c.details or {}).get("voided"):
                        c.details = {**(c.details or {}), "voided": f"player was already on {keep.name}'s roster",
                                     "voided_at": now}
                        c.status = TransactionStatus.DENIED
                changes.append({
                    "league_id": league_id, "player_id": pid, "removed_from": loser.id, "removed_from_name": loser.name,
                    "kept_on": keep.id, "kept_on_name": keep.name,
                    "kept_evidence": ev.get(keep.id, (3,))[0], "removed_evidence": ev.get(loser.id, (3,))[0],
                })

        for t in teams:
            if new_rosters[t.id] != list(t.roster or []):
                await db.execute(update(Team).where(Team.id == t.id).values(
                    roster=new_rosters[t.id], roster_version=Team.roster_version + 1))
        await db.commit()  # per league, so its lock isn't held while the next is scanned
    return changes
