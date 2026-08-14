"""
Waiver processing core (extracted from waivers.py in Phase 6, "Best-Ball
Hybrid", Step 5).

process_league_waivers is the single shared implementation behind BOTH
the commissioner's manual "Process Waivers" endpoint AND Best-Ball's new
scheduler pass that auto-processes queued claims the moment a league's
management window reopens -- exactly one implementation, not two,
mirroring how Guillotine/playoffs already live in their own service
modules called by both a route and the scheduler.

reviewed_by is str | None (Transaction.reviewed_by is already nullable)
-- None means "the scheduler did this, not a specific commissioner",
same convention Guillotine's own scheduler-triggered passes already use
for actions that don't have a human actor.
"""
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.models.league import League
from app.models.team import Team
from app.models.player import Player
from app.models.transaction import Transaction, TransactionType, TransactionStatus
from app.models.contract import Contract
from app.services.salary_cap_service import get_salary_cap_settings, compute_waiver_salary, team_cap_summary, release_player
from app.services.notification_service import notify_team_owners
from app.models.notification import NotificationType


async def _priority_order(league: League, league_id: str, db: AsyncSession) -> list[str]:
    """Current waiver priority, defaulting to team creation order if never set."""
    if league.waiver_priority:
        return league.waiver_priority
    result = await db.execute(
        select(Team).where(Team.league_id == league_id).order_by(Team.created_at)
    )
    return [t.id for t in result.scalars().all()]


async def process_league_waivers(league: League, db: AsyncSession, reviewed_by: str | None = None) -> dict[str, Any]:
    """Walks pending claims in priority order, resolving conflicts.
    Commits internally (same as the endpoint always did). Callers must
    already own any pre-condition gating (commissioner check for the
    manual endpoint, management-window check for Best-Ball) -- this
    function itself has no permission/window logic of its own."""
    league_id = league.id
    order = await _priority_order(league, league_id, db)

    teams_result = await db.execute(select(Team).where(Team.league_id == league_id))
    teams_by_id = {t.id: t for t in teams_result.scalars().all()}

    claims_result = await db.execute(
        select(Transaction).where(
            Transaction.league_id == league_id,
            Transaction.type == TransactionType.WAIVER,
            Transaction.status == TransactionStatus.PENDING,
        ).order_by(Transaction.processed_at.asc())
    )
    all_pending = claims_result.scalars().all()

    # Each team's single earliest pending claim is considered this run.
    earliest_claim_by_team: dict[str, Transaction] = {}
    for claim in all_pending:
        if claim.team_id not in earliest_claim_by_team:
            earliest_claim_by_team[claim.team_id] = claim

    granted_players: set[str] = set()
    granted: list[dict] = []
    denied: list[dict] = []
    skipped: list[dict] = []
    new_priority = list(order)

    # Salary-Cap (Phase 5): batch-fetched once, same N+1-avoidance
    # discipline the existing player_names lookup below already uses --
    # not per-claim.
    cap_settings = get_salary_cap_settings(league)
    cap_enabled = cap_settings["enabled"]
    all_add_ids = {c.details.get("add_player_id") for c in earliest_claim_by_team.values() if c.details}
    players_by_id: dict[str, Player] = {}
    if cap_enabled and all_add_ids:
        players_result = await db.execute(select(Player).where(Player.id.in_(all_add_ids)))
        players_by_id = {p.id: p for p in players_result.scalars().all()}
    active_contract_by_team_and_player: dict[tuple[str, str], Contract] = {}
    if cap_enabled:
        contracts_result = await db.execute(
            select(Contract).where(Contract.league_id == league_id, Contract.is_active == True)  # noqa: E712
        )
        active_contract_by_team_and_player = {(c.team_id, c.player_id): c for c in contracts_result.scalars().all()}

    for team_id in order:
        claim = earliest_claim_by_team.get(team_id)
        if not claim:
            continue

        details = claim.details or {}
        add_id = details.get("add_player_id")
        drop_id = details.get("drop_player_id")
        team = teams_by_id.get(team_id)

        if team and team.eliminated_week is not None:
            # Guillotine "haunt" twist (Phase 4): a ghost team stays in
            # League.waiver_priority forever (never removed below), so
            # its presence still affects the position of teams behind
            # it -- but it can never actually be GRANTED a claim. Denying
            # here (not skipping) means this claim is a final outcome,
            # not something that retries next run.
            claim.status = TransactionStatus.DENIED
            denied.append({"team_id": team_id, "add_player_id": add_id, "reason": "team is eliminated"})
            continue

        if not team or not add_id or add_id in granted_players:
            claim.status = TransactionStatus.DENIED
            denied.append({"team_id": team_id, "add_player_id": add_id})
            continue

        roster = set(team.roster or [])
        if drop_id and drop_id not in roster:
            claim.status = TransactionStatus.DENIED
            denied.append({"team_id": team_id, "add_player_id": add_id, "reason": "drop player no longer on roster"})
            continue

        if drop_id:
            roster.discard(drop_id)
        roster.add(add_id)

        # Salary-Cap (Phase 5): net the drop's salary release against the
        # add's salary cost -- both happen in the same roster write, so
        # they must be checked together, not as two independent deltas.
        new_salary = 0.0
        if cap_enabled:
            add_player = players_by_id.get(add_id)
            if not add_player:
                claim.status = TransactionStatus.DENIED
                denied.append({"team_id": team_id, "add_player_id": add_id, "reason": "player not found"})
                continue
            drop_salary = 0.0
            if drop_id:
                existing_contract = active_contract_by_team_and_player.get((team_id, drop_id))
                drop_salary = existing_contract.salary if existing_contract else 0.0
            new_salary = compute_waiver_salary(add_player, cap_settings)
            current_summary = await team_cap_summary(team, league, db)
            projected_cap = round(current_summary["cap_used"] - drop_salary + new_salary, 2)
            if projected_cap > cap_settings["cap_total"]:
                claim.status = TransactionStatus.DENIED
                denied.append({
                    "team_id": team_id, "add_player_id": add_id,
                    "reason": f"would exceed salary cap (${round(projected_cap - cap_settings['cap_total'], 2)} over)",
                })
                continue
            if len(roster) > cap_settings["max_roster_size"]:
                claim.status = TransactionStatus.DENIED
                denied.append({"team_id": team_id, "add_player_id": add_id, "reason": "would exceed max roster size"})
                continue

        # Atomic, conditional roster write -- same roster_version
        # compare-and-swap commissioner.review_trade uses, and for the same
        # reason: this endpoint's roster read (teams_by_id, above) and this
        # write are two separate points in time with no lock between them.
        # Confirmed locally: a trade approved for this team while waivers
        # were processing landed cleanly (status=="approved"), but the
        # trade's roster change was silently overwritten a moment later by
        # this write, which was still computing off the pre-trade roster --
        # the traded-away player stayed on the roster and the received
        # player never arrived, with no error anywhere. On a CAS miss here,
        # leave the claim PENDING (not denied) and report it skipped -- the
        # next "Process Waivers" run picks it back up with a fresh read,
        # rather than failing the whole batch over one contested team.
        cas_result = await db.execute(
            update(Team)
            .where(Team.id == team.id, Team.roster_version == team.roster_version)
            .values(roster=list(roster), roster_version=Team.roster_version + 1)
        )
        if cas_result.rowcount == 0:
            skipped.append({
                "team_id": team_id, "add_player_id": add_id,
                "reason": "roster changed concurrently (e.g. a trade was just approved) -- will retry on next processing run",
            })
            continue

        # Salary-Cap (Phase 5): release the dropped player's contract
        # (charging dead money if it had years remaining) and sign the
        # new one, now that the roster write itself has actually landed.
        if cap_enabled:
            if drop_id:
                await release_player(db, team, drop_id, league, reason="waiver drop")
            db.add(Contract(
                league_id=league_id, team_id=team.id, player_id=add_id,
                salary=new_salary, contract_years=cap_settings["waiver_contract_years"],
                signed_year=datetime.now(timezone.utc).year, source="waiver", is_active=True,
            ))

        claim.status = TransactionStatus.APPROVED
        claim.reviewed_by = reviewed_by
        granted_players.add(add_id)
        granted.append({"team_id": team_id, "add_player_id": add_id, "drop_player_id": drop_id})

        # Move this team to the back of the priority queue
        new_priority.remove(team_id)
        new_priority.append(team_id)

    league.waiver_priority = new_priority

    # Notify affected teams -- granted/denied are final outcomes worth
    # telling someone about; skipped isn't (it just means "will retry
    # next run", not resolved yet). One batched player-name lookup rather
    # than a query per notification.
    waiver_link = f"/leagues/{league_id}/waivers"
    notify_player_ids = {e["add_player_id"] for e in granted + denied if e.get("add_player_id")}
    player_names: dict[str, str] = {}
    if notify_player_ids:
        presult = await db.execute(select(Player).where(Player.id.in_(notify_player_ids)))
        player_names = {p.id: f"{p.first_name} {p.last_name}" for p in presult.scalars().all()}

    for entry in granted:
        team = teams_by_id.get(entry["team_id"])
        if team:
            pname = player_names.get(entry["add_player_id"], "a player")
            await notify_team_owners(db, team, NotificationType.WAIVER_APPROVED,
                                      f"Your waiver claim for {pname} was approved.", league_id, waiver_link)
    for entry in denied:
        team = teams_by_id.get(entry["team_id"])
        if team and entry.get("add_player_id"):
            pname = player_names.get(entry["add_player_id"], "a player")
            await notify_team_owners(db, team, NotificationType.WAIVER_DENIED,
                                      f"Your waiver claim for {pname} was denied.", league_id, waiver_link)

    await db.commit()

    return {
        "granted": granted,
        "skipped": skipped,
        "denied": denied,
        "updated_priority": new_priority,
    }
