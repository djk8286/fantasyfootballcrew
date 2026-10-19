"""Real Alembic round-trip for a9f3c2e71b40 (fantasy golf tables +
leagues.sport) on a throwaway SQLite file. Guards the boolean
server_default trap (must store integer 0, not TEXT 'false') and the
'nfl' backfill for existing leagues."""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
GOLF_TABLES = ["golf_tournaments", "golfers", "golf_field_entries", "golf_picks", "golf_team_event_results"]


def _alembic(db_path: Path, *args: str) -> None:
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}"}
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, check=True,
                   capture_output=True, timeout=120)


def _tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_golf_migration_round_trip(tmp_path):
    db = tmp_path / "golf.db"
    _alembic(db, "upgrade", "c4e6a8b0d2f3")
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO users (id, email, username, provider, token_version, email_verified, is_admin, is_suspended) "
                 "VALUES ('u1', 'a@b.c', 'u', 'email', 0, 1, 0, 0)")
    conn.execute("INSERT INTO leagues (id, name, commissioner_id, league_type, max_teams, draft_status, draft_type, is_mock) VALUES ('l1', 'Existing', 'u1', 'STANDARD', 12, 'NOT_STARTED', 'SNAKE', 0)")
    conn.commit()
    conn.close()

    _alembic(db, "upgrade", "a9f3c2e71b40")
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT sport FROM leagues WHERE id='l1'").fetchone()[0] == "nfl"
    assert set(GOLF_TABLES) <= _tables(conn)
    conn.execute("INSERT INTO golf_tournaments (id, espn_event_id, name, season, start_date) "
                 "VALUES ('t1', '401850916', 'Baycurrent', 2026, '2026-10-09')")
    conn.execute("INSERT INTO golfers (id, espn_athlete_id, full_name) VALUES ('g1', '4921329', 'M B')")
    conn.commit()
    assert conn.execute("SELECT is_major, typeof(is_major), status FROM golf_tournaments").fetchone() == (0, "integer", "scheduled")
    assert conn.execute("SELECT is_amateur, typeof(is_amateur) FROM golfers").fetchone() == (0, "integer")
    conn.close()

    _alembic(db, "downgrade", "c4e6a8b0d2f3")
    conn = sqlite3.connect(db)
    assert not (set(GOLF_TABLES) & _tables(conn))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(leagues)")}
    assert "sport" not in cols
    assert conn.execute("SELECT name FROM leagues WHERE id='l1'").fetchone()[0] == "Existing"
    # Downgrading golf must leave its parent (cookie-auth refresh_tokens) intact.
    assert "refresh_tokens" in _tables(conn)
    conn.close()
