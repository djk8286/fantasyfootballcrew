"""
Real Alembic round-trip for d5e8f1a3b7c2 (user suspension + admin audit
log) against a throwaway SQLite file -- guards the SQLite boolean
server_default trap (a literal 'false' string is stored as TEXT and reads
back truthy, which would mark every existing user suspended).
"""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent


def _alembic(db_path: Path, *args: str) -> None:
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}"}
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, check=True, capture_output=True)


def test_suspension_migration_upgrades_downgrades_and_backfills_false(tmp_path):
    db = tmp_path / "mig.db"
    _alembic(db, "upgrade", "c41a7e2b9d10")
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO users (id, email, username, provider, token_version, email_verified, is_admin) "
                 "VALUES ('u1', 'a@b.c', 'existing', 'email', 0, 1, 0)")
    conn.commit()
    conn.close()

    _alembic(db, "upgrade", "d5e8f1a3b7c2")
    conn = sqlite3.connect(db)
    value, kind = conn.execute("SELECT is_suspended, typeof(is_suspended) FROM users WHERE id='u1'").fetchone()
    assert (value, kind) == (0, "integer")
    assert conn.execute("SELECT count(*) FROM sqlite_master WHERE name='admin_audit_logs'").fetchone()[0] == 1
    conn.close()

    _alembic(db, "downgrade", "c41a7e2b9d10")
    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    assert "is_suspended" not in cols and "suspended_at" not in cols
    assert conn.execute("SELECT count(*) FROM sqlite_master WHERE name='admin_audit_logs'").fetchone()[0] == 0
    assert conn.execute("SELECT username FROM users WHERE id='u1'").fetchone()[0] == "existing"
    conn.close()
