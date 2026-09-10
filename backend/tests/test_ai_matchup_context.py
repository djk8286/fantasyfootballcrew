"""
Tests for the 2026-09-09 fix to analyze_lineup: opponent_roster and
matchups were previously hardcoded to {} unconditionally, so the AI
lineup helper could only ever compare a lineup against generic
rankings -- never against the team's real weekly matchup, even though
the prompt template (LINEUP_ANALYSIS_PROMPT) already had a dedicated
"Opponent's Team" / "Matchup Details" section waiting for real data.
"""
import uuid
import pytest
from app.models.user import User
from app.models.league import League, LeagueVisibility, LeagueType
from app.models.team import Team
from app.models.player import Player
from app.services.standings_service import get_season_schedule
import app.api.v1.ai as ai_module


async def _make_league_with_teams(db_session_factory, num_teams=4):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                             username=f"user{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(commissioner)
        league = League(id=str(uuid.uuid4()), name="Matchup Context Test League", commissioner_id=commissioner.id,
                         visibility=LeagueVisibility.OPEN, scoring_config={}, roster_slots={},
                         league_type=LeagueType.STANDARD)
        db.add(league)
        teams = []
        for i in range(num_teams):
            t = Team(id=str(uuid.uuid4()), name=f"Team {i}", league_id=league.id, owner_id=commissioner.id, roster=[])
            db.add(t)
            teams.append(t)
        await db.commit()
        for t in teams:
            await db.refresh(t)
        return league, teams


def _mock_nfl_state(season: int, week: int):
    async def _fake_fetch_nfl_state():
        return {"season": str(season), "week": str(week), "season_type": "regular"}
    return _fake_fetch_nfl_state


@pytest.mark.asyncio
async def test_current_matchup_context_finds_real_opponent(db_session_factory, monkeypatch):
    league, teams = await _make_league_with_teams(db_session_factory)
    my_team = teams[0]

    # Learn who the real round-robin schedule actually pairs my_team
    # against in week 1, rather than assuming a specific pairing.
    async with db_session_factory() as db:
        schedule = await get_season_schedule(league.id, 2026, db)
    week1 = next(w for w in schedule if w["week"] == 1)
    my_matchup = next(
        m for m in week1["matchups"]
        if m["team_a"]["id"] == my_team.id or m["team_b"]["id"] == my_team.id
    )
    expected_opponent_id = (
        my_matchup["team_b"]["id"] if my_matchup["team_a"]["id"] == my_team.id else my_matchup["team_a"]["id"]
    )

    monkeypatch.setattr(ai_module, "fetch_nfl_state", _mock_nfl_state(2026, 1))

    async with db_session_factory() as db:
        db.add(Player(id="qb1", sleeper_id="qb1", first_name="Test", last_name="QB", position="QB"))
        opponent_team_result = await db.execute(
            __import__("sqlalchemy").select(Team).where(Team.id == expected_opponent_id)
        )
        opponent_team = opponent_team_result.scalar_one()
        opponent_team.roster = ["qb1"]
        await db.commit()

        opponent_roster, matchups = await ai_module._current_matchup_context(my_team, league, db)

    assert matchups["week"] == 1
    assert matchups["opponent_team_name"] == opponent_team.name
    assert "qb1" in opponent_roster
    assert opponent_roster["qb1"]["position"] == "QB"


@pytest.mark.asyncio
async def test_current_matchup_context_noop_for_mock_league(db_session_factory, monkeypatch):
    league, teams = await _make_league_with_teams(db_session_factory)
    async with db_session_factory() as db:
        league_result = await db.execute(__import__("sqlalchemy").select(League).where(League.id == league.id))
        league_row = league_result.scalar_one()
        league_row.is_mock = True
        await db.commit()
        await db.refresh(league_row)
        mock_league = league_row  # the freshly-mutated object, not the stale one _make_league_with_teams returned

        monkeypatch.setattr(ai_module, "fetch_nfl_state", _mock_nfl_state(2026, 1))
        opponent_roster, matchups = await ai_module._current_matchup_context(teams[0], mock_league, db)
    assert opponent_roster == {}
    assert matchups == {}


@pytest.mark.asyncio
async def test_current_matchup_context_noop_when_nfl_state_unavailable(db_session_factory, monkeypatch):
    league, teams = await _make_league_with_teams(db_session_factory)

    async def _raise():
        raise RuntimeError("network down")
    monkeypatch.setattr(ai_module, "fetch_nfl_state", _raise)

    async with db_session_factory() as db:
        opponent_roster, matchups = await ai_module._current_matchup_context(teams[0], league, db)
    assert opponent_roster == {}
    assert matchups == {}
