from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts.migrate_user_management import migrate


def _seed_legacy_db(path: Path) -> None:
    """Build a v0 schema db with sample data."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE users (
            open_id TEXT PRIMARY KEY, union_id TEXT, name TEXT NOT NULL,
            avatar_url TEXT NOT NULL DEFAULT '',
            pinyin TEXT, github_username TEXT, created_at REAL NOT NULL
        );
        CREATE TABLE drafts (id TEXT PRIMARY KEY, user_open_id TEXT NOT NULL, body TEXT);
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, user_open_id TEXT NOT NULL,
            expires_at REAL NOT NULL, created_at REAL NOT NULL
        );
        CREATE TABLE file_reads (
            user_open_id TEXT NOT NULL, matter_id TEXT NOT NULL,
            filename TEXT NOT NULL, first_read_at REAL NOT NULL,
            PRIMARY KEY (user_open_id, matter_id, filename)
        );
    """)
    conn.execute(
        "INSERT INTO users VALUES (?,?,?,?,?,?,?)",
        ("ou_alice", "on_alice", "Alice", "", "alice", None, 1.0),
    )
    conn.execute(
        "INSERT INTO users VALUES (?,?,?,?,?,?,?)",
        ("ou_bob", "on_bob", "Bob", "", "bob", "bob_gh", 2.0),
    )
    conn.execute("INSERT INTO drafts VALUES (?,?,?)", ("d1", "ou_alice", "..."))
    conn.execute("INSERT INTO sessions VALUES (?,?,?,?)",
                 ("s1", "ou_alice", 9999.0, 1.0))
    conn.execute("INSERT INTO file_reads VALUES (?,?,?,?)",
                 ("ou_bob", "m1", "a.md", 1.5))
    conn.commit()
    conn.close()


def test_dry_run_does_not_write(tmp_path):
    db_path = tmp_path / "data.db"
    _seed_legacy_db(db_path)
    result = migrate(db_path=db_path, initial_admin_pinyin="alice", dry_run=True)
    assert result.success
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert "pivot_user" not in tables
    # ALTER TABLE additions also rolled back:
    draft_cols = {r[1] for r in conn.execute("PRAGMA table_info(drafts)")}
    assert "pivot_user_id" not in draft_cols
    session_cols = {r[1] for r in conn.execute("PRAGMA table_info(sessions)")}
    assert "pivot_user_id" not in session_cols
    conn.close()


def test_full_migration_creates_tables_and_promotes_admin(tmp_path):
    db_path = tmp_path / "data.db"
    _seed_legacy_db(db_path)
    result = migrate(db_path=db_path, initial_admin_pinyin="alice", dry_run=False)
    assert result.success
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    pivot_users = list(conn.execute("SELECT * FROM pivot_user"))
    assert len(pivot_users) == 2
    alice = conn.execute(
        "SELECT * FROM pivot_user WHERE pinyin='alice'"
    ).fetchone()
    assert alice["role"] == "admin"
    bob = conn.execute(
        "SELECT * FROM pivot_user WHERE pinyin='bob'"
    ).fetchone()
    assert bob["role"] == "member"
    bindings = list(conn.execute(
        "SELECT * FROM external_binding WHERE provider='feishu'"
    ))
    assert len(bindings) == 2
    # users table dropped
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert "users" not in tables
    conn.close()


def test_initial_admin_no_match_aborts(tmp_path):
    db_path = tmp_path / "data.db"
    _seed_legacy_db(db_path)
    result = migrate(db_path=db_path, initial_admin_pinyin="nobody", dry_run=False)
    assert not result.success
    assert "no user with pinyin" in result.error.lower()
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    conn.close()
    assert "pivot_user" not in tables  # rolled back


def test_orphan_fk_aborts(tmp_path):
    db_path = tmp_path / "data.db"
    _seed_legacy_db(db_path)
    # Insert orphan draft
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO drafts VALUES (?,?,?)", ("d2", "ou_ghost", "..."))
    conn.commit()
    conn.close()
    result = migrate(db_path=db_path, initial_admin_pinyin="alice", dry_run=False)
    assert not result.success
    assert "orphan" in result.error.lower()


def test_orphan_in_file_reads_aborts(tmp_path):
    """file_reads must be in _DOWNSTREAM_TABLES so its orphans abort migration."""
    db_path = tmp_path / "data.db"
    _seed_legacy_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO file_reads VALUES (?,?,?,?)",
                 ("ou_ghost", "m1", "b.md", 2.0))
    conn.commit()
    conn.close()
    result = migrate(db_path=db_path, initial_admin_pinyin="alice", dry_run=False)
    assert not result.success
    assert "orphan" in result.error.lower()
    assert "file_reads" in result.error.lower()


def test_sessions_rewritten_not_cleared(tmp_path):
    db_path = tmp_path / "data.db"
    _seed_legacy_db(db_path)
    migrate(db_path=db_path, initial_admin_pinyin="alice", dry_run=False)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    sessions = list(conn.execute("SELECT * FROM sessions"))
    conn.close()
    assert len(sessions) == 1  # still there
    # New column populated
    assert sessions[0]["pivot_user_id"] is not None


def test_initial_admin_ambiguous_aborts(tmp_path):
    db_path = tmp_path / "data.db"
    _seed_legacy_db(db_path)
    # Add a second user with the same pinyin "alice"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO users VALUES (?,?,?,?,?,?,?)",
        ("ou_alice2", "on_alice2", "Alice2", "", "alice", None, 3.0),
    )
    conn.commit()
    conn.close()
    result = migrate(db_path=db_path, initial_admin_pinyin="alice", dry_run=False)
    assert not result.success
    assert "ambiguous" in result.error.lower()
    # And no pivot_user table created (rolled back)
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    conn.close()
    assert "pivot_user" not in tables
