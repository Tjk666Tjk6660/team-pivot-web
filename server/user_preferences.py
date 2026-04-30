"""Per-user preferences key-value store.

Generic small KV table (`user_preferences`) for short personal settings —
the API layer enforces a key whitelist so this doesn't grow into a
"settings dumping ground". First key registered: `matter_list_filter`.
"""

from __future__ import annotations

from time import time

from server.db import Database


class UserPreferenceRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get_all(self, pivot_user_id: str) -> dict[str, str]:
        """Returns every preference set by this user as {key: value}.
        Missing keys simply don't appear in the dict."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT key, value FROM user_preferences WHERE pivot_user_id=?",
                (pivot_user_id,),
            ).fetchall()
        return {r["key"]: r["value"] for r in rows}

    def get(self, pivot_user_id: str, key: str) -> str | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT value FROM user_preferences"
                " WHERE pivot_user_id=? AND key=?",
                (pivot_user_id, key),
            ).fetchone()
        return row["value"] if row else None

    def set(self, pivot_user_id: str, key: str, value: str) -> None:
        """Upsert. Always overwrites the previous value for (user, key)."""
        with self._db.connect() as conn:
            conn.execute(
                "INSERT INTO user_preferences (pivot_user_id, key, value, updated_at)"
                " VALUES (?,?,?,?)"
                " ON CONFLICT(pivot_user_id, key) DO UPDATE SET"
                "   value=excluded.value, updated_at=excluded.updated_at",
                (pivot_user_id, key, value, time()),
            )
