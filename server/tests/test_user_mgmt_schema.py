from __future__ import annotations
from server.db import Database


def test_pivot_user_table_exists(tmp_path):
    db = Database(tmp_path / "test.db")
    with db.connect() as conn:
        rows = list(conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('pivot_user','external_binding','join_application','invite')"
        ))
    assert {r[0] for r in rows} == {
        "pivot_user", "external_binding", "join_application", "invite"
    }


def test_pivot_user_columns(tmp_path):
    db = Database(tmp_path / "test.db")
    with db.connect() as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(pivot_user)")}
    expected = {
        "id", "display_name", "pinyin", "email", "avatar_url",
        "github_username", "role", "status", "status_note",
        "created_at", "updated_at", "last_login_at",
        "status_changed_at", "status_changed_by",
    }
    assert expected.issubset(cols)


def test_external_binding_unique_provider_external_id(tmp_path):
    db = Database(tmp_path / "test.db")
    with db.connect() as conn:
        # First insert OK
        conn.execute(
            "INSERT INTO pivot_user (id, display_name, pinyin, role, status,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            ("u1", "Alice", "alice", "member", "active", 1.0, 1.0),
        )
        conn.execute(
            "INSERT INTO external_binding (id, pivot_user_id, provider, external_id, bound_at)"
            " VALUES (?,?,?,?,?)",
            ("b1", "u1", "feishu", "ou_xxx", 1.0),
        )
        # Duplicate (provider, external_id) must raise
        import sqlite3
        try:
            conn.execute(
                "INSERT INTO external_binding (id, pivot_user_id, provider, external_id, bound_at)"
                " VALUES (?,?,?,?,?)",
                ("b2", "u1", "feishu", "ou_xxx", 2.0),
            )
            raise AssertionError("expected IntegrityError")
        except sqlite3.IntegrityError:
            pass
