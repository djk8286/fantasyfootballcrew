"""
Tests for team_recap_service.build_team_recap_context -- Dashboard AI
Summaries initiative. One entry per team: this week's score, W/L/T/bye
result, opponent, and top-scoring starter.
"""
import uuid
import pytest
from app.models.user import User
from app.models.league import League, LeagueType, DraftStatus
from app.models.team import Team
from app.models.player import Player
from app.models.weekly_score import WeeklyScore
from app.services.team_recap_service import build_team_recap_context, get_recap, generate_and_save_recap


async def _make_league_with_scores(db_session_factory, num_teams=4, week=1, year=2026):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@example.com",
                             username=f"recapcommish{uuid.uuid4().hex[:6]}", hashed_password="x")
        db.add(commissioner)
        await db.flush()
        league = League(id=str(uuid.uuid4()), name="Recap Test League", commissioner_id=commissioner.id,
                         league_type=LeagueType.STANDARD, draft_status=DraftStatus.COMPLETED,
                         scoring_config={}, roster_slots={})
        db.add(league)
        await db.flush()

        teams = []
        players = []
        for i in range(num_teams):
            p = Player(id=str(uuid.uuid4()), sleeper_id=str(uuid.uuid4()), first_name="Top", last_name=f"Scorer{i}",
                       position="RB", team="XXX")
            db.add(p)
            players.append(p)
            t = Team(id=str(uuid.uuid4()), name=f"Team {i}", league_id=league.id, owner_id=commissioner.id,
                     roster=[p.id], is_cpu=False)
            db.add(t)
            teams.append(t)
        await db.flush()

        # Descending scores so win/loss is unambiguous within each pair.
        for i, t in enumerate(teams):
            score_val = 100.0 - i * 10
            db.add(WeeklyScore(
                league_id=league.id, team_id=t.id, week=week, year=year, total_score=score_val,
                lineup_data={"breakdown": {players[i].id: {"score": score_val, "stats": {}, "position": "RB"}}},
            ))
        await db.commit()
        return {"league": league, "teams": teams, "players": players, "db_session_factory": db_session_factory}


@pytest.mark.asyncio
async def test_context_includes_result_opponent_and_top_performer(db_session_factory):
    setup = await _make_league_with_scores(db_session_factory, num_teams=4)
    async with setup["db_session_factory"]() as db:
        context = await build_team_recap_context(setup["league"], week=1, year=2026, db=db)

    by_name = {c["team_name"]: c for c in context}
    assert len(context) == 4
    # Team 0 (highest score) beat Team 1 in the round-robin's first pairing.
    t0 = by_name["Team 0"]
    assert t0["result"] == "win"
    assert t0["opponent_name"] is not None
    assert t0["top_performer"] == "Top Scorer0"
    assert t0["top_performer_points"] == 100.0


@pytest.mark.asyncio
async def test_no_weekly_scores_yet_returns_empty_context(db_session_factory):
    setup = await _make_league_with_scores(db_session_factory, num_teams=2, week=1)
    async with setup["db_session_factory"]() as db:
        context = await build_team_recap_context(setup["league"], week=99, year=2026, db=db)
    assert context == []


@pytest.mark.asyncio
async def test_generate_and_save_recap_upserts_and_skips_when_no_data(db_session_factory, monkeypatch):
    from app.services.ai_service import AIService

    async def spy(self, prompt):
        return "TEAM 0: did great."
    monkeypatch.setattr(AIService, "_call_llm", spy)

    setup = await _make_league_with_scores(db_session_factory, num_teams=2)

    async with setup["db_session_factory"]() as db:
        recap = await generate_and_save_recap(setup["league"], week=1, year=2026, generated_by=None, db=db)
    assert recap is not None
    assert recap.content == "TEAM 0: did great."

    # Regenerate -- upserts in place, no duplicate row.
    async with setup["db_session_factory"]() as db:
        recap2 = await generate_and_save_recap(setup["league"], week=1, year=2026, generated_by=None, db=db)
    assert recap2.id == recap.id

    # A week with no scored data at all -- no-op, returns None, no row created.
    async with setup["db_session_factory"]() as db:
        none_recap = await generate_and_save_recap(setup["league"], week=99, year=2026, generated_by=None, db=db)
    assert none_recap is None
    async with setup["db_session_factory"]() as db:
        assert await get_recap(setup["league"].id, 99, 2026, db) is None
