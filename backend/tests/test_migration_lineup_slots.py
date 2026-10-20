"""Real Alembic round-trip for b7d1e4f9a2c6 (lineups.slots), chained after
b5d1e8f2a7c3 (draft_autopick), plus a single-head guard so two branches
adding migrations on the same parent fail CI instead of prod deploy."""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND = Path(__file__).resolve().parent.parent


def _alembic(db_path: Path, *args: str) -> None:
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}"}
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, check=True,
                   capture_output=True, timeout=120)


def _lineup_cols(db_path: Path) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        return {r[1] for r in conn.execute("PRAGMA table_info(lineups)")}
    finally:
        conn.close()


def test_single_alembic_head():
    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    assert len(script.get_heads()) == 1, script.get_heads()


def test_lineup_slots_chained_after_draft_autopick():
    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    assert script.get_revision("b7d1e4f9a2c6").down_revision == "b5d1e8f2a7c3"


def test_lineup_slots_migration_round_trip(tmp_path):
    db = tmp_path / "slots.db"
    _alembic(db, "upgrade", "b5d1e8f2a7c3")
    assert "slots" not in _lineup_cols(db)
    _alembic(db, "upgrade", "b7d1e4f9a2c6")
    assert "slots" in _lineup_cols(db)
    _alembic(db, "downgrade", "b5d1e8f2a7c3")
    assert "slots" not in _lineup_cols(db)
