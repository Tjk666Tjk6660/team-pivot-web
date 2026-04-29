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

    def get_all(self, user_open_id: str) -> dict[str, str]:
        """Returns every preference set by this user as {key: value}.
        Missing keys simply don't appear in the dict."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT key, value FROM user_preferences WHERE user_open_id=?",
                (user_open_id,),
            ).fetchall()
        return {r["key"]: r["value"] for r in rows}

    def get(self, user_open_id: str, key: str) -> str | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT value FROM user_preferences"
                " WHERE user_open_id=? AND key=?",
                (user_open_id, key),
            ).fetchone()
        return row["value"] if row else None

    def set(self, user_open_id: str, key: str, value: str) -> None:
        """Upsert. Always overwrites the previous value for (user, key)."""
        with self._db.connect() as conn:
            conn.execute(
                "INSERT INTO user_preferences (user_open_id, key, value, updated_at)"
                " VALUES (?,?,?,?)"
                " ON CONFLICT(user_open_id, key) DO UPDATE SET"
                "   value=excluded.value, updated_at=excluded.updated_at",
                (user_open_id, key, value, time()),
            )
