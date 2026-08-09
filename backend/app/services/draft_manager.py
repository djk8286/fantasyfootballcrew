"""
Draft Manager — the core business logic for snake and mock drafts.
Handles draft creation, pick making, snake order generation, and mock AI picks.
"""
import json
import random
import math
import re
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, update
from app.models.draft import Draft, DraftPick, DraftRunStatus
from app.models.team import Team
from app.models.player import Player
from app.models.league import League, DraftStatus
from app.services.sleeper_sync import sleeper_avatar_url, headline_stats as compute_headline_stats
from app.services.scoring_engine import calculate_player_score


# Positions the scoring engine (DEFAULT_SCORING) actually has point values
# for. The synced player pool also contains individual-defense/O-line
# positions (CB, DE, DT, OL, G, OT, T, OLB, C, SS, P, FS, LS, ILB, FB, NT,
# OG, S, ...) that this app cannot currently score at all -- those are
# excluded from the draft pool, not from general player browsing/search.
FANTASY_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}


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

    # A league should only ever have one real draft. Without this guard,
    # anyone hitting POST /drafts for a league that already has one (e.g. a
    # stale "Start Draft" button that hadn't yet learned the draft was
    # already underway/done) creates a second, independent Draft -- and
    # since team.roster accumulates picks by player ID across *all* drafts
    # for that team, the two drafts' rosters silently merge into one
    # oversized roster. Confirmed in production: a league with 5 separate
    # Draft rows for the same 14 teams, one team's roster showing 27
    # players instead of 15.
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
    await db.commit()
    await db.refresh(draft)
    return draft


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
) -> DraftPick:
    """
    Make a draft pick. Verifies:
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
    result = await db.execute(select(Draft).where(Draft.id == draft_id).with_for_update())
    draft = result.scalar_one_or_none()
    if not draft:
        raise ValueError("Draft not found")
    if draft.status != DraftRunStatus.IN_PROGRESS:
        raise ValueError("Draft is not in progress")

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
    if is_complete:
        league_result = await db.execute(select(League).where(League.id == draft.league_id))
        league = league_result.scalar_one_or_none()
        if league:
            league.draft_status = DraftStatus.COMPLETED

    # Add player to team's roster
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if team:
        if not team.roster:
            team.roster = []
        if player_id not in team.roster:
            team.roster.append(player_id)

    await db.commit()
    await db.refresh(draft_pick)
    return draft_pick


async def get_draft_state(db: AsyncSession, draft_id: str) -> dict:
    """Get full draft state including all picks and current team."""
    result = await db.execute(select(Draft).where(Draft.id == draft_id))
    draft = result.scalar_one_or_none()
    if not draft:
        raise ValueError("Draft not found")

    league_result = await db.execute(select(League).where(League.id == draft.league_id))
    league = league_result.scalar_one_or_none()
    scoring_config = (league.scoring_config or {}) if league else {}

    team_order = json.loads(draft.team_order)
    
    # Get number of teams
    result = await db.execute(select(Team).where(Team.league_id == draft.league_id))
    teams = list(result.scalars().all())
    num_teams = len(teams)
    
    # Get all picks made so far
    result = await db.execute(
        select(DraftPick).where(DraftPick.draft_id == draft_id).order_by(DraftPick.pick_number)
    )
    picks = result.scalars().all()

    # Get drafted player IDs
    drafted_ids = [p.player_id for p in picks]

    # Get current pick index
    pick_index = (draft.current_round - 1) * num_teams + (draft.current_pick - 1)
    current_team_id = team_order[pick_index] if pick_index < len(team_order) else None

    # Get available players (not drafted) — sort by fantasy relevance and rank.
    # Scoped to positions the scoring engine actually scores (FANTASY_POSITIONS,
    # module level) -- without this, ~65% of the synced player pool (CB/DE/DT/
    # OL/G/OT/etc., none of which DEFAULT_SCORING has any keys for) was loaded,
    # ranked, and shipped in this response for no reason, on an endpoint the
    # frontend polls every 5 seconds during a live draft.
    from sqlalchemy import case
    pos_priority = case(
        {v: i for i, v in enumerate(["RB", "WR", "QB", "TE", "K", "DEF"])},
        value=Player.position,
        else_=99
    )
    available_query = (
        select(Player)
        .where(~Player.id.in_(drafted_ids), Player.position.in_(FANTASY_POSITIONS))
        .order_by(pos_priority, Player.last_name)
        .limit(10000)
    )
    result = await db.execute(available_query)
    available_players = result.scalars().all()

    # Sort by rank (now truly sequential), then position priority.
    # get_player_rank_from_list is an O(1) precomputed lookup (see module
    # level) -- it used to rebuild the tier list and linearly substring-scan
    # it for every one of these players on every call.
    pos_order = ["RB", "WR", "QB", "TE", "K", "DEF", "DB", "DL", "LB"]
    def sort_key(p: Player) -> tuple:
        full_name = f"{p.first_name} {p.last_name}"
        rank = get_player_rank_from_list(full_name)
        pos_idx = pos_order.index(p.position) if p.position in pos_order else 99
        return (rank, pos_idx, p.last_name or "")

    available_players = sorted(available_players, key=sort_key)

    # Compute position ranks: RB1, RB2, ... WR1, WR2, ...
    pos_ranks: dict[str, int] = {}
    pos_rank_map: dict[str, int] = {}
    for p in available_players:
        pos = p.position
        pos_ranks[pos] = pos_ranks.get(pos, 0) + 1
        pos_rank_map[p.id] = pos_ranks[pos]

    # Build pick details with player info. Batch-fetch every player/team
    # referenced by these picks in 2 queries total instead of 2 queries PER
    # pick (an N+1 that grew every round -- 40+ sequential round trips by
    # round 10 of a 12-team draft, on an endpoint polled every 5s).
    pick_player_ids = {p.player_id for p in picks}
    pick_team_ids = {p.team_id for p in picks}
    picked_players_by_id: dict[str, Player] = {}
    if pick_player_ids:
        # Reuse available_players where possible -- most picks reference
        # players NOT in available_players (they're drafted), so this is
        # still a real lookup for the drafted set specifically.
        result = await db.execute(select(Player).where(Player.id.in_(pick_player_ids)))
        picked_players_by_id = {pl.id: pl for pl in result.scalars().all()}
    picked_teams_by_id: dict[str, Team] = {t.id: t for t in teams if t.id in pick_team_ids}

    picks_with_players = []
    for p in picks:
        player = picked_players_by_id.get(p.player_id)
        team = picked_teams_by_id.get(p.team_id)
        picks_with_players.append({
            "id": p.id,
            "round": p.round,
            "pick_number": p.pick_number,
            "player": {
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
                "headline_stats": compute_headline_stats(player.position, player.stats) if player else {},
                "stats": player.stats if player else None,
                "rank_score": get_player_rank_from_list(f"{player.first_name} {player.last_name}") if player else 0,
                "pos_rank": pos_rank_map.get(player.id, 0) if player else 0,
                "season_points": calculate_player_score(player.stats or {}, scoring_config, player.position) if player else None,
            },
            "team": {
                "id": team.id if team else None,
                "name": team.name if team else "Unknown",
            },
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
            "current_pick_started_at": (
                draft.current_pick_started_at.isoformat() if draft.current_pick_started_at.tzinfo
                else draft.current_pick_started_at.isoformat() + "+00:00"
            ) if draft.current_pick_started_at else None,
        },
        "picks": picks_with_players,
        "current_team_id": current_team_id,
        "current_team_name": next((t.name for t in teams if t.id == current_team_id), None),
        "teams": {t.id: {"name": t.name} for t in teams},
        "team_order": team_order,
        "claimed_teams": {t.id: t.owner_id for t in teams if t.owner_id is not None},
        "available_players": [
            {
                "id": p.id,
                "full_name": f"{p.first_name} {p.last_name}",
                "first_name": p.first_name,
                "last_name": p.last_name,
                "position": p.position,
                "team": p.team or "FA",
                "age": p.age,
                "number": p.number,
                "avatar_url": sleeper_avatar_url(p.sleeper_id),
                "sleeper_id": p.sleeper_id,
                "bye_week": p.bye_week,
                "injury_status": p.injury_status,
                "fantasy_positions": p.fantasy_positions,
                "headline_stats": compute_headline_stats(p.position, p.stats),
                "stats": p.stats,
                "rank_score": get_player_rank_from_list(f"{p.first_name} {p.last_name}"),
                "pos_rank": pos_rank_map.get(p.id, 0),
                "season_points": calculate_player_score(p.stats or {}, scoring_config, p.position),
            }
            for p in available_players
        ],
    }


_SUFFIX_RE = re.compile(r"\s+(jr\.?|sr\.?|ii|iii|iv|v)$", re.IGNORECASE)


def _normalize_name(name: str) -> str:
    """Lowercase and strip a trailing generational suffix, for matching a
    synced player's name against the static tier lists below."""
    return _SUFFIX_RE.sub("", name.strip().lower())


def build_sequential_ranking(tier_names: dict) -> list[tuple[int, str]]:
    """Build a sequential ranking list from tier names.
    Returns [(rank, player_name), ...] where rank starts at 1 and increments.
    Players are ordered: tier1 → tier2 → tier3 → tier4, 
    and alphabetically within each tier.
    """
    ranking = []
    rank = 1
    for tier_key in ["tier1", "tier2", "tier3", "tier4"]:
        names = sorted(tier_names[tier_key])
        for name in names:
            ranking.append((rank, name))
            rank += 1
    return ranking


def get_tier_names() -> dict:
    """Return tiered NFL player names for ranking. Used by both draft state and AI picks."""
    return {
        "tier1": {
            "Christian McCaffrey", "Patrick Mahomes", "Josh Allen", "Tyreek Hill",
            "Justin Jefferson", "Ja'Marr Chase", "Travis Kelce", "CeeDee Lamb",
            "Amon-Ra St. Brown", "Bijan Robinson", "Saquon Barkley", "Puka Nacua",
            "Jalen Hurts", "Lamar Jackson", "Garrett Wilson", "Davante Adams",
            "Derrick Henry", "A.J. Brown", "Sam LaPorta", "Trey McBride",
            "Jonathan Taylor", "Breece Hall", "Jahmyr Gibbs", "Kyren Williams",
            "De'Von Achane", "Marvin Harrison Jr.", "Malik Nabers", "Rome Odunze",
            "C.J. Stroud", "Joe Burrow", "Dak Prescott", "Kyler Murray",
        },
        "tier2": {
            "Travis Etienne", "Rachaad White", "Kenneth Walker III", "Isiah Pacheco",
            "Aaron Jones", "James Cook", "Joe Mixon", "Josh Jacobs",
            "D'Andre Swift", "Najee Harris", "Alvin Kamara", "Tony Pollard", 
            "David Montgomery", "Jaylen Waddle", "Deebo Samuel", "Cooper Kupp",
            "Keenan Allen", "Mike Evans", "Michael Pittman Jr.", "DJ Moore",
            "Chris Olave", "George Kittle", "Mark Andrews", "Kyle Pitts",
            "Evan Engram", "Jake Ferguson", "Dalton Kincaid", "Brock Bowers",
            "Anthony Richardson", "Tua Tagovailoa", "Jared Goff", "Brock Purdy",
            "Justin Herbert", "Jordan Love", "Trevor Lawrence", "Will Levis",
            "Geno Smith", "Matthew Stafford", "Aaron Rodgers", "Kirk Cousins",
            "Buffalo Bills", "San Francisco 49ers", "Dallas Cowboys",
            "New York Jets", "Kansas City Chiefs", "Baltimore Ravens",
            "Cleveland Browns", "Pittsburgh Steelers",
        },
        "tier3": {
            "Zamir White", "Zack Moss", "Ty Chandler", "Jaylen Warren",
            "Raheem Mostert", "Jerome Ford", "Gus Edwards", "Javonte Williams",
            "Ezekiel Elliott", "Austin Ekeler", "Devin Singletary", "Antonio Gibson",
            "Tyjae Spears", "Chuba Hubbard", "Brian Robinson Jr.", "Alexander Mattison",
            "Khalil Herbert", "Roschon Johnson", "Zach Charbonnet", "Tank Bigsby",
            "Tyler Allgeier", "Keaton Mitchell", "Elijah Mitchell", "Jeff Wilson Jr.",
            "Courtland Sutton", "Tyler Lockett", "Terry McLaurin", "Calvin Ridley",
            "Brandon Aiyuk", "Amari Cooper", "Stefon Diggs", "Christian Kirk",
            "DeAndre Hopkins", "Diontae Johnson", "Jerry Jeudy", "Marquise Brown",
            "Hollywood Brown", "Rashid Shaheed", "Romeo Doubs", "Jameson Williams",
            "Jaxon Smith-Njigba", "Zay Flowers", "Quentin Johnston", "Jordan Addison",
            "Kadarius Toney", "Skyy Moore", "Van Jefferson", "Josh Reynolds",
            "Tucker Kraft", "Luke Musgrave", "Chigoziem Okonkwo", "Jonnu Smith",
            "Cade Otton", "Michael Mayer", "Greg Dulcich", "Hayden Hurst",
            "Tyler Bass", "Justin Tucker", "Harrison Butker", "Brandon Aubrey",
            "Evan McPherson", "Jake Moody", "Younghoe Koo", "Ka'imi Fairbairn",
            "Philadelphia Eagles", "Miami Dolphins", "Cincinnati Bengals",
            "Detroit Lions", "New Orleans Saints", "Houston Texans",
            "Denver Broncos", "Green Bay Packers", "Chicago Bears",
            "Jacksonville Jaguars", "Seattle Seahawks", "Minnesota Vikings",
            "New England Patriots", "Los Angeles Rams", "Tampa Bay Buccaneers",
        },
        "tier4": {
            "Braelon Allen", "Ray Davis", "Trey Benson", "Jonathan Brooks",
            "Jaylen Wright", "MarShawn Lloyd", "Audric Estime", "Blake Corum",
            "Kendre Miller", "Rico Dowdle", "Christian Watson", "Nico Collins",
            "Keon Coleman", "Xavier Legette", "Brian Thomas Jr.", "Adonai Mitchell",
            "Ladd McConkey", "Malachi Corley", "Ricky Pearsall", "Ja'Lynn Polk",
            "Jermaine Burton", "Demario Douglas", "Treylon Burks", "John Metchie III",
            "Jalin Hyatt", "Alec Pierce", "Andrei Iosivas", "Khalil Shakir",
            "Curtis Samuel", "Rondale Moore", "Cedric Tillman", "Justin Watson",
            "Tim Patrick", "Nelson Agholor", "Mecole Hardman",
            "Dameon Pierce", "Kareem Hunt", "Clyde Edwards-Helaire", "Latavius Murray",
            "Tahj Washington", "Jacob Cowing", "Jha'Quan Jackson", "Tanner McLachlan",
            "Theo Johnson", "Cade Stover", "Erick All", "Jaheim Bell",
            "Harrison Bryant", "Brenton Strange", "Brevyn Spann-Ford",
        },
    }


# Precomputed ONCE at import time, not per-request. get_tier_names()/
# build_sequential_ranking() are pure static data -- get_draft_state and
# get_ai_mock_pick used to rebuild them on every single call, then rank
# every available player (up to ~9,400 in production) with a linear
# substring scan over all ~250 known names -- millions of string
# comparisons per request, done synchronously, on a page the frontend
# polls every 5 seconds. This is an O(1) dict lookup instead.
_TIER_NAMES = get_tier_names()
_SEQUENTIAL_RANKINGS = build_sequential_ranking(_TIER_NAMES)
_RANK_BY_NORMALIZED_NAME: dict[str, int] = {
    _normalize_name(name): rank for rank, name in _SEQUENTIAL_RANKINGS
}
_TIER_BY_NORMALIZED_NAME: dict[str, int] = {
    _normalize_name(name): tier
    for tier_key, tier in [("tier1", 1), ("tier2", 2), ("tier3", 3), ("tier4", 4)]
    for name in _TIER_NAMES[tier_key]
}


def get_player_rank_from_list(full_name: str) -> int:
    """Sequential rank (1 = best) for a known star player, else 1000."""
    return _RANK_BY_NORMALIZED_NAME.get(_normalize_name(full_name), 1000)


def get_player_tier(full_name: str) -> int:
    """Tier 1-4 for a known star player, else 5 (unranked)."""
    return _TIER_BY_NORMALIZED_NAME.get(_normalize_name(full_name), 5)


async def get_ai_mock_pick(
    db: AsyncSession,
    draft_id: str,
    team_id: str,
) -> Optional[Player]:
    """
    AI-powered mock draft pick with smart tier-based ranking.
    Uses known NFL player tiers, position scarcity, and team needs.
    """
    result = await db.execute(select(Draft).where(Draft.id == draft_id))
    draft = result.scalar_one_or_none()
    if not draft:
        return None

    # Get already drafted player IDs
    result = await db.execute(
        select(DraftPick.player_id).where(DraftPick.draft_id == draft_id)
    )
    drafted_ids = {row[0] for row in result.all()}

    # Get the team's existing picks this draft
    result = await db.execute(
        select(DraftPick).where(
            DraftPick.draft_id == draft_id,
            DraftPick.team_id == team_id,
        )
    )
    team_picks = result.scalars().all()
    team_positions = {}
    if team_picks:
        # Batch-fetch instead of one query per pick this team has made.
        team_pick_player_ids = {p.player_id for p in team_picks}
        presult = await db.execute(select(Player).where(Player.id.in_(team_pick_player_ids)))
        for player in presult.scalars().all():
            team_positions[player.position] = team_positions.get(player.position, 0) + 1

    # get_player_tier is an O(1) precomputed lookup (see module level) --
    # this used to rebuild the tier dict and linearly substring-scan it for
    # every available player (up to ~9,400 in production) on every call.

    # Get available players. Filtered to FANTASY_POSITIONS at the query level
    # now -- the scoring loop below already skipped anything outside
    # pos_rank's keys, so this is a pure efficiency change (less loaded from
    # the DB and iterated in Python), not a behavior change.
    result = await db.execute(
        select(Player).where(~Player.id.in_(drafted_ids), Player.position.in_(FANTASY_POSITIONS))
    )
    available = result.scalars().all()

    # Position priority by round
    if draft.current_round <= 2:
        # Early: elite RBs, WRs, top QBs
        pos_rank = {"RB": 0, "WR": 1, "TE": 2, "QB": 3, "DEF": 10, "K": 10}
    elif draft.current_round <= 5:
        pos_rank = {"RB": 0, "WR": 0, "QB": 1, "TE": 2, "DEF": 10, "K": 10}
    elif draft.current_round <= 8:
        pos_rank = {"RB": 0, "WR": 0, "TE": 1, "QB": 1, "DEF": 8, "K": 10}
    elif draft.current_round <= 12:
        pos_rank = {"RB": 0, "WR": 0, "TE": 0, "QB": 0, "DEF": 5, "K": 8}
    else:
        pos_rank = {"RB": 0, "WR": 0, "TE": 0, "QB": 0, "DEF": 0, "K": 0}

    # Score each available player
    scored_players = []
    for player in available:
        pos = player.position
        if pos not in pos_rank:
            continue

        full_name = f"{player.first_name} {player.last_name}"
        tier = get_player_tier(full_name)
        
        # Base score from tier (lower tier number = better)
        tier_score = (tier - 1) * 100  # Tier 1 = 0, Tier 5 = 400
        
        # Position priority bonus (lower = better)
        pos_bonus = pos_rank.get(pos, 99) * 10
        
        # Need score — prefer positions not yet filled
        need_penalty = team_positions.get(pos, 0) * 5
        
        # Free agent penalty
        fa_penalty = 30 if (not player.team or player.team in ("FA", "---")) else 0
        
        # Small age bonus for prime (24-28)
        age = player.age or 25
        age_score = 0
        if 24 <= age <= 28:
            age_score = -5  # Small boost
        elif age > 35:
            age_score = 20  # Penalty for very old
        
        total_score = tier_score + pos_bonus + need_penalty + fa_penalty + age_score
        scored_players.append((total_score, player))

    # Sort by score ascending
    scored_players.sort(key=lambda x: x[0])

    if scored_players:
        best_score = scored_players[0][0]
        # Pick from top contenders with some randomness
        top_tier_count = 3 if draft.current_round <= 5 else 5
        top_tier = [p for s, p in scored_players if s <= best_score + 40]
        candidates = top_tier[:max(top_tier_count * 2, 6)]
        return random.choice(candidates)

    return None


async def run_mock_draft(db: AsyncSession, draft_id: str, skip_team_ids: list[str] | None = None) -> list[dict]:
    """Run a mock draft with AI auto-picks.
    
    If skip_team_ids is provided, those teams' picks are left open
    for manual drafting (hybrid mock mode).
    """
    if skip_team_ids is None:
        skip_team_ids = []
    skip_set = set(skip_team_ids)
    
    result = await db.execute(select(Draft).where(Draft.id == draft_id))
    draft = result.scalar_one_or_none()
    if not draft:
        raise ValueError("Draft not found")

    # Start draft if pending
    if draft.status == DraftRunStatus.PENDING:
        await start_draft(db, draft_id)
    
    team_order_list = json.loads(draft.team_order)
    team_result = await db.execute(select(Team).where(Team.league_id == draft.league_id))
    teams_by_id = {t.id: t for t in team_result.scalars().all()}

    all_picks = []
    max_picks = len(team_order_list)
    
    for _ in range(max_picks):
        # Re-fetch draft to get current state
        result = await db.execute(select(Draft).where(Draft.id == draft_id))
        draft = result.scalar_one_or_none()
        
        if draft.status != DraftRunStatus.IN_PROGRESS:
            print(f"DEBUG: draft status is {draft.status} — breaking")
            break
        
        # Get who's picking
        num_teams = len(teams_by_id)
        pick_index = (draft.current_round - 1) * num_teams + (draft.current_pick - 1)
        current_team_id = team_order_list[pick_index]
        
        # If it's a user team's turn — STOP and let them pick manually
        if current_team_id in skip_set:
            print(f"DEBUG: skipping team {current_team_id[:12]}... (in skip_set)")
            break
        
        print(f"DEBUG: Making AI pick for team {current_team_id[:12]}...")
        # Get AI pick
        player = await get_ai_mock_pick(db, draft_id, current_team_id)
        if not player:
            print("DEBUG: No player found")
            break
        
        # Make the pick
        pick = await make_pick(db, draft_id, current_team_id, player.id)
        all_picks.append(pick)
    
    print(f"DEBUG: Returning {len(all_picks)} picks")
    return all_picks
