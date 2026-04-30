from __future__ import annotations

from server.db import Database


def test_acl_cache_tables_exist(tmp_path):
    db = Database(tmp_path / "test.db")
    expected = {
        "category_visibility_cache",
        "category_visibility_role_cache",
        "matter_visibility_cache",
        "matter_visibility_role_cache",
        "matter_visibility_user_cache",
    }
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    assert expected.issubset({row["name"] for row in rows})


def test_pivot_user_role_accepts_json_array(tmp_path):
    db = Database(tmp_path / "test.db")
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO pivot_user"
            " (id, display_name, pinyin, role, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, 'active', 1.0, 1.0)",
            ("u1", "Alice", "alice", '["member","技术部门"]'),
        )
        row = conn.execute("SELECT role FROM pivot_user WHERE id='u1'").fetchone()
    assert row["role"] == '["member","技术部门"]'
