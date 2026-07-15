"""
Draft Manager — the core business logic for snake and mock drafts.
Handles draft creation, pick making, snake order generation, and mock AI picks.
"""
import json
import random
import math
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from app.models.draft import Draft, DraftPick, DraftRunStatus
from app.models.team import Team
from app.models.player import Player
from app.models.league import League


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
    # Get draft
    result = await db.execute(select(Draft).where(Draft.id == draft_id))
    draft = result.scalar_one_or_none()
    if not draft:
        raise ValueError("Draft not found")
    if draft.status != DraftRunStatus.IN_PROGRESS:
        raise ValueError("Draft is not in progress")

    team_order = json.loads(draft.team_order)
    global_pick = (draft.current_round - 1) * 0 + draft.current_pick
    # Recalculate properly
    # Get number of teams
    result = await db.execute(select(Team).where(Team.league_id == draft.league_id))
    teams = result.scalars().all()
    num_teams = len(teams)
    
    # Calculate global pick index
    pick_index = (draft.current_round - 1) * num_teams + (draft.current_pick - 1)
    
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

    # Make the pick
    round_num = draft.current_round
    pick_num = draft.current_pick
    global_pick_number = pick_index + 1

    draft_pick = DraftPick(
        draft_id=draft_id,
        league_id=draft.league_id,
        team_id=team_id,
        player_id=player_id,
        round=round_num,
        pick_number=global_pick_number,
    )
    db.add(draft_pick)

    # Advance draft state
    if pick_num >= num_teams:
        draft.current_round += 1
        draft.current_pick = 1
    else:
        draft.current_pick += 1

    # Check if draft is complete
    if draft.current_round > draft.total_rounds:
        draft.status = DraftRunStatus.COMPLETED
    else:
        # Reset the pick timer for the next team
        draft.current_pick_started_at = datetime.now(timezone.utc)

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

    # Get available players (not drafted) — sort by fantasy relevance and rank
    from sqlalchemy import case
    pos_priority = case(
        {v: i for i, v in enumerate(["RB", "WR", "QB", "TE", "K", "DEF", "DB", "DL", "LB"])},
        value=Player.position,
        else_=99
    )
    available_query = (
        select(Player)
        .where(~Player.id.in_(drafted_ids))
        .order_by(pos_priority, Player.last_name)
        .limit(10000)
    )
    result = await db.execute(available_query)
    available_players = result.scalars().all()

    # Get proper sequential ranks for all players
    tier_names = get_tier_names()
    sequential_rankings = build_sequential_ranking(tier_names)

    def get_player_rank_from_list(full_name: str) -> int:
        """Get actual sequential rank from the master ranking."""
        name_lower = full_name.lower()
        for rank, ranked_name in sequential_rankings:
            name_check = ranked_name.lower()
            if name_check in name_lower or name_lower in name_check:
                return rank
        # Unknown player: rank after all known players
        return 1000
    
    # Sort by rank (now truly sequential), then position priority
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

    # Build pick details with player info
    picks_with_players = []
    for p in picks:
        player_result = await db.execute(select(Player).where(Player.id == p.player_id))
        player = player_result.scalar_one_or_none()
        team_result = await db.execute(select(Team).where(Team.id == p.team_id))
        team = team_result.scalar_one_or_none()
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
                "rank_score": get_player_rank_from_list(f"{player.first_name} {player.last_name}") if player else 0,
                "pos_rank": pos_rank_map.get(player.id, 0) if player else 0,
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
                "avatar_url": f"https://sleepercdn.com/content/nfl/players/{p.sleeper_id}.jpg" if p.sleeper_id else None,
                "sleeper_id": p.sleeper_id,
                "bye_week": p.bye_week,
                "injury_status": p.injury_status,
                "fantasy_positions": p.fantasy_positions,
                "rank_score": get_player_rank_from_list(f"{p.first_name} {p.last_name}"),
                "pos_rank": pos_rank_map.get(p.id, 0),
            }
            for p in available_players
        ],
    }


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
    for p in team_picks:
        presult = await db.execute(select(Player).where(Player.id == p.player_id))
        player = presult.scalar_one_or_none()
        if player:
            team_positions[player.position] = team_positions.get(player.position, 0) + 1

    tier_names = get_tier_names()

    # Tier scores
    def get_player_tier(full_name: str) -> int:
        name_lower = full_name.lower()
        for name_set, tier in [(tier_names["tier1"], 1), (tier_names["tier2"], 2), (tier_names["tier3"], 3), (tier_names["tier4"], 4)]:
            for n in name_set:
                if n.lower() in name_lower or name_lower in n.lower():
                    return tier
        return 5  # Unknown player

    # Get available players
    result = await db.execute(
        select(Player).where(~Player.id.in_(drafted_ids))
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
