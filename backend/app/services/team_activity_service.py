"""A team's record and streak, and the league activity feed (trades,
waiver claims, the draft and weekly results) with names resolved."""
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.draft import Draft, DraftPick, DraftRunStatus
from app.models.league import League
from app.models.player import Player
from app.models.team import Team
from app.models.transaction import Transaction, TransactionStatus, TransactionType
from app.models.weekly_score import WeeklyScore
from app.services.nfl_schedule_service import as_utc
from app.services.season_weeks import WeekState, season_week_states, week_bounds
from app.services.standings_service import _effective_matchups, get_standings


# ─── Record ─────────────────────────────────────────────────────────────

async def weekly_results(league: League, teams: list[Team], db: AsyncSession) -> list[dict]:
    """Every finished head-to-head game, oldest first:
    {year, week, team_a, team_b, score_a, score_b}. Same weeks and pairings
    get_standings counts."""
    rows = (await db.execute(select(WeeklyScore).where(WeeklyScore.league_id == league.id))).scalars().all()
    by_week: dict[tuple[int, int], dict[str, float]] = {}
    for ws in rows:
        by_week.setdefault((ws.year, ws.week), {})[ws.team_id] = ws.total_score
    states = {y: await season_week_states(y, db) for y in {y for y, _ in by_week}}
    out = []
    for (year, week), scores in sorted(by_week.items()):
        if states[year].get(week, WeekState.UNKNOWN) not in (WeekState.FINAL, WeekState.UNKNOWN):
            continue
        for a, b in _effective_matchups(league, teams, week):
            out.append({"year": year, "week": week, "team_a": a, "team_b": b,
                        "score_a": scores.get(a, 0.0), "score_b": scores.get(b, 0.0)})
    return out


def streak(results: list[dict], team_id: str) -> str | None:
    """"W3", "L1" or "T1" from the latest game back, None before any game."""
    marks = []
    for r in results:
        if team_id not in (r["team_a"], r["team_b"]):
            continue
        mine, theirs = (r["score_a"], r["score_b"]) if r["team_a"] == team_id else (r["score_b"], r["score_a"])
        marks.append("W" if mine > theirs else "L" if mine < theirs else "T")
    if not marks:
        return None
    last, n = marks[-1], 0
    for m in reversed(marks):
        if m != last:
            break
        n += 1
    return f"{last}{n}"


async def team_record(league: League, team: Team, teams: list[Team], db: AsyncSession) -> dict[str, Any]:
    """Wins, losses, ties, points for and against, rank and streak, read
    from standings. Team.wins/points_for are never written, which is why
    the team page used to show 0.0 points for."""
    standings = await get_standings(league.id, db)
    rank = next((i + 1 for i, row in enumerate(standings) if row["team_id"] == team.id), None)
    row = next((r for r in standings if r["team_id"] == team.id), None) or {}
    return {
        "wins": row.get("wins", 0),
        "losses": row.get("losses", 0),
        "ties": row.get("ties", 0),
        "points_for": row.get("points_for", 0.0),
        "points_against": row.get("points_against", 0.0),
        "rank": rank,
        "teams": len(standings),
        "streak": streak(await weekly_results(league, teams, db), team.id),
    }


# ─── Activity ───────────────────────────────────────────────────────────

def _names(ids: list[str], players: dict[str, Player]) -> str:
    names = [f"{players[i].first_name} {players[i].last_name}" for i in ids if i in players]
    if not names:
        return "nobody"
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _player_refs(ids: list[str], players: dict[str, Player]) -> list[dict]:
    return [{"id": i, "name": f"{players[i].first_name} {players[i].last_name}",
             "position": players[i].position, "team": players[i].team} for i in ids if i in players]


def _iso(dt: datetime | None) -> str | None:
    return as_utc(dt).isoformat() if dt else None


async def league_activity(
    league: League, teams: list[Team], db: AsyncSession, *,
    viewer_id: str | None = None, team_id: str | None = None, limit: int = 30,
) -> list[dict]:
    """Newest first. Finished trades, added players, the draft and results
    are public. Pending and declined trades and claims only show to the
    managers of a team involved, and carry a cancel target when the viewer
    proposed them."""
    team_by_id = {t.id: t for t in teams}
    mine = {t.id for t in teams if viewer_id and viewer_id in (t.owner_id, t.co_owner_id)}

    def tname(tid: str | None) -> str:
        return team_by_id[tid].name if tid in team_by_id else "A former team"

    txs = (await db.execute(select(Transaction).where(
        Transaction.league_id == league.id,
        Transaction.type.in_([TransactionType.TRADE, TransactionType.WAIVER]),
    ))).scalars().all()
    pids = set()
    for t in txs:
        d = t.details or {}
        pids.update(d.get("offered_player_ids") or [])
        pids.update(d.get("requested_player_ids") or [])
        pids.update(p for p in (d.get("add_player_id"), d.get("drop_player_id")) if p)

    draft = (await db.execute(select(Draft).where(
        Draft.league_id == league.id, Draft.status == DraftRunStatus.COMPLETED,
    ).order_by(Draft.updated_at.desc()).limit(1))).scalar_one_or_none()
    picks = []
    if draft is not None:
        picks = (await db.execute(select(DraftPick).where(DraftPick.draft_id == draft.id)
                                  .order_by(DraftPick.pick_number))).scalars().all()
        pids.update(p.player_id for p in picks)

    players = {}
    if pids:
        players = {p.id: p for p in (await db.execute(select(Player).where(Player.id.in_(pids)))).scalars().all()}

    items: list[dict] = []
    for t in txs:
        d = t.details or {}
        if t.type == TransactionType.TRADE:
            target = d.get("target_team_id")
            involved = [t.team_id, target]
            offered, requested = d.get("offered_player_ids") or [], d.get("requested_player_ids") or []
            gave, got = _names(offered, players), _names(requested, players)
            if t.status == TransactionStatus.APPROVED:
                status, text = "done", f"{tname(t.team_id)} traded {gave} to {tname(target)} for {got}."
            elif t.status == TransactionStatus.PENDING:
                status, text = "pending", f"{tname(t.team_id)} offered {gave} to {tname(target)} for {got}."
            elif d.get("cancelled_by_proposer"):
                status, text = "declined", f"{tname(t.team_id)} withdrew an offer to {tname(target)}."
            else:
                status, text = "declined", f"{tname(target)} turned down {tname(t.team_id)}'s offer of {gave} for {got}."
            item = {"kind": "trade", "players": _player_refs(offered + requested, players)}
        else:
            add, drop = d.get("add_player_id"), d.get("drop_player_id")
            involved = [t.team_id]
            dropping = f", dropping {_names([drop], players)}" if drop else ""
            shown = [p for p in (add, drop) if p]
            if t.status == TransactionStatus.APPROVED:
                status, text = "done", f"{tname(t.team_id)} added {_names([add], players)}{dropping}."
            elif t.status == TransactionStatus.PENDING:
                status, text = "pending", f"{tname(t.team_id)} put in a claim for {_names([add], players)}{dropping}."
            elif d.get("voided") and drop:
                # Roster repair voided the add after the fact. The drop still happened.
                status, text, shown = "done", f"{tname(t.team_id)} dropped {_names([drop], players)}.", [drop]
            else:
                status, text = "declined", f"{tname(t.team_id)}'s claim for {_names([add], players)} didn't go through."
            item = {"kind": "claim", "players": _player_refs(shown, players)}

        if status != "done" and not (mine & set(involved)):
            continue
        if team_id and team_id not in involved:
            continue
        item.update({
            "id": t.id, "status": status, "at": _iso(t.processed_at), "week": None,
            "team_ids": [i for i in involved if i], "text": text,
            "cancel": ({"type": item["kind"], "id": t.id}
                       if status == "pending" and t.team_id in mine else None),
        })
        items.append(item)

    if draft is not None and picks:
        at = _iso(max((p.drafted_at for p in picks if p.drafted_at), default=None) or draft.updated_at)
        if team_id:
            own = [p.player_id for p in picks if p.team_id == team_id]
            if own:
                items.append({"id": f"draft-{draft.id}-{team_id}", "kind": "draft", "status": "done", "at": at,
                              "week": None, "team_ids": [team_id], "cancel": None,
                              "players": _player_refs(own[:1], players),
                              "text": f"{tname(team_id)} drafted {len(own)} players, starting with {_names(own[:1], players)}."})
        else:
            items.append({"id": f"draft-{draft.id}", "kind": "draft", "status": "done", "at": at, "week": None,
                          "team_ids": [], "cancel": None, "players": [],
                          "text": f"The draft finished with {len(picks)} picks."})

    results = await weekly_results(league, teams, db)
    ends = {}
    for y in {r["year"] for r in results}:
        ends[y] = {w: last for w, (_, last, _) in (await week_bounds(y, db)).items()}
    for r in results:
        a, b, sa, sb = r["team_a"], r["team_b"], r["score_a"], r["score_b"]
        if team_id and team_id not in (a, b):
            continue
        if sa == sb:
            text = f"{tname(a)} and {tname(b)} tied {sa:.2f} to {sb:.2f} in Week {r['week']}."
        else:
            (w, ws), (l, ls) = ((a, sa), (b, sb)) if sa > sb else ((b, sb), (a, sa))
            text = f"{tname(w)} beat {tname(l)} {ws:.2f} to {ls:.2f} in Week {r['week']}."
        items.append({"id": f"result-{r['year']}-{r['week']}-{a}-{b}", "kind": "result", "status": "done",
                      "at": _iso(ends.get(r["year"], {}).get(r["week"])), "week": r["week"],
                      "team_ids": [a, b], "cancel": None, "players": [], "text": text})

    epoch = datetime.min.replace(tzinfo=timezone.utc).isoformat()
    items.sort(key=lambda i: i["at"] or epoch, reverse=True)
    return items[:limit]
