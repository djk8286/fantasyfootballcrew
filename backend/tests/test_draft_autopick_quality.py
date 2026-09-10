"""
Regression coverage for the 2026-09-09 fix to get_ai_mock_pick's player
selection: real bug report was "Auto-Fill picks random, not even good,
players." Root cause -- get_percentile_tier bucketed the ENTIRE ranked
pool into just 5 tiers (tiers 3 and 4 alone each covered 30% of every
draftable player), and every player in the same tier got the exact same
tier_score. Combined with a ~40-point randomization window, a player
ranked #50 and one ranked #490 could tie and become equally likely
picks. Fixed by making tier_score a continuous function of real rank
instead of a 5-step bucket.

These tests use a real DB (db_session_factory, from conftest.py) since
get_ai_mock_pick queries Player/DraftPick/Team for real -- unlike
test_draft_manager.py's pure in-memory build_rank_by_id coverage.
"""
import random
import uuid
import pytest
from app.models.user import User
from app.models.league import League, LeagueVisibility, LeagueType, DraftStatus
from app.models.team import Team
from app.models.player import Player
from app.services.draft_manager import create_draft, start_draft, get_ai_mock_pick


async def _setup_draft(db_session_factory, num_players=2000, position="RB"):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                             username=f"user{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(commissioner)
        league = League(id=str(uuid.uuid4()), name="Autopick Quality Test League", commissioner_id=commissioner.id,
                         visibility=LeagueVisibility.OPEN, scoring_config={}, roster_slots={},
                         league_type=LeagueType.STANDARD, draft_status=DraftStatus.NOT_STARTED)
        db.add(league)
        team = Team(id=str(uuid.uuid4()), name="CPU Team", league_id=league.id, is_cpu=True, roster=[])
        db.add(team)
        # create_draft requires >= 2 teams; the second is just filler,
        # never picked from in these tests.
        db.add(Team(id=str(uuid.uuid4()), name="CPU Team 2", league_id=league.id, is_cpu=True, roster=[]))
        # search_rank 1 (best) .. num_players (worst), at real-world scale
        # (thousands of draftable players) -- inserted in SHUFFLED order
        # deliberately, not rank order. get_ai_mock_pick's own DB query
        # has no ORDER BY, so its natural iteration order reflects
        # insertion/rowid order, which in real production is whatever
        # order Sleeper's sync happened to return players in -- NOT rank
        # order. Inserting in rank order here would let the DB's
        # coincidental return order mask exactly the bug this test
        # exists to catch (an unsorted slice of a same-scored group).
        ranks = list(range(1, num_players + 1))
        random.Random(42).shuffle(ranks)
        for rank in ranks:
            db.add(Player(id=f"rb{rank}", sleeper_id=str(uuid.uuid4()), first_name=f"Back{rank}",
                           last_name="Runner", position=position, search_rank=rank))
        await db.commit()
        await db.refresh(team)

        draft = await create_draft(db, league.id, total_rounds=15)
        await start_draft(db, draft.id)
        return draft, team


@pytest.mark.asyncio
async def test_round_one_pick_never_reaches_deep_into_the_pool(db_session_factory):
    """Round 1, empty roster, 2000 ranked RBs on the board (real-world
    scale) -- the pick must come from genuinely near the top of real
    rank. Under the old discrete-tier scoring, tier 1 alone (top 5%) is
    100 players all scored identically, and the candidate slice was
    never sorted by true rank within that tie -- with players inserted
    in shuffled (non-rank) order, that could surface literally any of
    those 100 with equal odds, not just the best few."""
    draft, team = await _setup_draft(db_session_factory, num_players=2000)

    async with db_session_factory() as db:
        picks_ranks = []
        for _ in range(25):
            player = await get_ai_mock_pick(db, draft.id, team.id, current_round=1, total_rounds=15)
            assert player is not None
            picks_ranks.append(int(player.id[2:]))  # "rb17" -> 17, i.e. its search_rank

        assert max(picks_ranks) <= 15, f"picked a rank as deep as {max(picks_ranks)} of 2000 in round 1 -- fix regressed"
        assert sum(picks_ranks) / len(picks_ranks) <= 8


@pytest.mark.asyncio
async def test_never_reaches_outside_the_true_top_tier_of_a_large_pool(db_session_factory):
    """Even allowing for realistic randomness, the AI must never wander
    outside the genuine top slice of a 2000-player pool on an early pick
    -- that's exactly what the reported "random, not even good, players"
    bug looked like (picking anywhere within the 100-player tier-1 band,
    not just its best few)."""
    draft, team = await _setup_draft(db_session_factory, num_players=2000)

    async with db_session_factory() as db:
        for _ in range(25):
            player = await get_ai_mock_pick(db, draft.id, team.id, current_round=2, total_rounds=15)
            assert player is not None
            rank = int(player.id[2:])
            assert rank <= 30, f"picked rank {rank} of 2000 in round 2 -- should stay near the genuine top"
