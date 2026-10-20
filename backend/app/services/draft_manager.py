"""
Draft Manager — the core business logic for snake and mock drafts.
Handles draft creation, pick making, snake order generation, and mock AI picks.
"""
import asyncio
import copy
import json
import random
import math
import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, update, delete, func
from sqlalchemy.exc import IntegrityError
from app.models.draft import Draft, DraftPick, DraftRunStatus
from app.models.team import Team
from app.models.player import Player
from app.models.league import League, DraftStatus, LeagueType, DraftType
from app.models.draft_queue_entry import DraftQueueEntry
from app.models.draft_autopick import DraftAutopick
from app.services.sleeper_sync import sleeper_avatar_url, headline_stats as compute_headline_stats, effective_season_stats
from app.services.scoring_engine import calculate_player_score, DEFAULT_SCORING, DEFAULT_ROSTER_SLOTS
from app.models.contract import Contract
from app.services.salary_cap_service import DEFAULT_SALARY_CAP_SETTINGS, get_salary_cap_settings, compute_pick_slot_salary
from app.services import draft_board


# Positions the scoring engine (DEFAULT_SCORING) actually has point values
# for. The synced player pool also contains individual-defense/O-line
# positions (CB, DE, DT, OL, G, OT, T, OLB, C, SS, P, FS, LS, ILB, FB, NT,
# OG, S, ...) that this app cannot currently score at all -- those are
# excluded from the draft pool, not from general player browsing/search.
# DB/DL/LB (individual defensive players) added here -- they were synced
# from Sleeper and sitting in the database the whole time, but excluded
# from this set meant they never appeared as draftable at all (the
# available-players query below filters on membership in this set). The
# CPU draft AI's own position-priority dicts (get_ai_mock_pick) don't
# have entries for these three, so CPU teams still won't draft them --
# that's intentional for now, not an oversight: CPU_STARTER_SLOTS has no
# IDP slots to want yet (no league has any IDP roster-slot concept
# either), so there's nothing to safely give a CPU a reason to draft one.
# Humans can draft them manually.
FANTASY_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF", "DB", "DL", "LB"}

# (2026-09-09's per-draft _rank_cache lived here. Superseded on
# 2026-10-19 by draft_board.PlayerCatalog, which caches the whole board --
# ranks, points, display fields -- not just ranks. See draft_board.py.)

# Standard starting-lineup slots and realistic bench caps, used by
# get_ai_mock_pick's need scoring below. A human drafter reliably fills
# starters before taking depth, and rarely stockpiles many bench K/DEF/QB
# even in a long draft -- these give the CPU the same discipline instead
# of letting pure tier ranking stack three QBs by round 6 because a
# top-tier one happened to still be on the board.
CPU_STARTER_SLOTS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "DEF": 1}
CPU_POSITION_CAPS = {"QB": 3, "RB": 6, "WR": 7, "TE": 3, "K": 2, "DEF": 2}


def generate_snake_order(team_ids: list[str], total_rounds: int) -> list[str]:
    """
    Generate a snake draft order for all rounds.
    Returns a flat list where index = global pick number - 1.
    
    Example: teams [A,B,C] for 3 rounds
    Round 1: A, B, C
    Round 2: C, B, A
    Round 3: A, B, C
    Result: [A, B, C, C, B, A, A, B, C]
    """
    order = []
    forward = list(team_ids)
    for rnd in range(1, total_rounds + 1):
        if rnd % 2 == 1:
            order.extend(forward)
        else:
            order.extend(reversed(forward))
    return order


def get_drafting_team_at_pick(team_order: list[str], pick_number: int) -> str:
    """Get which team is drafting at a given global pick number."""
    if pick_number < 1 or pick_number > len(team_order):
        raise ValueError(f"Pick {pick_number} out of range (1-{len(team_order)})")
    return team_order[pick_number - 1]


async def create_draft(db: AsyncSession, league_id: str, total_rounds: int = 15) -> Draft:
    """Create a new draft for a league. Generates the snake order from league teams."""
    # Verify league exists
    result = await db.execute(select(League).where(League.id == league_id))
    league = result.scalar_one_or_none()
    if not league:
        raise ValueError("League not found")

    # A league should only ever have one real draft. This check alone is a
    # plain SELECT with no locking, so it doesn't close the window between
    # two concurrent callers -- both can pass it before either commits.
    # That's exactly how production ended up with 5 separate Draft rows for
    # the same 14 teams, one team's roster showing 27 players instead of 15
    # (team.roster accumulates picks by player ID across *every* Draft row
    # for that team, so duplicate drafts silently merge into one oversized
    # roster). This check stays as a fast, friendly pre-check for the
    # common case; Draft.__table_args__'s partial unique index
    # (uq_drafts_one_active_per_league) is what actually closes the race --
    # see the except block below for the case this check misses.
    existing = await db.execute(
        select(Draft).where(Draft.league_id == league_id, Draft.status != DraftRunStatus.COMPLETED)
    )
    if existing.scalars().first():
        raise ValueError("This league already has an active draft")

    # Get teams in the league
    result = await db.execute(
        select(Team).where(Team.league_id == league_id).order_by(Team.created_at)
    )
    teams = result.scalars().all()
    if len(teams) < 2:
        raise ValueError("Need at least 2 teams to draft")

    team_ids = [t.id for t in teams]
    random.shuffle(team_ids)  # Randomize initial order

    team_order = generate_snake_order(team_ids, total_rounds)

    draft = Draft(
        league_id=league_id,
        status=DraftRunStatus.PENDING,
        current_round=1,
        current_pick=1,
        total_rounds=total_rounds,
        team_order=json.dumps(team_order),
    )
    db.add(draft)
    try:
        await db.commit()
    except IntegrityError:
        # The pre-check above missed a concurrent creation for this same
        # league that committed first -- the partial unique index caught
        # it instead. Same user-facing error either way.
        await db.rollback()
        raise ValueError("This league already has an active draft")
    await db.refresh(draft)
    return draft


async def quickstart_mock_draft(
    db: AsyncSession,
    user_id: str,
    num_teams: int = 10,
    total_rounds: int = 15,
    draft_position: Optional[int] = None,
) -> tuple[Draft, str]:
    """No real league needed: auto-provisions a throwaway League
    (is_mock=True, excluded from list_leagues) with one team owned by
    user_id and (num_teams - 1) CPU teams, then creates and immediately
    starts a draft against it. Reuses the entire real draft engine and
    room -- create_draft, start_draft, and everything the draft page
    already does (including the existing Auto-Fill button, which skips
    whichever team you own) -- rather than a second, parallel
    implementation. See the standalone /mock-draft page on the frontend.

    Returns (draft, my_team_id) -- the caller (the API route) needs
    my_team_id to hand back to the frontend. This draft starts
    immediately (never sits PENDING), so the frontend's own "claim a
    team" screen -- which only ever shows for a PENDING draft -- never
    gets a chance to run here; without the caller getting my_team_id
    back explicitly, the frontend had no way to know which of the
    num_teams rows it should treat as the user's own.
    """
    if num_teams < 2 or num_teams > 20:
        raise ValueError("num_teams must be between 2 and 20")
    if total_rounds < 1 or total_rounds > 30:
        raise ValueError("total_rounds must be between 1 and 30")
    if draft_position is not None and not (1 <= draft_position <= num_teams):
        raise ValueError(f"draft_position must be between 1 and {num_teams}")

    # IDs generated up front (rather than relying on flush timing to
    # populate them) so every row can be constructed and added in one shot.
    league_id = str(uuid.uuid4())
    league = League(
        id=league_id,
        # %-d/%-I (no leading zero) are a Linux/Mac-only strftime extension --
        # not supported by Windows' C runtime, so this format needs to stick
        # to the portable directives even though prod itself runs on Linux.
        name=f"Mock Draft — {datetime.now(timezone.utc):%b %d, %I:%M %p}",
        commissioner_id=user_id,
        league_type=LeagueType.STANDARD,
        scoring_config=copy.deepcopy(DEFAULT_SCORING),  # deep copy -- see create_league for why
        roster_slots=copy.deepcopy(DEFAULT_ROSTER_SLOTS),
        max_teams=num_teams,
        draft_type=DraftType.SNAKE,
        co_commissioner_ids=[],
        is_mock=True,
    )
    db.add(league)

    my_team_id = str(uuid.uuid4())
    db.add(Team(id=my_team_id, name="Your Team", owner_id=user_id, league_id=league_id, roster=[]))

    cpu_team_ids = []
    for i in range(num_teams - 1):
        tid = str(uuid.uuid4())
        cpu_team_ids.append(tid)
        db.add(Team(id=tid, name=f"CPU Team {i + 1}", league_id=league_id, is_cpu=True, roster=[]))

    await db.commit()

    draft = await create_draft(db, league_id, total_rounds)

    if draft_position is not None:
        random.shuffle(cpu_team_ids)
        slot_order = cpu_team_ids[: draft_position - 1] + [my_team_id] + cpu_team_ids[draft_position - 1 :]
        draft.team_order = json.dumps(generate_snake_order(slot_order, total_rounds))
        await db.commit()
        await db.refresh(draft)

    draft = await start_draft(db, draft.id)
    return draft, my_team_id


async def start_draft(db: AsyncSession, draft_id: str) -> Draft:
    """Start a pending draft."""
    result = await db.execute(select(Draft).where(Draft.id == draft_id))
    draft = result.scalar_one_or_none()
    if not draft:
        raise ValueError("Draft not found")
    if draft.status != DraftRunStatus.PENDING:
        raise ValueError(f"Draft already {draft.status.value}")

    draft.status = DraftRunStatus.IN_PROGRESS
    draft.current_round = 1
    draft.current_pick = 1
    draft.current_pick_started_at = datetime.now(timezone.utc)

    # League.draft_status is a separate field from Draft.status -- the
    # league page reads league.draft_status to decide whether to show
    # "Start Draft" or "View Draft"/roster info, so it has to be kept in
    # sync here (and on completion in make_pick below), not just left at
    # its NOT_STARTED default forever.
    league_result = await db.execute(select(League).where(League.id == draft.league_id))
    league = league_result.scalar_one_or_none()
    if league:
        league.draft_status = DraftStatus.IN_PROGRESS

    await db.commit()
    await db.refresh(draft)
    return draft


async def make_pick(
    db: AsyncSession,
    draft_id: str,
    team_id: str,
    player_id: str,
    expected_pick_number: Optional[int] = None,
) -> DraftPick:
    """
    Make a draft pick. Verifies:
    - (optional) it's still pick `expected_pick_number` -- makes a retried
      or double-submitted request idempotent: it can never land on the
      NEXT pick, even when that's the same team's (snake turn)
    - Draft is in progress
    - It's the team's turn
    - Player hasn't been drafted yet
    - Player exists
    Advances the draft state.
    """
    # Row-level lock on the Draft row for this transaction: a real lock on
    # Postgres (production), a no-op on SQLite (local dev, which has no
    # per-row lock) -- see the compare-and-swap note below for why locking
    # alone isn't the actual correctness guarantee here.
    # populate_existing: always the locked row's CURRENT values, never a
    # stale copy already in this session's identity map (e.g. a loop that
    # read the draft before a concurrent pick landed).
    result = await db.execute(
        select(Draft).where(Draft.id == draft_id).with_for_update().execution_options(populate_existing=True)
    )
    draft = result.scalar_one_or_none()
    if not draft:
        raise ValueError("Draft not found")
    if draft.status != DraftRunStatus.IN_PROGRESS:
        raise ValueError("Draft is not in progress")
    if draft.is_paused:
        raise ValueError("Draft is paused by the commissioner")

    team_order = json.loads(draft.team_order)

    # Get number of teams
    result = await db.execute(select(Team).where(Team.league_id == draft.league_id))
    teams = result.scalars().all()
    num_teams = len(teams)

    observed_round = draft.current_round
    observed_pick = draft.current_pick

    # Calculate global pick index
    pick_index = (observed_round - 1) * num_teams + (observed_pick - 1)

    if pick_index >= len(team_order):
        raise ValueError("Draft is already complete")

    if expected_pick_number is not None and expected_pick_number != pick_index + 1:
        raise ValueError(f"Pick {expected_pick_number} has already been made.")

    expected_team_id = team_order[pick_index]
    if team_id != expected_team_id:
        raise ValueError(f"It's not your turn. Team {expected_team_id} is drafting.")

    # Check player not already drafted in this draft
    result = await db.execute(
        select(DraftPick).where(
            DraftPick.draft_id == draft_id,
            DraftPick.player_id == player_id,
        )
    )
    if result.scalar_one_or_none():
        raise ValueError("Player already drafted")

    # Check player exists
    result = await db.execute(select(Player).where(Player.id == player_id))
    player = result.scalar_one_or_none()
    if not player:
        raise ValueError("Player not found")

    round_num = observed_round
    global_pick_number = pick_index + 1

    # Salary-Cap (Phase 5): fetched unconditionally (previously the only
    # League fetch in this function was inside the `if is_complete:`
    # branch below) since a cap-enabled league needs its settings for
    # EVERY pick, not just the draft's last one.
    league_result = await db.execute(select(League).where(League.id == draft.league_id))
    league = league_result.scalar_one_or_none()
    cap_settings = get_salary_cap_settings(league) if league else DEFAULT_SALARY_CAP_SETTINGS
    cap_enabled = bool(league and cap_settings["enabled"])

    # Advance draft state
    if observed_pick >= num_teams:
        new_round, new_pick = observed_round + 1, 1
    else:
        new_round, new_pick = observed_round, observed_pick + 1
    is_complete = new_round > draft.total_rounds
    new_status = DraftRunStatus.COMPLETED if is_complete else DraftRunStatus.IN_PROGRESS
    new_timer_started_at = None if is_complete else datetime.now(timezone.utc)

    # Atomic, conditional advance -- only succeeds if the draft's state
    # still matches what was observed above (current_round/current_pick
    # unchanged since the read at the top of this function). If another
    # concurrent request already advanced it in the meantime -- e.g. a
    # human clicking while the mock-draft loop is also picking for the
    # current team, or a double-submitted click -- rowcount is 0 and this
    # request aborts instead of racing through to a duplicate pick.
    # Confirmed in production: the same pick_number recorded twice for one
    # team, once even with two different players. with_for_update() above
    # makes this the common (non-racing) path on Postgres by serializing
    # concurrent transactions; this WHERE-clause compare-and-swap is what
    # actually guarantees correctness, including on SQLite where the lock
    # is a no-op.
    advance_result = await db.execute(
        update(Draft)
        .where(
            Draft.id == draft_id,
            Draft.current_round == observed_round,
            Draft.current_pick == observed_pick,
        )
        .values(
            current_round=new_round,
            current_pick=new_pick,
            status=new_status,
            current_pick_started_at=new_timer_started_at,
        )
    )
    if advance_result.rowcount == 0:
        raise ValueError("It's not your turn. Someone else just picked.")

    draft_pick = DraftPick(
        draft_id=draft_id,
        league_id=draft.league_id,
        team_id=team_id,
        player_id=player_id,
        round=round_num,
        pick_number=global_pick_number,
    )
    db.add(draft_pick)

    # Keep League.draft_status in sync -- see start_draft for why.
    if is_complete and league:
        league.draft_status = DraftStatus.COMPLETED

    # Add player to team's roster. Salary-Cap (Phase 5): this write now
    # goes through the same roster_version CAS pattern trade approval/
    # waiver processing already use, added here for real (not just left
    # as an accepted gap) -- waivers/trades stay always-open even during
    # an active draft, so a concurrent waiver claim for a currently-
    # drafting team is a real race this Contract-row-plus-roster-append
    # write needs to be atomic against. A lost race raises ValueError,
    # which rolls back this whole transaction (including the turn-advance
    # CAS above, since db.commit() hasn't happened yet) -- so the picking
    # team's turn is left intact for a clean retry, nothing half-commits.
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if team:
        current_roster = list(team.roster or [])
        if player_id not in current_roster:
            if cap_enabled and len(current_roster) >= cap_settings["max_roster_size"]:
                raise ValueError(f"{team.name}'s roster is already at the {cap_settings['max_roster_size']}-player limit")
            new_roster = current_roster + [player_id]
            roster_cas = await db.execute(
                update(Team)
                .where(Team.id == team.id, Team.roster_version == team.roster_version)
                .values(roster=new_roster, roster_version=Team.roster_version + 1)
            )
            if roster_cas.rowcount == 0:
                raise ValueError("Your roster changed concurrently (e.g. a waiver claim was just processed) -- please retry the pick")
            if cap_enabled:
                # No cap_total check here, deliberately: a pick's salary
                # is 100% deterministic from (round, pick_number), not
                # from which player is chosen -- a team can't make its
                # draft cheaper by picking a different player for an
                # already-fixed-price slot. A team's total draft-day
                # salary obligation is fixed the moment the snake order
                # is generated, independent of any pick decision, so
                # there's nothing for a per-pick cap check to gate.
                salary = compute_pick_slot_salary(global_pick_number, num_teams * draft.total_rounds, cap_settings)
                db.add(Contract(
                    league_id=draft.league_id, team_id=team.id, player_id=player_id,
                    salary=salary, contract_years=cap_settings["default_contract_years"],
                    signed_year=datetime.now(timezone.utc).year, source="draft", is_active=True,
                ))

    # Drop this player from EVERY team's queue in this draft, not just the
    # picking team's own -- once drafted, they're unavailable to anyone,
    # so a stale queue entry on another team would otherwise sit there
    # forever (get_next_pick_for_team already skips drafted players when
    # reading the queue, but there's no reason to let the table grow
    # unbounded with dead rows). Same transaction as the pick itself.
    await db.execute(
        delete(DraftQueueEntry).where(
            DraftQueueEntry.draft_id == draft_id,
            DraftQueueEntry.player_id == player_id,
        )
    )

    await db.commit()
    await db.refresh(draft_pick)
    return draft_pick


def _season_points_fields(player: Player | None, scoring_config: dict) -> dict:
    """season_points + season_points_year for a (possibly None) player, via
    effective_season_stats -- shared by both the picks history and the
    available-players list below."""
    if not player:
        return {"season_points": None, "season_points_year": None}
    stats, year = effective_season_stats(player)
    return {
        "season_points": calculate_player_score(stats, scoring_config, player.position),
        "season_points_year": year,
    }


def _projected_points_field(player: Player | None, scoring_config: dict) -> dict:
    """projected_points: a simple, honestly-labeled 2026 estimate, not a
    real projections model -- this app has no external projections data
    source (same limitation the AI service's own bet-analysis docstring
    already admits for odds/weather, and the same "simple estimate from
    the best real number available" approach get_season_schedule already
    uses for future weeks). Assume repeat production absent any other
    information: last season's actual total, a legitimate baseline
    projection method on its own, not a placeholder pretending to be more
    than it is.

    Deliberately reads player.last_season_stats directly rather than
    going through effective_season_stats (season_points' source) -- once
    the real 2026 season starts and gets synced, effective_season_stats
    switches to live current-season data, which would make season_points
    and projected_points collapse into showing the exact same number all
    year. Keeping this pinned to last season's archived total instead
    means it stays a stable preseason baseline a user can compare their
    actual in-season pace against, which is the more useful thing "2025
    actual vs. 2026 projected" side by side is actually for."""
    if not player:
        return {"projected_points": None}
    stats = player.last_season_stats or {}
    return {"projected_points": calculate_player_score(stats, scoring_config, player.position)}


def _headline_and_raw_stats_fields(player: Player | None) -> dict:
    """headline_stats + stats for a (possibly None) player, via
    effective_season_stats -- same reasoning as _season_points_fields
    above: player.stats is this YEAR's live totals, empty until the season
    actually starts and gets synced. Using it directly (as this used to)
    meant every player in the draft pool showed a blank stats line for the
    entire pre-season -- this falls back to last season's archived totals
    instead, same source _season_points_fields already uses."""
    if not player:
        return {"headline_stats": {}, "stats": None}
    stats, _ = effective_season_stats(player)
    return {
        "headline_stats": compute_headline_stats(player.position, stats),
        "stats": stats,
    }


async def _load_state_inputs(db: AsyncSession, draft_id: str):
    """Everything /state depends on, via small queries only -- no Player
    rows (those come from the cached catalog, see draft_board.py)."""
    result = await db.execute(select(Draft).where(Draft.id == draft_id))
    draft = result.scalar_one_or_none()
    if not draft:
        raise ValueError("Draft not found")
    league_result = await db.execute(select(League).where(League.id == draft.league_id))
    league = league_result.scalar_one_or_none()
    result = await db.execute(select(Team).where(Team.league_id == draft.league_id))
    teams = list(result.scalars().all())
    result = await db.execute(
        select(DraftPick.id, DraftPick.round, DraftPick.pick_number, DraftPick.team_id, DraftPick.player_id)
        .where(DraftPick.draft_id == draft_id)
        .order_by(DraftPick.pick_number)
    )
    picks = [tuple(r) for r in result.all()]
    return draft, league, teams, picks


def _started_at_iso(draft: Draft) -> Optional[str]:
    started = draft.current_pick_started_at
    if not started:
        return None
    return started.isoformat() if started.tzinfo else started.isoformat() + "+00:00"


def _state_key(draft: Draft, league: Optional[League], teams: list, picks: list, catalog) -> tuple:
    teams_sig = tuple(sorted((t.id, t.name, t.owner_id, t.co_owner_id, t.partner_team_id) for t in teams))
    return (
        draft.id, draft.status.value, draft.current_round, draft.current_pick, bool(draft.is_paused),
        draft.timer_seconds, _started_at_iso(draft), draft.total_rounds, draft.draft_type, draft.team_order,
        len(picks), picks[-1][0] if picks else None, teams_sig,
        bool(league.is_mock) if league else False,
        draft_board.catalog_token(catalog),
    )


async def _build_state(db: AsyncSession, draft: Draft, league: Optional[League], teams: list, picks: list, catalog) -> dict:
    team_order = json.loads(draft.team_order)
    num_teams = len(teams)
    pick_index = (draft.current_round - 1) * num_teams + (draft.current_pick - 1)
    current_team_id = team_order[pick_index] if pick_index < len(team_order) else None

    drafted_ids = {p[4] for p in picks}

    # Available players: the pre-sorted catalog minus anyone drafted, with
    # pos_rank (RB1, RB2, ...) counted among what's still on the board --
    # identical ordering and fields to the old per-poll rebuild, minus the
    # raw `stats` blob (never read by the draft room; ~70% of the payload).
    available: list[dict] = []
    pos_counts: dict[str, int] = {}
    for entry in catalog.entries:
        if entry["id"] in drafted_ids:
            continue
        n = pos_counts.get(entry["position"], 0) + 1
        pos_counts[entry["position"]] = n
        available.append(draft_board.public_entry(entry, n))

    # Drafted players outside the catalog (e.g. a position no longer
    # draftable) -- rare; fetched directly.
    missing = [p[4] for p in picks if p[4] not in catalog.index]
    missing_players: dict[str, Player] = {}
    if missing:
        result = await db.execute(select(Player).where(Player.id.in_(missing)))
        missing_players = {pl.id: pl for pl in result.scalars().all()}
    scoring_config = (league.scoring_config or {}) if league else {}

    teams_by_id = {t.id: t for t in teams}
    picks_with_players = []
    for pick_id, rnd, pick_number, team_id, player_id in picks:
        if player_id in catalog.index:
            player_view = draft_board.pick_player_view(catalog.entries[catalog.index[player_id]])
        else:
            player = missing_players.get(player_id)
            player_view = {
                "id": player.id if player else None,
                "full_name": f"{player.first_name} {player.last_name}" if player else "Unknown",
                "position": player.position if player else "N/A",
                "team": player.team if player else "FA",
                "number": player.number if player else None,
                "age": player.age if player else None,
                "bye_week": player.bye_week if player else None,
                "injury_status": player.injury_status if player else None,
                "fantasy_positions": player.fantasy_positions if player else None,
                "avatar_url": sleeper_avatar_url(player.sleeper_id) if player else None,
                "rank_score": len(catalog.rank_by_id) + 1 if player else 0,
                "pos_rank": 0,
                "headline_stats": _headline_and_raw_stats_fields(player)["headline_stats"],
                **_season_points_fields(player, scoring_config),
            }
        team = teams_by_id.get(team_id)
        picks_with_players.append({
            "id": pick_id,
            "round": rnd,
            "pick_number": pick_number,
            "player": player_view,
            "team": {"id": team.id if team else None, "name": team.name if team else "Unknown"},
        })

    return {
        "draft": {
            "id": draft.id,
            "league_id": draft.league_id,
            "status": draft.status.value,
            "draft_type": draft.draft_type,
            "current_round": draft.current_round,
            "current_pick": draft.current_pick,
            "total_rounds": draft.total_rounds,
            "num_teams": num_teams,
            "total_picks": num_teams * draft.total_rounds,
            "timer_seconds": draft.timer_seconds,
            "is_paused": bool(draft.is_paused),
            "current_pick_started_at": _started_at_iso(draft),
        },
        "picks": picks_with_players,
        "current_team_id": current_team_id,
        "current_team_name": teams_by_id[current_team_id].name if current_team_id in teams_by_id else None,
        # owner_id/co_owner_id included so the draft room can show a
        # 2-Man team's whose-turn-within-the-team indicator -- either
        # owner already can submit a pick for this team_id (see
        # require_team_or_league_access), this is purely a display
        # signal, not new authorization.
        "teams": {t.id: {"name": t.name, "owner_id": t.owner_id, "co_owner_id": t.co_owner_id, "partner_team_id": t.partner_team_id} for t in teams},
        "team_order": team_order,
        "claimed_teams": {t.id: t.owner_id for t in teams if t.owner_id is not None},
        "available_players": available,
        "is_mock": league.is_mock if league else False,
    }


async def get_draft_state(db: AsyncSession, draft_id: str) -> dict:
    """Get full draft state including all picks and current team.

    Player data comes from the cached PlayerCatalog (draft_board.py) --
    see that module's docstring for the 2026-10-19 incident this fixes.
    The HTTP route uses get_draft_state_encoded instead, which also
    caches the encoded body across viewers."""
    draft, league, teams, picks = await _load_state_inputs(db, draft_id)
    scoring_config = (league.scoring_config or {}) if league else {}
    catalog = await draft_board.get_catalog(db, scoring_config, FANTASY_POSITIONS)
    return await _build_state(db, draft, league, teams, picks, catalog)


async def get_draft_state_encoded(db: AsyncSession, draft_id: str) -> "draft_board.EncodedState":
    """get_draft_state, built at most once per state change per process and
    shared by every viewer (single-flight per draft). Releases the DB
    connection before waiting on another request's build, so a burst of
    polls can't drain the pool the way it did on 2026-10-19."""
    draft, league, teams, picks = await _load_state_inputs(db, draft_id)
    scoring_config = (league.scoring_config or {}) if league else {}
    catalog = await draft_board.get_catalog(db, scoring_config, FANTASY_POSITIONS)
    key = _state_key(draft, league, teams, picks, catalog)
    hit = draft_board.cached_state(draft_id, key)
    if hit:
        return hit
    missing_needed = any(p[4] not in catalog.index for p in picks)
    if not missing_needed:
        # Nothing left to read -- give the connection back before queueing
        # behind another request's build. Expunge first: a rollback would
        # otherwise expire the already-loaded rows we still use below.
        db.expunge_all()
        await db.rollback()
    async with draft_board.state_lock(draft_id):
        hit = draft_board.cached_state(draft_id, key)
        if hit:
            return hit
        state = await _build_state(db, draft, league, teams, picks, catalog)
        return await draft_board.store_state(draft_id, key, state)


IDP_POSITIONS = {"DB", "DL", "LB"}


# Sleeper's own sentinel for "not really ranked" (an inactive/irrelevant
# player still carries a search_rank field, but set to something like
# 9999999 -- several orders of magnitude past any real rank, confirmed
# directly against the live API). Treated the same as no search_rank at
# all (None): falls through to the production-based fallback below
# rather than being trusted as a real ADP-style signal.
_SEARCH_RANK_SENTINEL = 500_000


def build_rank_by_id(players, scoring_config: dict) -> dict[str, int]:
    """Real, current-season overall rank (1 = best) for every given
    player, across ALL positions -- replaces the old hand-maintained
    static ~194-name tier list (get_tier_names, removed) that read like a
    2024-offseason snapshot (zero 2025-draft-class players, still-elevated
    declining veterans, an unranked fallback of 1000 -- worse than every
    listed player).

    Primary signal: Player.search_rank -- Sleeper's own overall
    fantasy-relevance rank, synced from the SAME /players/nfl payload
    sync_players_to_db already fetches (previously fetched and discarded).
    This is a real, live, year-round ADP-style number that reflects THIS
    season's expectations, not last year's box score -- confirmed directly
    against the real API before wiring this up (e.g. Bijan Robinson=1,
    Ashton Jeanty [2025 rookie]=12, Aaron Rodgers [declining vet]=196), and
    critically it's populated even during the preseason, unlike Sleeper's
    weekly projections endpoint (empty until the regular season actually
    starts publishing them).

    Fallback, for anyone with no usable search_rank at all -- confirmed:
    team DEF entries never carry one, and some deep-roster IDP players
    don't either: real last-season production (effective_season_stats +
    calculate_player_score -- the same pipeline season_points and the
    original version of this function used), best first, placed strictly
    AFTER every search_rank-ranked player so a real ADP-informed rank
    always outranks a fallback one. players only needs .id/.position/
    .search_rank/.stats/.stats_year/.last_season_stats/.last_season_year --
    real Player rows or anything duck-typed the same way."""
    with_rank: list = []
    without_rank: list = []
    for p in players:
        if p.search_rank is not None and p.search_rank < _SEARCH_RANK_SENTINEL:
            with_rank.append(p)
        else:
            without_rank.append(p)

    with_rank.sort(key=lambda p: p.search_rank)
    rank_by_id: dict[str, int] = {p.id: i + 1 for i, p in enumerate(with_rank)}

    scored = [
        (p.id, calculate_player_score(effective_season_stats(p)[0], scoring_config, p.position))
        for p in without_rank
    ]
    scored.sort(key=lambda ps: -ps[1])
    offset = len(with_rank)
    for i, (pid, _) in enumerate(scored):
        rank_by_id[pid] = offset + i + 1

    return rank_by_id


def get_rank_score(player, rank_by_id: dict[str, int]) -> int:
    """rank_score for a player: their computed data-driven rank
    (build_rank_by_id) if they were part of the pool it was built over,
    else a fallback rank worse than everyone actually ranked (e.g. a
    drafted/historic player display that happens to fall outside
    whatever pool this particular call ranked)."""
    return rank_by_id.get(player.id, len(rank_by_id) + 1)


def get_percentile_tier(rank: int, total: int) -> int:
    """Percentile-bucket tier (1 = elite ... 5 = deep bench/unranked),
    the data-driven replacement for the old static tier1-4 (+5 unranked)
    name list get_ai_mock_pick used for its tier_score. Computed from
    build_rank_by_id's real rank instead of a second, separately-stale
    static list -- same 1-5 scale get_ai_mock_pick already expects.
    Top 5% = tier 1, next 15% = tier 2, next 30% = tier 3, next 30% =
    tier 4, remaining 20% = tier 5."""
    if total <= 0:
        return 5
    pct = rank / total
    if pct <= 0.05:
        return 1
    elif pct <= 0.20:
        return 2
    elif pct <= 0.50:
        return 3
    elif pct <= 0.80:
        return 4
    return 5


async def get_team_queue(db: AsyncSession, draft_id: str, team_id: str) -> list[DraftQueueEntry]:
    """A team's queue, in pick order (position ascending). Includes
    entries for players who may have since been drafted by someone else
    -- callers that need "still available" should cross-check against
    current picks themselves (see get_next_pick_for_team), same as the
    frontend already does for its own local queue state."""
    result = await db.execute(
        select(DraftQueueEntry)
        .where(DraftQueueEntry.draft_id == draft_id, DraftQueueEntry.team_id == team_id)
        .order_by(DraftQueueEntry.position)
    )
    return list(result.scalars().all())


async def add_to_queue(db: AsyncSession, draft_id: str, team_id: str, player_id: str) -> None:
    """Append a player to the end of a team's queue. No-ops (doesn't
    raise) if already queued -- toggling a player that's already in the
    queue is a client bug, not a real conflict worth a 400 for."""
    existing = await db.execute(
        select(DraftQueueEntry).where(
            DraftQueueEntry.draft_id == draft_id,
            DraftQueueEntry.team_id == team_id,
            DraftQueueEntry.player_id == player_id,
        )
    )
    if existing.scalar_one_or_none():
        return
    max_position = await db.scalar(
        select(func.max(DraftQueueEntry.position)).where(
            DraftQueueEntry.draft_id == draft_id, DraftQueueEntry.team_id == team_id
        )
    )
    db.add(DraftQueueEntry(
        draft_id=draft_id, team_id=team_id, player_id=player_id,
        position=(max_position + 1) if max_position is not None else 0,
    ))
    await db.commit()


async def remove_from_queue(db: AsyncSession, draft_id: str, team_id: str, player_id: str) -> None:
    """Remove one player from a team's queue. Leaves the remaining
    entries' `position` values as-is (gaps are fine -- get_team_queue
    only ever needs relative order, never contiguous integers)."""
    await db.execute(
        delete(DraftQueueEntry).where(
            DraftQueueEntry.draft_id == draft_id,
            DraftQueueEntry.team_id == team_id,
            DraftQueueEntry.player_id == player_id,
        )
    )
    await db.commit()


async def get_next_pick_for_team(
    db: AsyncSession,
    draft_id: str,
    team_id: str,
    current_round: Optional[int] = None,
    total_rounds: Optional[int] = None,
    available_players: Optional[list[Player]] = None,
) -> Optional[Player]:
    """Server-authoritative "what should this team pick right now" --
    the single function both the manual /auto-pick endpoint and the
    timer-expiry watchdog (scheduler.py) call, so the two paths can never
    disagree. Checks the team's persisted queue FIRST, in order, skipping
    anyone already drafted (by this team or anyone else) -- only falls
    back to the AI ranking (get_ai_mock_pick) once the queue is empty or
    fully exhausted. This is what makes "auto-pick takes from the queue"
    true unconditionally, not just when the owning client's own browser
    tab happens to be open and running its own client-side queue check."""
    queue = await get_team_queue(db, draft_id, team_id)
    if queue:
        drafted_result = await db.execute(select(DraftPick.player_id).where(DraftPick.draft_id == draft_id))
        drafted_ids = {row[0] for row in drafted_result.all()}
        for entry in queue:
            if entry.player_id in drafted_ids:
                continue
            player_result = await db.execute(select(Player).where(Player.id == entry.player_id))
            player = player_result.scalar_one_or_none()
            if player:
                return player
    return await get_ai_mock_pick(
        db, draft_id, team_id,
        current_round=current_round, total_rounds=total_rounds, available_players=available_players,
    )


def _cpu_pos_rank(current_round: int) -> dict[str, int]:
    """Position priority by round (lower = better)."""
    if current_round <= 2:
        # Early: elite RBs, WRs, top QBs
        return {"RB": 0, "WR": 1, "TE": 2, "QB": 3, "DEF": 10, "K": 10}
    elif current_round <= 5:
        return {"RB": 0, "WR": 0, "QB": 1, "TE": 2, "DEF": 10, "K": 10}
    elif current_round <= 8:
        return {"RB": 0, "WR": 0, "TE": 1, "QB": 1, "DEF": 8, "K": 10}
    elif current_round <= 12:
        return {"RB": 0, "WR": 0, "TE": 0, "QB": 0, "DEF": 5, "K": 8}
    return {"RB": 0, "WR": 0, "TE": 0, "QB": 0, "DEF": 0, "K": 0}


def _choose_cpu_candidate(
    candidates: list[tuple],
    total_ranked: int,
    team_positions: dict[str, int],
    current_round: int,
    total_rounds: int,
):
    """The CPU drafting brain, over lightweight records:
    (key, position, raw_team, age, rank) where rank is 1-based among the
    AVAILABLE pool. Returns the chosen record's key, or None.

    Scoring (lower = better):
    - tier_score: continuous rank across 0-400 (2026-09-09 fix -- the old
      discrete 5-tier buckets made a #50 and a #490 player tie, which is
      why Auto-Fill picked "random, not even good" players).
    - pos_bonus: position priority by round (_cpu_pos_rank) * 10.
    - need_penalty: none while still short a starter at the position;
      escalating past starters; +300 at the realistic cap
      (CPU_POSITION_CAPS). Endgame override: once picks left <= unfilled
      starter slots, -1000 for those positions so a team always ends up
      with a K/DEF (0 kickers were drafted across 36 sampled CPU teams
      before this rule).
    - small free-agent and age adjustments.
    Then a little realistic randomness among close contenders (within 40
    points of the best on the 0-400 scale)."""
    pos_rank = _cpu_pos_rank(current_round)
    rounds_left = total_rounds - current_round + 1
    unfilled_starters = {p for p, need in CPU_STARTER_SLOTS.items() if team_positions.get(p, 0) < need}
    must_fill_now = len(unfilled_starters) >= rounds_left

    scored = []
    denom = max(total_ranked - 1, 1)
    for key, pos, raw_team, age, rank in candidates:
        if pos not in pos_rank:
            continue
        tier_score = ((rank - 1) / denom) * 400
        pos_bonus = pos_rank.get(pos, 99) * 10
        have = team_positions.get(pos, 0)
        starter_need = CPU_STARTER_SLOTS.get(pos, 0)
        if have < starter_need:
            need_penalty = 0
        else:
            need_penalty = 20 * (have - starter_need + 1)
            if have >= CPU_POSITION_CAPS.get(pos, 99):
                need_penalty += 300
        if must_fill_now and pos in unfilled_starters:
            need_penalty -= 1000
        fa_penalty = 30 if (not raw_team or raw_team in ("FA", "---")) else 0
        age = age or 25
        age_score = -5 if 24 <= age <= 28 else (20 if age > 35 else 0)
        scored.append((tier_score + pos_bonus + need_penalty + fa_penalty + age_score, key))

    if not scored:
        return None
    scored.sort(key=lambda x: x[0])
    best_score = scored[0][0]
    top_tier_count = 3 if current_round <= 5 else 5
    top_tier = [k for sc, k in scored if sc <= best_score + 40]
    candidates_out = top_tier[:max(top_tier_count * 2, 6)]
    return random.choice(candidates_out)


async def _team_position_counts(db: AsyncSession, draft_id: str, team_id: str) -> dict[str, int]:
    result = await db.execute(
        select(Player.position)
        .join(DraftPick, DraftPick.player_id == Player.id)
        .where(DraftPick.draft_id == draft_id, DraftPick.team_id == team_id)
    )
    counts: dict[str, int] = {}
    for (pos,) in result.all():
        counts[pos] = counts.get(pos, 0) + 1
    return counts


async def get_ai_mock_pick(
    db: AsyncSession,
    draft_id: str,
    team_id: str,
    current_round: Optional[int] = None,
    total_rounds: Optional[int] = None,
    available_players: Optional[list[Player]] = None,
) -> Optional[Player]:
    """CPU draft pick: rank-based tiers, position priority by round, and
    roster needs (see _choose_cpu_candidate).

    available_players: optional explicit pool of Player rows (ranked among
    themselves, as before). Omitted -- the watchdog/auto-pick/mock paths --
    it uses the cached PlayerCatalog under DEFAULT_SCORING instead of
    loading and ranking the whole undrafted pool on every pick (~1 s per
    pick on a prod-sized pool, the CPU-pick half of the 2026-10-19
    slowdown). Standard DEFAULT_SCORING either way: a CPU-pick relative
    ranking signal, not any one league's custom rules.
    """
    if current_round is None or total_rounds is None:
        result = await db.execute(select(Draft).where(Draft.id == draft_id))
        draft = result.scalar_one_or_none()
        if not draft:
            return None
        current_round = draft.current_round
        total_rounds = draft.total_rounds

    team_positions = await _team_position_counts(db, draft_id, team_id)

    if available_players is not None:
        rank_by_id = build_rank_by_id(available_players, DEFAULT_SCORING)
        by_id = {p.id: p for p in available_players}
        candidates = [
            (p.id, p.position, p.team, p.age, get_rank_score(p, rank_by_id)) for p in available_players
        ]
        chosen = _choose_cpu_candidate(candidates, len(rank_by_id), team_positions, current_round, total_rounds)
        return by_id.get(chosen) if chosen else None

    catalog = await draft_board.get_catalog(db, DEFAULT_SCORING, FANTASY_POSITIONS)
    drafted_result = await db.execute(select(DraftPick.player_id).where(DraftPick.draft_id == draft_id))
    drafted_ids = {row[0] for row in drafted_result.all()}
    # cpu_records are already in DEFAULT_SCORING rank order, so position in
    # the filtered list IS the rank among available players -- the same
    # number build_rank_by_id(available) used to produce.
    candidates = []
    for rec in catalog.cpu_records:
        if rec[0] in drafted_ids:
            continue
        candidates.append((rec[0], rec[1], rec[2], rec[3], len(candidates) + 1))
    chosen = _choose_cpu_candidate(candidates, len(candidates), team_positions, current_round, total_rounds)
    if not chosen:
        return None
    return await db.get(Player, chosen)


def current_pick_slot(draft: Draft, num_teams: int) -> tuple[int, Optional[str]]:
    """(1-based global pick number, team on the clock or None) -- the same
    formula make_pick uses."""
    order = json.loads(draft.team_order or "[]")
    idx = (draft.current_round - 1) * num_teams + (draft.current_pick - 1)
    team_id = order[idx] if 0 <= idx < len(order) else None
    return idx + 1, team_id


async def _num_teams(db: AsyncSession, league_id: str) -> int:
    return int(await db.scalar(select(func.count(Team.id)).where(Team.league_id == league_id)) or 0)


async def get_autopick(db: AsyncSession, draft_id: str, team_id: str) -> bool:
    row = await db.execute(
        select(DraftAutopick.enabled).where(DraftAutopick.draft_id == draft_id, DraftAutopick.team_id == team_id)
    )
    value = row.scalar_one_or_none()
    return bool(value)


async def set_autopick(db: AsyncSession, draft_id: str, team_id: str, enabled: bool, user_id: Optional[str]) -> bool:
    result = await db.execute(
        select(DraftAutopick).where(DraftAutopick.draft_id == draft_id, DraftAutopick.team_id == team_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        db.add(DraftAutopick(draft_id=draft_id, team_id=team_id, enabled=enabled, updated_by=user_id))
    else:
        row.enabled = enabled
        row.updated_by = user_id
        row.updated_at = datetime.now(timezone.utc)
    try:
        await db.commit()
    except IntegrityError:
        # Concurrent first toggle for the same team -- the other insert won; apply ours on top.
        await db.rollback()
        await db.execute(
            update(DraftAutopick)
            .where(DraftAutopick.draft_id == draft_id, DraftAutopick.team_id == team_id)
            .values(enabled=enabled, updated_by=user_id, updated_at=datetime.now(timezone.utc))
        )
        await db.commit()
    return enabled


async def advance_draft_if_due(db: AsyncSession, draft_id: str, now: Optional[datetime] = None) -> Optional[DraftPick]:
    """Server-authoritative clock: make the current pick if it's due, else
    do nothing. Called every second by the draft watchdog (scheduler.py)
    whether or not any browser is open, and reads everything from the DB
    each time -- so it survives restarts (an expired clock found after a
    redeploy is picked on the first tick) and needs no in-memory state.

    Due when:
      - a CPU (or ownerless) team, or a human team with autopick ON
        (draft_autopick, server-persisted), has been on the clock for
        settings.CPU_PICK_DELAY_S; or
      - a human team's pick clock (timer_seconds > 0) has run out -- with
        autopick OFF too. The toggle only decides whether to wait for the
        clock; it never lets the draft stall (QA 2026-10-19, pick 18).
    Paused drafts never advance.

    Double-pick safety: make_pick takes a row lock on the draft (Postgres
    FOR UPDATE), compare-and-swaps current_round/current_pick, and is
    pinned to this exact pick number (expected_pick_number). Two workers
    (e.g. old + new container during a deploy) or a human click racing the
    watchdog: exactly one wins, the rest get ValueError and change nothing.
    """
    from app.core.config import settings

    draft = (await db.execute(select(Draft).where(Draft.id == draft_id))).scalar_one_or_none()
    if (
        not draft
        or draft.status != DraftRunStatus.IN_PROGRESS
        or draft.is_paused
        or not draft.current_pick_started_at
    ):
        return None
    now = now or datetime.now(timezone.utc)
    started_at = draft.current_pick_started_at
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    elapsed = (now - started_at).total_seconds()
    if elapsed < settings.CPU_PICK_DELAY_S:
        return None

    num_teams = await _num_teams(db, draft.league_id)
    if num_teams == 0:
        return None
    pick_number, team_id = current_pick_slot(draft, num_teams)
    if not team_id:
        return None
    team = await db.get(Team, team_id)
    if team is None:
        return None
    is_cpu_turn = team.is_cpu or not team.owner_id
    timer_expired = draft.timer_seconds > 0 and elapsed >= draft.timer_seconds
    if not (is_cpu_turn or timer_expired or await get_autopick(db, draft_id, team_id)):
        return None

    current_round, total_rounds = draft.current_round, draft.total_rounds
    player = await get_next_pick_for_team(db, draft_id, team_id, current_round=current_round, total_rounds=total_rounds)
    if not player:
        return None
    return await make_pick(db, draft_id, team_id, player.id, expected_pick_number=pick_number)


async def run_mock_draft(
    db: AsyncSession,
    draft_id: str,
    skip_team_ids: list[str] | None = None,
) -> list[DraftPick]:
    """Fill picks with CPU choices until a skipped (human) team is on the
    clock, the draft is paused, or it completes. Powers "Sim to My Pick"
    (skip = the user's teams) and "Auto-Pick All" (no skip).

    Re-reads the draft row before every pick and pins each make_pick to
    that pick number, so it coexists with the watchdog picking at the same
    time: a lost race just re-syncs and carries on, instead of the old
    local-mirror loop aborting with a 400 ("Someone else just picked") on
    the first collision -- which is what made Auto-Pick All look like it
    did nothing. Yields to the event loop between picks."""
    skip_set = set(skip_team_ids or [])

    draft = (await db.execute(select(Draft).where(Draft.id == draft_id))).scalar_one_or_none()
    if not draft:
        raise ValueError("Draft not found")
    if draft.status == DraftRunStatus.PENDING:
        await start_draft(db, draft_id)

    num_teams = await _num_teams(db, draft.league_id)
    max_picks = len(json.loads(draft.team_order or "[]"))
    all_picks: list[DraftPick] = []
    lost_races = 0
    while len(all_picks) + lost_races <= max_picks:
        draft = (
            await db.execute(select(Draft).where(Draft.id == draft_id).execution_options(populate_existing=True))
        ).scalar_one()
        if draft.status != DraftRunStatus.IN_PROGRESS or draft.is_paused:
            break
        pick_number, team_id = current_pick_slot(draft, num_teams)
        if not team_id or team_id in skip_set:
            break
        player = await get_ai_mock_pick(
            db, draft_id, team_id, current_round=draft.current_round, total_rounds=draft.total_rounds,
        )
        if not player:
            break
        try:
            pick = await make_pick(db, draft_id, team_id, player.id, expected_pick_number=pick_number)
        except ValueError:
            await db.rollback()
            lost_races += 1
            if lost_races > 10:
                break
            continue
        all_picks.append(pick)
        await asyncio.sleep(0)
    return all_picks
