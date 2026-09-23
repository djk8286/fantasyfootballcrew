"""
Tests for league_deletion_service.delete_league -- the admin "delete a
dead league" cascade (2026-09-22). Every table with a real FK pointing
at leagues.id (directly or via teams/drafts/playoffs/contracts) is
RESTRICT by default; this pins that the full cascade actually clears
every one of them in the right order, that a completely empty league
still deletes cleanly, and that a Notification survives as "unlinked"
rather than being destroyed.
"""
import uuid
from datetime import datetime, timezone
import pytest
from sqlalchemy import select, func, text
from app.models.user import User
from app.models.league import League, LeagueType
from app.models.team import Team
from app.models.player import Player
from app.models.draft import Draft, DraftPick, DraftRunStatus
from app.models.draft_queue_entry import DraftQueueEntry
from app.models.playoff import Playoff, PlayoffMatchup, PlayoffStatus
from app.models.contract import Contract, DeadMoney
from app.models.coach import Coach, CoachPosition
from app.models.lineup import Lineup
from app.models.score_adjustment import ScoreAdjustment
from app.models.weekly_score import WeeklyScore
from app.models.transaction import Transaction, TransactionType
from app.models.team_player_news import TeamPlayerNews
from app.models.chat_message import ChatMessage
from app.models.ai_usage_event import AIUsageEvent
from app.models.ai_analysis_history import AIAnalysisHistory
from app.models.league_invite import LeagueInvite
from app.models.league_join_request import LeagueJoinRequest
from app.models.commissioner_digest import CommissionerDigest
from app.models.scoring import ScoringConfig
from app.models.notification import Notification, NotificationType
from app.models.team_weekly_recap import TeamWeeklyRecap
from app.services.league_deletion_service import delete_league

YEAR = 2026


@pytest.mark.asyncio
async def test_delete_league_with_no_dependents_at_all(db_session_factory):
    """The trivial case -- a brand new, totally empty league -- must
    still delete cleanly (no dependent rows anywhere to trip over)."""
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                             username=f"u{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(commissioner)
        await db.flush()
        league = League(id=str(uuid.uuid4()), name="Empty Shell", commissioner_id=commissioner.id,
                         league_type=LeagueType.STANDARD, scoring_config={}, roster_slots={})
        db.add(league)
        await db.commit()
        league_id = league.id

        await delete_league(db, league)
        await db.commit()

    async with db_session_factory() as db:
        result = await db.execute(select(League).where(League.id == league_id))
        assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_delete_league_clears_every_dependent_table_and_nulls_notifications(db_session_factory):
    # SQLite does NOT enforce foreign keys by default (this app's
    # core/database.py never sets PRAGMA foreign_keys=ON) -- without
    # this, this test would pass even if delete_league deleted rows in
    # the WRONG order, since nothing would actually check the
    # constraints it's built around. Production is Postgres, which DOES
    # enforce every one of these FKs (RESTRICT by default) -- turning
    # this on is what makes this test a real proof the ordering is
    # correct, not just that no exception happens to be raised in an
    # engine that never checks. db_session_factory uses a single
    # StaticPool connection, so this persists for the rest of the test.
    async with db_session_factory() as db:
        await db.execute(text("PRAGMA foreign_keys = ON"))
        await db.commit()

    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                             username=f"u{uuid.uuid4().hex[:8]}", hashed_password="x")
        other_user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                           username=f"u{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add_all([commissioner, other_user])
        await db.flush()

        league = League(id=str(uuid.uuid4()), name="Full Fixture League", commissioner_id=commissioner.id,
                         league_type=LeagueType.STANDARD, scoring_config={}, roster_slots={})
        db.add(league)
        await db.flush()

        player = Player(id=str(uuid.uuid4()), sleeper_id=f"s{uuid.uuid4().hex[:8]}",
                         first_name="Test", last_name="Player", position="RB")
        db.add(player)
        await db.flush()

        team_a = Team(id=str(uuid.uuid4()), name="Team A", league_id=league.id,
                      owner_id=commissioner.id, roster=[player.id])
        team_b = Team(id=str(uuid.uuid4()), name="Team B", league_id=league.id,
                      owner_id=other_user.id, roster=[])
        db.add_all([team_a, team_b])
        await db.flush()
        # Self-referential FK -- must survive the deletion's null-first step.
        team_a.partner_team_id = team_b.id
        await db.flush()

        draft = Draft(id=str(uuid.uuid4()), league_id=league.id, status=DraftRunStatus.COMPLETED)
        db.add(draft)
        await db.flush()
        db.add(DraftPick(id=str(uuid.uuid4()), draft_id=draft.id, league_id=league.id,
                          team_id=team_a.id, player_id=player.id, round=1, pick_number=1))
        db.add(DraftQueueEntry(id=str(uuid.uuid4()), draft_id=draft.id, team_id=team_a.id,
                                player_id=player.id, position=0))

        playoff = Playoff(id=str(uuid.uuid4()), league_id=league.id, year=YEAR,
                           seeding_method="wins", start_week=15, total_rounds=2)
        db.add(playoff)
        await db.flush()
        db.add(PlayoffMatchup(id=str(uuid.uuid4()), playoff_id=playoff.id, round=1, slot=0,
                               week=15, team_a_id=team_a.id, team_b_id=team_b.id))

        contract = Contract(id=str(uuid.uuid4()), league_id=league.id, team_id=team_a.id,
                             player_id=player.id, salary=10.0, contract_years=1,
                             signed_year=YEAR, source="draft")
        db.add(contract)
        await db.flush()
        db.add(DeadMoney(id=str(uuid.uuid4()), league_id=league.id, team_id=team_a.id,
                          player_id=player.id, contract_id=contract.id, amount=5.0))

        db.add(Coach(id=str(uuid.uuid4()), name="Coach K", position=CoachPosition.HC, team_id=team_a.id))
        db.add(Lineup(id=str(uuid.uuid4()), team_id=team_a.id, week=1, year=YEAR, starters=[player.id]))
        db.add(ScoreAdjustment(id=str(uuid.uuid4()), league_id=league.id, team_id=team_a.id,
                                week=1, year=YEAR, amount=1.0, reason="test", created_by=commissioner.id))
        db.add(WeeklyScore(id=str(uuid.uuid4()), league_id=league.id, team_id=team_a.id,
                            week=1, year=YEAR, total_score=100.0))
        db.add(Transaction(id=str(uuid.uuid4()), league_id=league.id, team_id=team_a.id,
                            type=TransactionType.ADD))
        db.add(TeamPlayerNews(id=str(uuid.uuid4()), team_id=team_a.id, league_id=league.id,
                               content="news", player_snapshot={}))
        db.add(ChatMessage(id=str(uuid.uuid4()), league_id=league.id, role="user", content="hi"))
        db.add(AIUsageEvent(id=str(uuid.uuid4()), league_id=league.id, endpoint="chat"))
        db.add(AIAnalysisHistory(id=str(uuid.uuid4()), user_id=commissioner.id, league_id=league.id,
                                  analysis_type="lineup", summary="s", result="r"))
        db.add(LeagueInvite(id=str(uuid.uuid4()), league_id=league.id, invited_email="x@test.local",
                             token_hash=f"h{uuid.uuid4().hex}", expires_at=datetime.now(timezone.utc)))
        db.add(LeagueJoinRequest(id=str(uuid.uuid4()), league_id=league.id,
                                  requested_by_user_id=other_user.id))
        db.add(CommissionerDigest(id=str(uuid.uuid4()), league_id=league.id, week=1, year=YEAR,
                                   content="digest", generated_by=commissioner.id))
        db.add(ScoringConfig(id=str(uuid.uuid4()), league_id=league.id, category="passing",
                              stat_name="pass_yd", points_per_unit=0.04))
        db.add(TeamWeeklyRecap(id=str(uuid.uuid4()), league_id=league.id, week=1, year=YEAR,
                                content="recap"))
        notification = Notification(id=str(uuid.uuid4()), user_id=other_user.id, league_id=league.id,
                                     type=NotificationType.MATCHUP_WON, message="you won")
        db.add(notification)
        await db.commit()

        league_id, team_a_id, team_b_id = league.id, team_a.id, team_b.id
        notification_id = notification.id

        result = await db.execute(select(League).where(League.id == league_id))
        league_reloaded = result.scalar_one()
        await delete_league(db, league_reloaded)
        await db.commit()

    # Everything scoped to the league is gone.
    async with db_session_factory() as db:
        assert (await db.execute(select(League).where(League.id == league_id))).scalar_one_or_none() is None
        assert (await db.execute(select(func.count(Team.id)).where(Team.league_id == league_id))).scalar() == 0
        assert (await db.execute(select(func.count(Draft.id)).where(Draft.league_id == league_id))).scalar() == 0
        assert (await db.execute(select(func.count(DraftPick.id)).where(DraftPick.league_id == league_id))).scalar() == 0
        assert (await db.execute(select(func.count(DraftQueueEntry.id)).where(DraftQueueEntry.team_id == team_a_id))).scalar() == 0
        assert (await db.execute(select(func.count(Playoff.id)).where(Playoff.league_id == league_id))).scalar() == 0
        assert (await db.execute(select(func.count(PlayoffMatchup.id)))).scalar() == 0
        assert (await db.execute(select(func.count(Contract.id)).where(Contract.league_id == league_id))).scalar() == 0
        assert (await db.execute(select(func.count(DeadMoney.id)).where(DeadMoney.league_id == league_id))).scalar() == 0
        assert (await db.execute(select(func.count(Coach.id)).where(Coach.team_id == team_a_id))).scalar() == 0
        assert (await db.execute(select(func.count(Lineup.id)).where(Lineup.team_id == team_a_id))).scalar() == 0
        assert (await db.execute(select(func.count(ScoreAdjustment.id)).where(ScoreAdjustment.league_id == league_id))).scalar() == 0
        assert (await db.execute(select(func.count(WeeklyScore.id)).where(WeeklyScore.league_id == league_id))).scalar() == 0
        assert (await db.execute(select(func.count(Transaction.id)).where(Transaction.league_id == league_id))).scalar() == 0
        assert (await db.execute(select(func.count(TeamPlayerNews.id)).where(TeamPlayerNews.league_id == league_id))).scalar() == 0
        assert (await db.execute(select(func.count(ChatMessage.id)).where(ChatMessage.league_id == league_id))).scalar() == 0
        assert (await db.execute(select(func.count(AIUsageEvent.id)).where(AIUsageEvent.league_id == league_id))).scalar() == 0
        assert (await db.execute(select(func.count(AIAnalysisHistory.id)).where(AIAnalysisHistory.league_id == league_id))).scalar() == 0
        assert (await db.execute(select(func.count(LeagueInvite.id)).where(LeagueInvite.league_id == league_id))).scalar() == 0
        assert (await db.execute(select(func.count(LeagueJoinRequest.id)).where(LeagueJoinRequest.league_id == league_id))).scalar() == 0
        assert (await db.execute(select(func.count(CommissionerDigest.id)).where(CommissionerDigest.league_id == league_id))).scalar() == 0
        assert (await db.execute(select(func.count(ScoringConfig.id)).where(ScoringConfig.league_id == league_id))).scalar() == 0
        assert (await db.execute(select(func.count(TeamWeeklyRecap.id)).where(TeamWeeklyRecap.league_id == league_id))).scalar() == 0
        assert (await db.execute(select(func.count(Team.id)).where(Team.id == team_b_id))).scalar() == 0

        # The notification SURVIVES, just unlinked from the (now-gone)
        # league -- it's the recipient's own history, not the league's.
        notif_result = await db.execute(select(Notification).where(Notification.id == notification_id))
        notif = notif_result.scalar_one()
        assert notif.league_id is None
        assert notif.message == "you won"

        # The player (global NFL pool, not league-scoped) is untouched.
        player_result = await db.execute(select(Player).where(Player.id == player.id))
        assert player_result.scalar_one_or_none() is not None

        # Neither user was touched by deleting the league.
        for uid in (commissioner.id, other_user.id):
            assert (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none() is not None
