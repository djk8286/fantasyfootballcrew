"""Real Alembic round-trip for b5d1e8f2a7c3 (draft_autopick) on a
throwaway SQLite file: additive table, boolean default stored as 0 (not
TEXT 'false'), one row per (draft, team), clean downgrade."""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent


def _alembic(db_path: Path, *args: str) -> None:
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}"}
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, check=True,
                   capture_output=True, timeout=120)


def _tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_draft_autopick_migration_round_trip(tmp_path):
    db = tmp_path / "ap.db"
    _alembic(db, "upgrade", "a9f3c2e71b40")
    conn = sqlite3.connect(db)
    assert "draft_autopick" not in _tables(conn)
    conn.close()

    _alembic(db, "upgrade", "b5d1e8f2a7c3")
    conn = sqlite3.connect(db)
    assert "draft_autopick" in _tables(conn)
    conn.execute("INSERT INTO draft_autopick (id, draft_id, team_id) VALUES ('a1', 'd1', 't1')")
    assert conn.execute("SELECT enabled, typeof(enabled) FROM draft_autopick").fetchone() == (0, "integer")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO draft_autopick (id, draft_id, team_id) VALUES ('a2', 'd1', 't1')")
    conn.commit()
    conn.close()

    _alembic(db, "downgrade", "a9f3c2e71b40")
    conn = sqlite3.connect(db)
    assert "draft_autopick" not in _tables(conn)
    conn.close()
