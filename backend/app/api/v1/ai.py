import contextlib
import re
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.core.database import get_db
from app.core.config import settings
from app.core.limiter import limiter
from app.models.team import Team
from app.models.league import League, LeagueType
from app.models.player import Player
from app.models.coach import Coach
from app.models.transaction import Transaction, TransactionType
from app.models.user import User
from app.services.ai_service import AIService
from app.services.standings_service import get_standings, get_combined_standings, get_season_schedule, DEFAULT_SEASON_WEEKS
from app.services.salary_cap_service import get_salary_cap_settings, team_cap_summary
from app.services.ai_usage_service import record_ai_usage
from app.services.ai_history_service import record_analysis, get_analysis_history
from app.services import ai_jobs, ai_cost_service
from app.models.ai_usage_event import AIUsageEvent
from app.services.scheduler import fetch_nfl_state
from app.api.v1.lineups import load_week_games
from app.services.default_lineup import league_roster_slots
from app.services.scoring_engine import DEFAULT_ROSTER_SLOTS
from app.services.team_comparison_service import build_team_trend
from app.services.player_comparison_service import build_player_profile
from app.api.deps import get_current_user, require_league_participant

router = APIRouter(prefix="/ai", tags=["ai"])


def _get_ai_service() -> AIService:
    if settings.OPENAI_API_KEY:
        return AIService(api_key=settings.OPENAI_API_KEY, provider="openai")
    if settings.ANTHROPIC_API_KEY:
        return AIService(api_key=settings.ANTHROPIC_API_KEY, provider="anthropic")
    return AIService(api_key=None)


# Two-or-three consecutive Capitalized words -- "Justin Fields", "Odell
# Beckham Jr" -- as a lightweight, no-NLP-dependency way to spot likely
# player names in a Bet tab's free-text prompt (the ONLY AI Analysis
# feature with zero structured input, see analyze_bet below). Deliberately
# loose: false positives (matching a phrase that isn't actually a player)
# just mean the DB lookup below finds nothing and it's silently dropped;
# there's no cost to over-triggering here, only to under-triggering.
_NAME_CANDIDATE_RE = re.compile(r"\b[A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+){1,2}\b")


async def _verified_players_from_text(text: str, db: AsyncSession) -> list[dict]:
    """Extract candidate player names from free text and look each up
    against this app's own synced Player data (real current team/
    position/injury_status from Sleeper, not the LLM's training
    memory) -- see analyze_bet's docstring for why this exists.

    A regex match can be 2-3 capitalized words, and the FIRST word isn't
    reliably the first name -- a sentence-initial capital ("Is Puka
    Nacua a good start?") gets swept into the same match as a real name,
    and a suffix ("Odell Beckham Jr") puts the real last name in the
    middle, not last. Rather than guess which word is which, try every
    consecutive 2-word window inside each match as a (first, last)
    candidate pair -- cheap (matches are short) and side-effect-free
    (an extra wrong pairing just finds zero rows in the DB and is
    silently dropped, same as any other false positive here)."""
    seen_ids: set[str] = set()
    verified: list[dict] = []
    for candidate in set(_NAME_CANDIDATE_RE.findall(text)):
        words = candidate.split()
        for i in range(len(words) - 1):
            first, last = words[i], words[i + 1]
            result = await db.execute(
                select(Player).where(Player.first_name.ilike(first), Player.last_name.ilike(last))
            )
            for p in result.scalars().all():
                if p.id in seen_ids:
                    continue
                seen_ids.add(p.id)
                verified.append({
                    "name": f"{p.first_name} {p.last_name}",
                    "position": p.position,
                    "current_team": p.team or "Free Agent",
                    "injury_status": p.injury_status or "none reported",
                })
    return verified


async def _roster_summary(team: Team, db: AsyncSession) -> dict:
    if not team.roster:
        return {}
    result = await db.execute(select(Player).where(Player.id.in_(team.roster)))
    players = result.scalars().all()
    return {
        p.id: {
            "name": f"{p.first_name} {p.last_name}", "position": p.position, "team": p.team,
            "injury_status": p.injury_status,
        }
        for p in players
    }


async def _coach_summary(team: Team, db: AsyncSession) -> list[dict]:
    """A team's active coaching staff, for threading into AI prompt
    context (Phase 2 Step 3, "Front-Office finish-out") -- lets the AI
    factor a team's win_bonus/flat_weekly coaches into its commentary."""
    result = await db.execute(
        select(Coach).where(Coach.team_id == team.id, Coach.is_active == True)  # noqa: E712
    )
    return [
        {"position": c.position.value, "name": c.name, "bonus_type": c.bonus_type, "bonus_value": c.bonus_value}
        for c in result.scalars().all()
    ]


async def _salary_summary(team: Team, league: League, db: AsyncSession) -> dict:
    """A team's cap situation, for threading into AI prompt context
    (Phase 5, "Salary-Cap + Contract Leagues") -- lets the AI factor cap
    space/contract obligations into its lineup/trade commentary. No-ops
    to {} for a non-cap league, same house style as _coach_summary
    returning [] for a team with no coaches."""
    if not league or not get_salary_cap_settings(league)["enabled"]:
        return {}
    return await team_cap_summary(team, league, db)


async def _partner_summary(team: Team, league: League, db: AsyncSession) -> dict:
    """A team's linked-pair context, for threading into AI prompt
    context (Phase 7, "Dual-Squad/Mirror") -- lets the AI factor a
    manager's OTHER team's record into lineup/trade commentary (e.g.
    "your pair is already locked into 1st combined, this trade is
    low-stakes"). No-ops to {} for a non-paired team/league, same house
    style as _salary_summary returning {} for a non-cap league."""
    if not league or league.league_type != LeagueType.DUAL_SQUAD or not team.partner_team_id:
        return {}
    combined = await get_combined_standings(league.id, db)
    row = next((r for r in combined if team.id in r["team_ids"]), None)
    return row or {}


async def _current_matchup_context(team: Team, league: League | None, db: AsyncSession) -> tuple[dict, dict]:
    """This team's REAL current-week opponent roster + matchup context,
    for threading into the AI lineup prompt (2026-09-09). Previously
    analyze_lineup passed opponent_roster={} and matchups={}
    unconditionally -- the AI could only ever compare a lineup against
    generic rankings, never against what's actually happening in the
    team's own matchup this week. Reuses get_season_schedule (the same
    real/projected-score schedule the Schedule page itself renders) to
    find this week's opponent, rather than a second, parallel
    "who do I play this week" implementation.

    No-ops to ({}, {}) for a mock/practice-draft league, a league with
    no schedule this week (bye week, an odd team out, or Guillotine's
    finale pairing not applying), or if the live NFL week can't be
    fetched -- same "meaningless but harmless" precedent every other
    optional context helper here (_salary_summary, _partner_summary)
    already follows for a case it doesn't apply to."""
    if not league or league.is_mock:
        return {}, {}
    try:
        state = await fetch_nfl_state()
        season = int(state["season"])
        week = int(state["week"])
    except Exception:
        return {}, {}

    schedule = await get_season_schedule(league.id, season, db, num_weeks=DEFAULT_SEASON_WEEKS)
    week_entry = next((w for w in schedule if w["week"] == week), None)
    if not week_entry:
        return {}, {}

    opponent_id = my_entry = opp_entry = None
    for m in week_entry["matchups"]:
        if m["team_a"]["id"] == team.id:
            opponent_id, my_entry, opp_entry = m["team_b"]["id"], m["team_a"], m["team_b"]
            break
        if m["team_b"]["id"] == team.id:
            opponent_id, my_entry, opp_entry = m["team_a"]["id"], m["team_b"], m["team_a"]
            break
    if not opponent_id:
        return {}, {}  # bye week / eliminated / odd team out this week

    opp_result = await db.execute(select(Team).where(Team.id == opponent_id))
    opponent = opp_result.scalar_one_or_none()
    opponent_roster = await _roster_summary(opponent, db) if opponent else {}

    matchups = {
        "week": week,
        "opponent_team_name": opponent.name if opponent else "Unknown",
        "my_projected_score": my_entry["projected_score"],
        "opponent_projected_score": opp_entry["projected_score"],
    }
    return opponent_roster, matchups


class LineupAnalysisRequest(BaseModel):
    team_id: str


class TradeAnalysisRequest(BaseModel):
    trade_id: str


class BetAnalysisRequest(BaseModel):
    prompt: str


class TeamComparisonRequest(BaseModel):
    team_a_id: str
    team_b_id: str


class PlayerComparisonRequest(BaseModel):
    player_a_id: str
    player_b_id: str
    league_id: str


async def _load_owned_team(body: "LineupAnalysisRequest", db: AsyncSession, current_user: User):
    result = await db.execute(select(Team).where(Team.id == body.team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    if current_user.id not in {team.owner_id, team.co_owner_id}:
        raise HTTPException(status_code=403, detail="You do not own this team")
    league_result = await db.execute(select(League).where(League.id == team.league_id))
    return team, league_result.scalar_one_or_none()


def league_starting_slots(league: League | None) -> dict[str, int]:
    """The league's configured starting slots (zero-count slots dropped),
    in lineup order. Without these the model assumed a generic format
    (QA 2026-10-19: "the recommendation assumes a common format")."""
    slots = league_roster_slots(league) if league else dict(DEFAULT_ROSTER_SLOTS)
    return {k: int(v) for k, v in slots.items() if int(v or 0) > 0}


async def _add_week_games(roster: dict, db: AsyncSession) -> None:
    """Each player's bye and game this week, from the same WeekGames the
    lineup page uses. Without it the model only saw injury_status and
    started a TE on bye as merely "Questionable" (QA 2026-10-20)."""
    if not roster:
        return
    try:
        state = await fetch_nfl_state()
        games = await load_week_games(int(state["season"]), int(state["week"]), db)
    except Exception:
        return
    for p in roster.values():
        p["on_bye"] = games.on_bye(p["team"])
        p["game"] = games.info(p["team"])


async def _lineup_prompt_inputs(team: Team, league: League | None, db: AsyncSession) -> dict:
    """Everything analyze_lineup needs, gathered from the DB up front so the
    (slow) LLM call itself can run without holding a request open."""
    roster = await _roster_summary(team, db)
    await _add_week_games(roster, db)
    coaching_staff = await _coach_summary(team, db)
    salary_context = await _salary_summary(team, league, db)
    partner_context = await _partner_summary(team, league, db)
    # This team's REAL current-week opponent + matchup context -- see
    # _current_matchup_context.
    opponent_roster, matchups = await _current_matchup_context(team, league, db)
    return dict(
        roster=roster, opponent_roster=opponent_roster, matchups=matchups,
        roster_slots=league_starting_slots(league),
        scoring=(league.scoring_config if league else None) or {},
        coaching_staff=coaching_staff, salary_context=salary_context,
        partner_context=partner_context,
    )


@router.post("/lineup")
@limiter.limit("10/hour")
async def analyze_lineup(
    request: Request,
    body: LineupAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Synchronous lineup analysis (kept for API callers). The web app uses
    the async /ai/lineup/jobs flow below, because generation routinely
    takes 20-40 s and a page navigation mid-request dropped the result
    (QA regression 2026-10-19). Rate-limited: each call is a real LLM
    request once a key is configured."""
    team, league = await _load_owned_team(body, db, current_user)
    inputs = await _lineup_prompt_inputs(team, league, db)
    await record_ai_usage(db, "lineup", league_id=team.league_id, user_id=current_user.id)
    analysis = await _get_ai_service().analyze_lineup(**inputs)
    await record_analysis(
        db, user_id=current_user.id, analysis_type="lineup", league_id=team.league_id,
        summary=f"{team.name} — {league.name}" if league else team.name, result=analysis,
    )
    await db.commit()
    return {"analysis": analysis}


@contextlib.asynccontextmanager
async def _job_session(session_dep):
    """One short-lived session from a get_db-style generator, always closed
    (returning its pool connection) -- the job holds no connection while
    the model call itself runs."""
    gen = session_dep()
    try:
        yield await gen.__anext__()
    finally:
        await gen.aclose()


@router.post("/lineup/jobs", status_code=202)
@limiter.limit("10/hour")
async def start_lineup_analysis_job(
    request: Request,
    body: LineupAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Start a lineup analysis in the background and return a job id
    immediately; poll GET /ai/jobs/{job_id}. The result is also saved to
    analysis history exactly like the synchronous endpoint."""
    team, league = await _load_owned_team(body, db, current_user)
    inputs = await _lineup_prompt_inputs(team, league, db)
    await record_ai_usage(db, "lineup", league_id=team.league_id, user_id=current_user.id)
    await db.commit()
    # The background task inherits this request's context, so AIService's
    # cost metering keeps writing tokens/cost onto this (now committed,
    # detached) usage row in memory; _run copies them back to the DB so
    # cost tracking and the daily spend cap still see this call.
    usage_event = ai_cost_service.current_usage_event()
    usage_event_id = usage_event.id if usage_event is not None else None
    summary = f"{team.name} — {league.name}" if league else team.name
    # Same session source the request used (honours test overrides).
    session_dep = request.app.dependency_overrides.get(get_db, get_db)

    async def _run() -> str:
        try:
            analysis = await _get_ai_service().analyze_lineup(**inputs)
        finally:
            if usage_event_id is not None and usage_event is not None:
                async with _job_session(session_dep) as job_db:
                    row = await job_db.get(AIUsageEvent, usage_event_id)
                    if row is not None:
                        row.model = usage_event.model
                        row.input_tokens = usage_event.input_tokens
                        row.output_tokens = usage_event.output_tokens
                        row.cost_usd = usage_event.cost_usd
                        row.error = usage_event.error
                        await job_db.commit()
        async with _job_session(session_dep) as job_db:
            await record_analysis(
                job_db, user_id=current_user.id, analysis_type="lineup",
                league_id=team.league_id, summary=summary, result=analysis,
            )
            await job_db.commit()
        return analysis

    job = ai_jobs.start(current_user.id, "lineup", _run)
    return {"job_id": job.id, "status": job.status}


@router.get("/jobs/{job_id}")
async def get_analysis_job(job_id: str, current_user: User = Depends(get_current_user)):
    """Status of a background analysis job. Only its owner can read it;
    anyone else (or an expired/unknown id) gets the same 404."""
    job = ai_jobs.get(job_id, current_user.id)
    if job is None:
        raise HTTPException(status_code=404, detail="Analysis job not found or expired")
    return job.public()


@router.post("/trade")
@limiter.limit("10/hour")
async def analyze_trade(
    request: Request,
    body: TradeAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get AI evaluation of a proposed trade."""
    result = await db.execute(
        select(Transaction).where(
            Transaction.id == body.trade_id,
            Transaction.type == TransactionType.TRADE,
        )
    )
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    details = trade.details or {}
    target_team_id = details.get("target_team_id")

    proposer_result = await db.execute(select(Team).where(Team.id == trade.team_id))
    proposer = proposer_result.scalar_one_or_none()
    target_result = await db.execute(select(Team).where(Team.id == target_team_id))
    target = target_result.scalar_one_or_none()
    if not proposer or not target:
        raise HTTPException(status_code=404, detail="One of the trading teams no longer exists")

    if current_user.id not in {proposer.owner_id, proposer.co_owner_id, target.owner_id, target.co_owner_id}:
        raise HTTPException(status_code=403, detail="You are not part of this trade")

    league_result = await db.execute(select(League).where(League.id == trade.league_id))
    league = league_result.scalar_one_or_none()
    scoring = (league.scoring_config if league else None) or {}

    offered_ids = details.get("offered_player_ids") or []
    requested_ids = details.get("requested_player_ids") or []
    players_result = await db.execute(
        select(Player).where(Player.id.in_(offered_ids + requested_ids))
    )
    player_map = {p.id: {"name": f"{p.first_name} {p.last_name}", "position": p.position} for p in players_result.scalars().all()}
    offered = [player_map.get(pid, {"name": pid}) for pid in offered_ids]
    requested = [player_map.get(pid, {"name": pid}) for pid in requested_ids]

    standings = await get_standings(trade.league_id, db)
    team_a_coaching = await _coach_summary(proposer, db)
    team_b_coaching = await _coach_summary(target, db)
    team_a_salary = await _salary_summary(proposer, league, db)
    team_b_salary = await _salary_summary(target, league, db)
    team_a_partner = await _partner_summary(proposer, league, db)
    team_b_partner = await _partner_summary(target, league, db)

    await record_ai_usage(db, "trade", league_id=trade.league_id, user_id=current_user.id)
    service = _get_ai_service()
    analysis = await service.analyze_trade(
        team_a_name=proposer.name, team_b_name=target.name,
        team_a_players=offered, team_b_players=requested, scoring=scoring, standings={"standings": standings},
        team_a_coaching=team_a_coaching, team_b_coaching=team_b_coaching,
        team_a_salary=team_a_salary, team_b_salary=team_b_salary,
        team_a_partner=team_a_partner, team_b_partner=team_b_partner,
    )
    await record_analysis(
        db, user_id=current_user.id, analysis_type="trade", league_id=trade.league_id,
        summary=f"{proposer.name} ↔ {target.name}", result=analysis,
    )
    await db.commit()
    return {"analysis": analysis}


@router.post("/bet")
@limiter.limit("10/hour")
async def analyze_bet(
    request: Request,
    body: BetAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Freeform betting-angle analysis. When OpenAI is the configured
    provider, this does REAL live web research (current odds, injury
    reports, snap counts) via AIService._call_openai_search -- not just
    training memory + whatever the user typed. Any player names
    mentioned also get looked up against this app's own synced roster
    data first (see _verified_players_from_text) as a fast, free
    cross-check alongside that search, so the model has real current
    team/position/injury data to ground against too. Falls back to a
    no-search, honestly-hedged prompt for any other/no configured
    provider -- see ai_service.py's BET_ANALYSIS_PROMPT vs.
    BET_ANALYSIS_SEARCH_SYSTEM_PROMPT."""
    verified_players = await _verified_players_from_text(body.prompt, db)
    # No league_id -- this tool isn't scoped to any league (freeform
    # personal betting question). See AIUsageEvent's model docstring.
    await record_ai_usage(db, "bet", user_id=current_user.id)
    service = _get_ai_service()
    analysis = await service.analyze_bet(
        matchup={"description": body.prompt}, lines={}, verified_players=verified_players,
    )
    summary = body.prompt if len(body.prompt) <= 140 else body.prompt[:137] + "..."
    await record_analysis(
        db, user_id=current_user.id, analysis_type="bet", summary=summary, result=analysis,
    )
    await db.commit()
    return {"analysis": analysis}


@router.post("/team-comparison")
@limiter.limit("10/hour")
async def analyze_team_comparison(
    request: Request,
    body: TeamComparisonRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full-season trend comparison between two teams in the same
    league -- see team_comparison_service.build_team_trend for the
    weekly points/consistency/position-group-strength shape. Distinct
    from analyze_lineup's opponent context (a single week's matchup);
    this is deliberately a whole-season read."""
    if body.team_a_id == body.team_b_id:
        raise HTTPException(status_code=422, detail="Pick two different teams to compare")

    a_result = await db.execute(select(Team).where(Team.id == body.team_a_id))
    team_a = a_result.scalar_one_or_none()
    b_result = await db.execute(select(Team).where(Team.id == body.team_b_id))
    team_b = b_result.scalar_one_or_none()
    if not team_a or not team_b:
        raise HTTPException(status_code=404, detail="One of the teams no longer exists")
    if team_a.league_id != team_b.league_id:
        raise HTTPException(status_code=422, detail="Both teams must be in the same league")

    league_result = await db.execute(select(League).where(League.id == team_a.league_id))
    league = league_result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    await require_league_participant(league, current_user, db)

    scoring = league.scoring_config or {}
    team_a_trend = await build_team_trend(team_a, db, scoring)
    team_b_trend = await build_team_trend(team_b, db, scoring)

    await record_ai_usage(db, "team_comparison", league_id=league.id, user_id=current_user.id)
    service = _get_ai_service()
    analysis = await service.analyze_team_comparison(
        league_name=league.name, team_a_trend=team_a_trend, team_b_trend=team_b_trend, scoring=scoring,
    )
    await record_analysis(
        db, user_id=current_user.id, analysis_type="team_compare", league_id=league.id,
        summary=f"{team_a.name} vs {team_b.name}", result=analysis,
    )
    await db.commit()
    return {"analysis": analysis, "team_a_trend": team_a_trend, "team_b_trend": team_b_trend}


@router.post("/player-comparison")
@limiter.limit("10/hour")
async def analyze_player_comparison(
    request: Request,
    body: PlayerComparisonRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Season-stats start/sit verdict between two players, under one
    specific league's own scoring rules -- see
    player_comparison_service.build_player_profile."""
    if body.player_a_id == body.player_b_id:
        raise HTTPException(status_code=422, detail="Pick two different players to compare")

    league_result = await db.execute(select(League).where(League.id == body.league_id))
    league = league_result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    await require_league_participant(league, current_user, db)

    a_result = await db.execute(select(Player).where(Player.id == body.player_a_id))
    player_a = a_result.scalar_one_or_none()
    b_result = await db.execute(select(Player).where(Player.id == body.player_b_id))
    player_b = b_result.scalar_one_or_none()
    if not player_a or not player_b:
        raise HTTPException(status_code=404, detail="One of the players was not found")

    scoring = league.scoring_config or {}
    profile_a = build_player_profile(player_a, scoring)
    profile_b = build_player_profile(player_b, scoring)

    await record_ai_usage(db, "player_comparison", league_id=league.id, user_id=current_user.id)
    service = _get_ai_service()
    analysis = await service.analyze_player_comparison(player_a=profile_a, player_b=profile_b, scoring=scoring)
    await record_analysis(
        db, user_id=current_user.id, analysis_type="player_compare", league_id=league.id,
        summary=f"{profile_a['name']} vs {profile_b['name']}", result=analysis,
    )
    await db.commit()
    return {"analysis": analysis, "player_a": profile_a, "player_b": profile_b}


def _history_dict(h) -> dict:
    return {
        "id": h.id,
        "league_id": h.league_id,
        "summary": h.summary,
        "result": h.result,
        "created_at": h.created_at.isoformat() if h.created_at else None,
    }


@router.get("/history")
async def get_history(
    analysis_type: str,
    league_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """This user's past results for one AI Analysis tool, newest first
    -- see ai_history_service.py. No LLM call, so unrated (unlike
    /lineup, /trade, /bet above)."""
    if analysis_type not in {"lineup", "trade", "bet", "team_compare", "player_compare"}:
        raise HTTPException(
            status_code=422,
            detail="analysis_type must be one of: lineup, trade, bet, team_compare, player_compare",
        )
    history = await get_analysis_history(
        db, user_id=current_user.id, analysis_type=analysis_type, league_id=league_id,
    )
    return {"history": [_history_dict(h) for h in history]}
