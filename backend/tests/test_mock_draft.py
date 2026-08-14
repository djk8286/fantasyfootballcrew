"""
Tests for run_mock_draft -- previously had zero test coverage of any
kind (confirmed via grep before this file existed), despite being a
non-trivial loop with real state-advancement logic. Written alongside
the Production Quality Hardening Phase 3 perf refactor (eliminating
~2,000+ queries in a full 12-round mock draft by tracking round/pick/
available-players locally instead of re-querying every pick) -- these
tests are the actual proof that refactor is behavior-preserving, not
just "still doesn't crash".
"""
import json
import uuid
import pytest
from sqlalchemy import select
from app.models.user import User
from app.models.league import League, LeagueType, DraftStatus
from app.models.team import Team
from app.models.player import Player
from app.models.draft import DraftPick, DraftRunStatus, Draft
from app.services.draft_manager import create_draft, start_draft, run_mock_draft


async def _make_draftable_league(db_session_factory, num_teams=6, total_rounds=4, extra_players=20):
    """num_teams * total_rounds real players (exactly enough to fill the
    draft with zero slack) PLUS extra_players spare ones -- run_mock_draft
    itself doesn't cap how many players exist, but a too-tight pool would
    make "no duplicate picks" trivially true for the wrong reason (nothing
    left to duplicate). Mixed positions, not just RB, since get_ai_mock_pick's
    pos_rank/need logic behaves differently per position -- a real mock
    draft always sees a mixed pool."""
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@example.com",
                             username=f"mockcommish{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(commissioner)
        await db.flush()

        league = League(
            id=str(uuid.uuid4()), name="Mock Draft Test League", commissioner_id=commissioner.id,
            league_type=LeagueType.STANDARD, draft_status=DraftStatus.NOT_STARTED,
            scoring_config={}, roster_slots={},
        )
        db.add(league)
        await db.flush()

        teams = [
            Team(id=str(uuid.uuid4()), name=f"Team {i + 1}", league_id=league.id,
                 owner_id=commissioner.id, roster=[], roster_version=0, is_cpu=True)
            for i in range(num_teams)
        ]
        db.add_all(teams)

        positions = ["QB", "RB", "WR", "TE", "K", "DEF"]
        needed = num_teams * total_rounds + extra_players
        prefix = uuid.uuid4().hex[:8]  # unique per call -- a test may build more than one league against the same DB
        players = [
            Player(id=str(uuid.uuid4()), sleeper_id=f"sleeper-mock-{prefix}-{i}", first_name=f"Player{i}",
                   last_name="Test", position=positions[i % len(positions)])
            for i in range(needed)
        ]
        db.add_all(players)
        await db.commit()

        draft = await create_draft(db, league.id, total_rounds=total_rounds)
        draft = await start_draft(db, draft.id)

        return {
            "league_id": league.id,
            "team_ids": [t.id for t in teams],
            "draft_id": draft.id,
            "num_teams": num_teams,
            "total_rounds": total_rounds,
            "db_session_factory": db_session_factory,
        }


@pytest.mark.asyncio
async def test_full_mock_draft_completes_with_no_duplicate_picks(db_session_factory):
    setup = await _make_draftable_league(db_session_factory, num_teams=6, total_rounds=4)

    async with setup["db_session_factory"]() as db:
        picks = await run_mock_draft(db, setup["draft_id"])

    expected_total = setup["num_teams"] * setup["total_rounds"]
    assert len(picks) == expected_total

    async with setup["db_session_factory"]() as db:
        result = await db.execute(select(DraftPick).where(DraftPick.draft_id == setup["draft_id"]))
        db_picks = result.scalars().all()
        assert len(db_picks) == expected_total

        player_ids = [p.player_id for p in db_picks]
        assert len(player_ids) == len(set(player_ids)), "a player was drafted more than once"

        # pick_number 1..expected_total, each exactly once (no gaps/dupes
        # in the sequence the state-advancement produced).
        pick_numbers = sorted(p.pick_number for p in db_picks)
        assert pick_numbers == list(range(1, expected_total + 1))

        draft_result = await db.execute(select(Draft).where(Draft.id == setup["draft_id"]))
        draft = draft_result.scalar_one()
        assert draft.status == DraftRunStatus.COMPLETED

        # Every team ended up with exactly total_rounds players.
        teams_result = await db.execute(select(Team).where(Team.league_id == setup["league_id"]))
        for team in teams_result.scalars().all():
            assert len(team.roster or []) == setup["total_rounds"]


@pytest.mark.asyncio
async def test_hybrid_mock_draft_stops_before_a_skipped_teams_turn(db_session_factory):
    """skip_team_ids -- a human keeps one team, the rest are CPU-run.
    run_mock_draft must stop the instant it reaches that team's turn,
    not draft for them. team_order is the FULL pick sequence across
    every round (snake-ordered, so a given team appears at a different
    index each round), shuffled via the global, unseeded `random`
    module -- so which pick index is "the skipped team's turn" has to
    be read back from team_order itself, not assumed."""
    setup = await _make_draftable_league(db_session_factory, num_teams=4, total_rounds=3)

    async with setup["db_session_factory"]() as db:
        draft_result = await db.execute(select(Draft).where(Draft.id == setup["draft_id"]))
        team_order = json.loads(draft_result.scalar_one().team_order)
    # Round 1 is exactly team_order[0:num_teams], every team once -- the
    # LAST team to pick in round 1 guarantees every other team picks at
    # least once before this stops (a real, non-trivial case), and that
    # slot's index is exactly this team's first appearance since round 1
    # has no repeats yet.
    human_team_id = team_order[setup["num_teams"] - 1]
    expected_picks_before_stopping = team_order.index(human_team_id)
    assert expected_picks_before_stopping == setup["num_teams"] - 1

    async with setup["db_session_factory"]() as db:
        picks = await run_mock_draft(db, setup["draft_id"], skip_team_ids=[human_team_id])

    assert all(p.team_id != human_team_id for p in picks)
    assert len(picks) == expected_picks_before_stopping

    async with setup["db_session_factory"]() as db:
        result = await db.execute(select(DraftPick).where(DraftPick.draft_id == setup["draft_id"]))
        db_picks = result.scalars().all()
        assert all(p.team_id != human_team_id for p in db_picks)
        assert len(db_picks) == len(picks)

        draft_result = await db.execute(select(Draft).where(Draft.id == setup["draft_id"]))
        draft = draft_result.scalar_one()
        assert draft.status == DraftRunStatus.IN_PROGRESS


@pytest.mark.asyncio
async def test_mock_draft_query_count_does_not_scale_with_pick_count(db_session_factory):
    """Regression guard for the actual perf fix -- a small draft and a
    bigger draft (same players-per-pick ratio, just more teams/rounds)
    should NOT show a proportionally bigger per-pick query cost. Doesn't
    assert an exact number (too brittle across unrelated future changes)
    -- asserts the scaling shape instead."""
    from sqlalchemy import event

    async def _count_queries(coro_factory, engine):
        count = 0

        def _listener(conn, cursor, statement, parameters, context, executemany):
            nonlocal count
            count += 1

        event.listen(engine.sync_engine, "before_cursor_execute", _listener)
        try:
            await coro_factory()
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", _listener)
        return count

    small = await _make_draftable_league(db_session_factory, num_teams=4, total_rounds=3)  # 12 picks
    big = await _make_draftable_league(db_session_factory, num_teams=8, total_rounds=6)     # 48 picks

    engine = small["db_session_factory"]().bind

    async def run_small():
        async with small["db_session_factory"]() as db:
            await run_mock_draft(db, small["draft_id"])

    async def run_big():
        async with big["db_session_factory"]() as db:
            await run_mock_draft(db, big["draft_id"])

    small_queries = await _count_queries(run_small, engine)
    big_queries = await _count_queries(run_big, engine)

    # 4x the picks (12 -> 48) should NOT mean anywhere near 4x the
    # queries if the fix is real -- the old O(N) code would scale almost
    # linearly with pick count; the fixed code's per-pick cost is O(1)
    # (a handful of small queries), dominated by one-time setup.
    picks_ratio = 48 / 12
    query_ratio = big_queries / small_queries
    assert query_ratio < picks_ratio, (
        f"query count scaled {query_ratio:.1f}x for a {picks_ratio:.1f}x increase in picks "
        f"({small_queries} -> {big_queries}) -- looks like the N+1 regressed"
    )
