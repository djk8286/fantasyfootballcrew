"""Which NFL weeks count for a league: final or not, and which came
before the league drafted."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.draft import Draft, DraftPick, DraftRunStatus
from app.models.nfl_game import NFLGame
from app.services.nfl_schedule_service import as_utc

# A game is over well within this long after kickoff. Past it, a week
# counts as final even if a game row's completed flag was never refreshed.
GAME_WINDOW = timedelta(hours=8)


class WeekState:
    UPCOMING = "upcoming"
    LIVE = "live"
    FINAL = "final"
    UNKNOWN = "unknown"  # no games synced for the week


async def week_bounds(year: int, db: AsyncSession) -> dict[int, tuple[datetime, datetime, bool]]:
    """week -> (first kickoff, last kickoff, every game completed)."""
    rows = await db.execute(
        select(
            NFLGame.week,
            func.min(NFLGame.kickoff_at),
            func.max(NFLGame.kickoff_at),
            func.count(),
            func.sum(case((NFLGame.completed.is_(True), 1), else_=0)),
        ).where(NFLGame.year == year, NFLGame.season_type == 2).group_by(NFLGame.week)
    )
    return {w: (as_utc(first), as_utc(last), int(done or 0) == n) for w, first, last, n, done in rows.all()}


async def season_week_states(year: int, db: AsyncSession, now: datetime | None = None) -> dict[int, str]:
    """week -> WeekState for every week with synced games. Missing weeks are UNKNOWN."""
    now = now or datetime.now(timezone.utc)
    out = {}
    for week, (first, last, all_done) in (await week_bounds(year, db)).items():
        if all_done or now >= last + GAME_WINDOW:
            out[week] = WeekState.FINAL
        elif now >= first:
            out[week] = WeekState.LIVE
        else:
            out[week] = WeekState.UPCOMING
    return out


def week_counts(states: dict[int, str], week: int) -> bool:
    """Whether a week's scores count toward W/L and points for/against.
    Unknown weeks count, as they always did."""
    return states.get(week, WeekState.UNKNOWN) in (WeekState.FINAL, WeekState.UNKNOWN)


async def league_start_week(league_id: str, year: int, db: AsyncSession) -> int:
    """First NFL week the league plays: the week in progress (or next)
    when its draft finished. 1 when there's no finished draft or no
    schedule to place it in."""
    draft = (await db.execute(
        select(Draft).where(Draft.league_id == league_id, Draft.status == DraftRunStatus.COMPLETED)
        .order_by(Draft.updated_at.desc()).limit(1)
    )).scalar_one_or_none()
    if draft is None:
        return 1
    last_pick = (await db.execute(
        select(func.max(DraftPick.drafted_at)).where(DraftPick.draft_id == draft.id)
    )).scalar_one_or_none()
    done_at = last_pick or draft.updated_at
    if done_at is None:
        return 1
    done_at = as_utc(done_at)
    bounds = await week_bounds(year, db)
    if not bounds:
        return 1
    later = [w for w, (_, last, _) in bounds.items() if last > done_at]
    if later:
        return min(later)
    # Drafted after every synced game: the season so far is all pre-draft.
    return min(max(bounds) + 1, 18)
