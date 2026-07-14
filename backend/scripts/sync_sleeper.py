"""
Run the Sleeper player sync to populate the database with NFL players.
Filters to fantasy-relevant positions only (QB, RB, WR, TE, K, DEF).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import httpx
from sqlalchemy import select
from app.core.database import async_session, engine, Base
from app.models.player import Player
from app.services.sleeper_sync import SLEEPER_API

FANTASY_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF", "FB", "DB", "DL", "LB", "DE", "DT", "CB", "S", "FS", "SS"}
POSITION_MAP = {
    "FB": "RB",
    "DB": "DB",
    "DL": "DL",
    "DE": "DL",
    "DT": "DL",
    "LB": "LB",
    "OLB": "LB",
    "ILB": "LB",
    "CB": "DB",
    "S": "DB",
    "FS": "DB",
    "SS": "DB",
}


async def sync_players():
    # Create tables if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with httpx.AsyncClient() as client:
        print("🔄 Fetching players from Sleeper API...")
        response = await client.get(f"{SLEEPER_API}/players/nfl", timeout=60)
        players_data = response.json()
        print(f"📦 Total from API: {len(players_data)}")

    count = 0
    skipped = 0
    async with async_session() as db:
        for sleeper_id, data in players_data.items():
            position = data.get("position", "UNKNOWN")
            if position not in FANTASY_POSITIONS:
                skipped += 1
                continue

            if not data.get("first_name") or not data.get("last_name"):
                skipped += 1
                continue

            # Map exotic positions to standard ones
            mapped_position = POSITION_MAP.get(position, position)
            full_name = f"{data['first_name']} {data['last_name']}"

            # Check if player exists
            result = await db.execute(
                select(Player).where(Player.sleeper_id == sleeper_id)
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.team = data.get("team") or existing.team
                existing.injury_status = data.get("injury_status") or existing.injury_status
                existing.bye_week = data.get("bye_week") or existing.bye_week
            else:
                player = Player(
                    sleeper_id=sleeper_id,
                    first_name=data.get("first_name", ""),
                    last_name=data.get("last_name", ""),
                    position=mapped_position,
                    team=data.get("team"),
                    bye_week=data.get("bye_week"),
                    injury_status=data.get("injury_status"),
                    fantasy_positions=data.get("fantasy_positions"),
                    age=data.get("age"),
                    number=data.get("number"),
                )
                db.add(player)

            count += 1
            if count % 500 == 0:
                print(f"  ✅ {count} players processed...")
                await db.flush()

        await db.commit()

    print(f"\n{'='*40}")
    print(f"✅ Sync complete!")
    print(f"  Players synced: {count}")
    print(f"  Skipped (non-fantasy): {skipped}")
    print(f"{'='*40}")

    # Show counts by position
    async with async_session() as db:
        from sqlalchemy import func as sfunc
        result = await db.execute(
            select(Player.position, sfunc.count(Player.id))
            .group_by(Player.position)
            .order_by(sfunc.count(Player.id).desc())
        )
        print("\n📊 Players by position:")
        for pos, cnt in result:
            print(f"  {pos}: {cnt}")


asyncio.run(sync_players())
