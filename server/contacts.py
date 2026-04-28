from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from time import time

from server.db import Database


@dataclass(frozen=True)
class Contact:
    open_id: str
    union_id: str | None
    name: str
    en_name: str | None
    avatar_url: str
    synced_at: float


class ContactRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, open_id: str) -> Contact | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM contacts WHERE open_id=?", (open_id,)
            ).fetchone()
        return _row(row) if row else None

    def get_by_any_id(self, id_: str) -> Contact | None:
        if not id_:
            return None
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM contacts WHERE open_id=? OR union_id=?",
                (id_, id_),
            ).fetchone()
        return _row(row) if row else None

    def lookup_for_mention(self, value: str) -> Contact | None:
        """Resolve a user-supplied identifier to a Contact for @-mention dispatch.

        Web's MentionField always emits real open_ids, but MCP lets AI pass
        natural strings like "邓柯" or "Alice" that came out of the user's
        chat. The Feishu notifier needs the actual open_id to deliver DMs,
        so we look up here.

        Match order:
          1. open_id / union_id (exact ID — always unique)
          2. name / en_name (only when result is unique; 重名 → None)

        Returns None for: empty input, no match, or ambiguous name match.
        Callers should treat None as "skip this mention" (log + drop), never
        as an exception, so one bad name does not fail an entire publish call.
        """
        if not value:
            return None
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM contacts WHERE open_id=? OR union_id=?",
                (value, value),
            ).fetchone()
            if row is not None:
                return _row(row)
            rows = conn.execute(
                "SELECT * FROM contacts WHERE name=? OR en_name=?",
                (value, value),
            ).fetchall()
            if len(rows) == 1:
                return _row(rows[0])
        return None

    def get_many(self, open_ids: list[str]) -> dict[str, Contact]:
        if not open_ids:
            return {}
        placeholders = ",".join("?" for _ in open_ids)
        with self._db.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM contacts WHERE open_id IN ({placeholders})",
                open_ids,
            ).fetchall()
        return {r["open_id"]: _row(r) for r in rows}

    def search(self, q: str, limit: int = 20) -> list[Contact]:
        q = q.strip()
        with self._db.connect() as conn:
            if not q:
                rows = conn.execute(
                    "SELECT * FROM contacts ORDER BY name LIMIT ?", (limit,)
                ).fetchall()
            else:
                like = f"%{q}%"
                rows = conn.execute(
                    "SELECT * FROM contacts"
                    " WHERE name LIKE ? OR en_name LIKE ? OR open_id LIKE ?"
                    " ORDER BY name LIMIT ?",
                    (like, like, like, limit),
                ).fetchall()
        return [_row(r) for r in rows]

    def upsert_many(self, items: list[dict]) -> int:
        if not items:
            return 0
        now = time()
        with self._db.connect() as conn:
            for item in items:
                conn.execute(
                    "INSERT INTO contacts"
                    " (open_id, union_id, name, en_name, avatar_url, synced_at)"
                    " VALUES (?,?,?,?,?,?)"
                    " ON CONFLICT(open_id) DO UPDATE SET"
                    " union_id=excluded.union_id,"
                    " name=excluded.name,"
                    " en_name=excluded.en_name,"
                    " avatar_url=excluded.avatar_url,"
                    " synced_at=excluded.synced_at",
                    (
                        item["open_id"],
                        item.get("union_id"),
                        item["name"],
                        item.get("en_name"),
                        item.get("avatar_url") or "",
                        now,
                    ),
                )
        return len(items)

    def upsert_from_login(
        self,
        *,
        open_id: str,
        union_id: str | None,
        name: str,
        avatar_url: str,
    ) -> Contact:
        now = time()
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT en_name FROM contacts WHERE open_id=?",
                (open_id,),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO contacts (open_id, union_id, name, en_name, avatar_url, synced_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (open_id, union_id, name, None, avatar_url or "", now),
                )
            else:
                conn.execute(
                    "UPDATE contacts"
                    " SET union_id=?, name=?, avatar_url=?, synced_at=?"
                    " WHERE open_id=?",
                    (union_id, name, avatar_url or "", now, open_id),
                )
        got = self.get(open_id)
        assert got is not None
        return got

    def count(self) -> int:
        with self._db.connect() as conn:
            row = conn.execute("SELECT COUNT(*) as c FROM contacts").fetchone()
        return int(row["c"])


def _row(row: sqlite3.Row) -> Contact:
    return Contact(
        open_id=row["open_id"],
        union_id=row["union_id"],
        name=row["name"],
        en_name=row["en_name"],
        avatar_url=row["avatar_url"],
        synced_at=row["synced_at"],
    )
