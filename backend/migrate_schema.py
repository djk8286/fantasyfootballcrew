"""Migration: Add new columns to teams and leagues tables."""
import sqlite3
import sys

DB_PATH = "D:\\fantasyfootballcrew\\backend\\ffc.db"


def migration():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Check teams table
    c.execute("PRAGMA table_info(teams)")
    team_cols = {row[1] for row in c.fetchall()}
    print(f"Teams columns: {team_cols}")

    if "avatar_url" not in team_cols:
        c.execute("ALTER TABLE teams ADD COLUMN avatar_url VARCHAR")
        print("  + Added avatar_url to teams")
    if "is_cpu" not in team_cols:
        c.execute("ALTER TABLE teams ADD COLUMN is_cpu BOOLEAN DEFAULT 0")
        print("  + Added is_cpu to teams")

    # Check leagues table
    c.execute("PRAGMA table_info(leagues)")
    league_cols = {row[1] for row in c.fetchall()}
    print(f"Leagues columns: {league_cols}")

    if "co_commissioner_ids" not in league_cols:
        c.execute("ALTER TABLE leagues ADD COLUMN co_commissioner_ids JSON")
        print("  + Added co_commissioner_ids to leagues")

    conn.commit()
    conn.close()
    print("Migration complete!")


if __name__ == "__main__":
    migration()
