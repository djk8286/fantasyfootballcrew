"""
Tests for _verified_players_from_text (api/v1/ai.py) -- the Bet tab's
only grounding against real data, added investigating a David-reported
"the AI gave a few answers that were a little off on player movement/
who's on what team" bug. The Bet tab is pure free text with no
structured input at all, so this is the one place that can catch the
model guessing wrong about a specific, real player's current team.
"""
import uuid
import pytest
from app.models.player import Player
from app.api.v1.ai import _verified_players_from_text


async def _seed_players(db_session_factory):
    async with db_session_factory() as db:
        db.add(Player(id=str(uuid.uuid4()), sleeper_id="v1", first_name="Puka", last_name="Nacua",
                       position="WR", team="LAR", injury_status=None))
        db.add(Player(id=str(uuid.uuid4()), sleeper_id="v2", first_name="Justin", last_name="Fields",
                       position="QB", team="NYJ", injury_status="Questionable"))
        await db.commit()


@pytest.mark.asyncio
async def test_finds_real_player_mentioned_in_free_text(db_session_factory):
    await _seed_players(db_session_factory)
    async with db_session_factory() as db:
        result = await _verified_players_from_text(
            "Is Puka Nacua a good start against the Bills this week?", db
        )
    assert len(result) == 1
    assert result[0]["name"] == "Puka Nacua"
    assert result[0]["current_team"] == "LAR"


@pytest.mark.asyncio
async def test_finds_multiple_players_and_reports_injury_status(db_session_factory):
    await _seed_players(db_session_factory)
    async with db_session_factory() as db:
        result = await _verified_players_from_text(
            "Justin Fields vs Puka Nacua, who has the better matchup?", db
        )
    by_name = {p["name"]: p for p in result}
    assert set(by_name) == {"Justin Fields", "Puka Nacua"}
    assert by_name["Justin Fields"]["injury_status"] == "Questionable"
    assert by_name["Puka Nacua"]["injury_status"] == "none reported"


@pytest.mark.asyncio
async def test_no_real_names_in_text_returns_empty(db_session_factory):
    await _seed_players(db_session_factory)
    async with db_session_factory() as db:
        result = await _verified_players_from_text(
            "Chiefs minus three and a half at home, good bet?", db
        )
    assert result == []


@pytest.mark.asyncio
async def test_capitalized_phrase_that_matches_no_real_player_returns_empty(db_session_factory):
    """A name-shaped phrase that just doesn't correspond to any synced
    player -- the whole point of this being a loose regex is that false
    positives here are harmless (silently found nothing), not that it
    never fires on non-players."""
    await _seed_players(db_session_factory)
    async with db_session_factory() as db:
        result = await _verified_players_from_text("What about New York Giants defense?", db)
    assert result == []


@pytest.mark.asyncio
async def test_same_player_not_duplicated_if_mentioned_twice(db_session_factory):
    await _seed_players(db_session_factory)
    async with db_session_factory() as db:
        result = await _verified_players_from_text(
            "Puka Nacua has been great. Should I start Puka Nacua over my other WR?", db
        )
    assert len(result) == 1
