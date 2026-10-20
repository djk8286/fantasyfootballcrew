"""
Admin League Deletion (2026-09-22). Every table below has a real,
un-cascaded FK pointing at leagues.id or (transitively) teams.id/
drafts.id/playoffs.id/contracts.id -- Postgres enforces RESTRICT by
default on all of them, so a bare `db.delete(league)` fails with an
IntegrityError the moment ANY child row still exists (which is every
real league). This deletes every dependent row first, in dependency
order (deepest children first), all inside the caller's own
transaction -- nothing is committed here, so a failure partway through
leaves the database exactly as it was, not a half-deleted league.

Two deliberate exceptions to "just delete the row": Notification and
User are never touched here. A Notification is the RECEIVING user's
own inbox history, not the league's -- its league_id is nulled instead
of the row being deleted, same "null someone else's reference, don't
destroy someone else's data" precedent
users.delete_me/account_deletion_service already set for account
deletion. Users (commissioners, team owners) are entirely untouched --
deleting a league never deletes a person.
"""
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.league import League
from app.models.team import Team
from app.models.draft import Draft, DraftPick
from app.models.draft_queue_entry import DraftQueueEntry
from app.models.draft_autopick import DraftAutopick
from app.models.playoff import Playoff, PlayoffMatchup
from app.models.contract import Contract, DeadMoney
from app.models.coach import Coach
from app.models.lineup import Lineup
from app.models.score_adjustment import ScoreAdjustment
from app.models.weekly_score import WeeklyScore
from app.models.transaction import Transaction
from app.models.team_player_news import TeamPlayerNews
from app.models.chat_message import ChatMessage
from app.models.ai_usage_event import AIUsageEvent
from app.models.ai_analysis_history import AIAnalysisHistory
from app.models.league_invite import LeagueInvite
from app.models.league_join_request import LeagueJoinRequest
from app.models.commissioner_digest import CommissionerDigest
from app.models.scoring import ScoringConfig
from app.models.notification import Notification
from app.models.team_weekly_recap import TeamWeeklyRecap


async def delete_league(db: AsyncSession, league: League) -> None:
    """Permanently and irreversibly deletes `league` and every row that
    exists only because of it. Does NOT commit -- the caller (the admin
    endpoint) commits once, after this returns, so the whole deletion
    is one atomic transaction."""
    team_ids_result = await db.execute(select(Team.id).where(Team.league_id == league.id))
    team_ids = [t for (t,) in team_ids_result.all()]

    draft_ids_result = await db.execute(select(Draft.id).where(Draft.league_id == league.id))
    draft_ids = [d for (d,) in draft_ids_result.all()]

    playoff_ids_result = await db.execute(select(Playoff.id).where(Playoff.league_id == league.id))
    playoff_ids = [p for (p,) in playoff_ids_result.all()]

    # --- Level 3: rows that reference a Draft/Playoff/Contract row ----
    if playoff_ids:
        await db.execute(delete(PlayoffMatchup).where(PlayoffMatchup.playoff_id.in_(playoff_ids)))
    if draft_ids:
        await db.execute(delete(DraftQueueEntry).where(DraftQueueEntry.draft_id.in_(draft_ids)))
        await db.execute(delete(DraftAutopick).where(DraftAutopick.draft_id.in_(draft_ids)))
    await db.execute(delete(DraftPick).where(DraftPick.league_id == league.id))
    await db.execute(delete(DeadMoney).where(DeadMoney.league_id == league.id))

    # --- Level 2: rows that reference a Team, or are themselves the
    #     Draft/Playoff/Contract rows the level-3 deletes above just
    #     cleared references to -----------------------------------------
    await db.execute(delete(Contract).where(Contract.league_id == league.id))
    await db.execute(delete(Playoff).where(Playoff.league_id == league.id))
    await db.execute(delete(Draft).where(Draft.league_id == league.id))
    if team_ids:
        await db.execute(delete(Coach).where(Coach.team_id.in_(team_ids)))
        await db.execute(delete(Lineup).where(Lineup.team_id.in_(team_ids)))
    await db.execute(delete(ScoreAdjustment).where(ScoreAdjustment.league_id == league.id))
    await db.execute(delete(WeeklyScore).where(WeeklyScore.league_id == league.id))
    await db.execute(delete(Transaction).where(Transaction.league_id == league.id))
    await db.execute(delete(TeamPlayerNews).where(TeamPlayerNews.league_id == league.id))

    # --- Level 1: rows scoped directly to the league, nothing left
    #     referencing them at this point ---------------------------------
    await db.execute(delete(ChatMessage).where(ChatMessage.league_id == league.id))
    await db.execute(delete(AIUsageEvent).where(AIUsageEvent.league_id == league.id))
    await db.execute(delete(AIAnalysisHistory).where(AIAnalysisHistory.league_id == league.id))
    await db.execute(delete(LeagueInvite).where(LeagueInvite.league_id == league.id))
    await db.execute(delete(LeagueJoinRequest).where(LeagueJoinRequest.league_id == league.id))
    await db.execute(delete(CommissionerDigest).where(CommissionerDigest.league_id == league.id))
    await db.execute(delete(ScoringConfig).where(ScoringConfig.league_id == league.id))
    await db.execute(delete(TeamWeeklyRecap).where(TeamWeeklyRecap.league_id == league.id))

    # A user's own notification history outlives the league it was
    # about -- see module docstring. Nulled, not deleted.
    await db.execute(
        update(Notification).where(Notification.league_id == league.id).values(league_id=None)
    )

    # --- Teams: null the self-referential partner_team_id first
    #     (defensive -- a bulk DELETE of mutually-referencing rows in one
    #     statement is fine on both SQLite and Postgres, but there's no
    #     reason to rely on that when nulling first is free) -----------
    if team_ids:
        await db.execute(
            update(Team).where(Team.league_id == league.id).values(partner_team_id=None)
        )
        await db.execute(delete(Team).where(Team.league_id == league.id))

    # --- The league itself. Nothing references it anymore. ------------
    await db.delete(league)
