from __future__ import annotations

from dataclasses import dataclass
from time import time

from server.db import Database


@dataclass(frozen=True)
class ReaderEntry:
    open_id: str
    first_read_at: float


class FileReadRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def mark(self, user_open_id: str, matter_id: str, filename: str) -> ReaderEntry:
        """Mark a (user, matter, file) read. Idempotent: first call records now;
        subsequent calls return the original first_read_at."""
        now = time()
        with self._db.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO file_reads"
                " (user_open_id, matter_id, filename, first_read_at)"
                " VALUES (?,?,?,?)",
                (user_open_id, matter_id, filename, now),
            )
            row = conn.execute(
                "SELECT first_read_at FROM file_reads"
                " WHERE user_open_id=? AND matter_id=? AND filename=?",
                (user_open_id, matter_id, filename),
            ).fetchone()
        return ReaderEntry(open_id=user_open_id, first_read_at=row["first_read_at"])

    def list_for_matter(self, matter_id: str) -> dict[str, list[ReaderEntry]]:
        """Return {filename: [ReaderEntry...]} for a matter, ascending by first_read_at."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT filename, user_open_id, first_read_at FROM file_reads"
                " WHERE matter_id=?"
                " ORDER BY filename, first_read_at",
                (matter_id,),
            ).fetchall()
        out: dict[str, list[ReaderEntry]] = {}
        for r in rows:
            out.setdefault(r["filename"], []).append(
                ReaderEntry(open_id=r["user_open_id"], first_read_at=r["first_read_at"])
            )
        return out
