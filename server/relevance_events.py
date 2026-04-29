from __future__ import annotations

from dataclasses import dataclass
from time import time

from server.db import Database


KIND_FILE = "file"
KIND_MENTION = "mention"
REASON_COMMENT_MENTION = "comment_mention"


@dataclass(frozen=True)
class RelevanceRow:
    user_open_id: str
    matter_id: str
    filename: str
    kind: str
    reason: str
    event_at: str
    actor_pinyin: str
    created_at: float
    read_at: float | None


class RelevanceEventsRepo:
    """Single-table store for "relevant to me" events.

    Two row kinds share one table:
      - kind='file':    file-level relevance (owner / reply / verify / in_my_matter).
                        At most one row per (user, matter, filename) — event_at is
                        item.created_at and actor_pinyin is item.creator, both
                        deterministic, so PK collisions naturally dedupe.
      - kind='mention': one row per @ event in comments. event_at is comment.created_at,
                        actor_pinyin is comment.author. Different comments → different
                        PKs → red counts accumulate.

    Real-time writer uses INSERT OR IGNORE for race safety; scanner uses
    explicit exists() + insert for observability (counts inserted vs skipped).
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    # ---------- writes ----------

    def insert_file(
        self,
        user_open_id: str,
        matter_id: str,
        filename: str,
        *,
        reason: str,
        event_at: str,
        actor_pinyin: str,
    ) -> bool:
        """INSERT OR IGNORE a kind='file' row. Returns True if a new row was
        inserted, False if the PK was already present."""
        return self._insert_or_ignore(
            user_open_id, matter_id, filename, KIND_FILE,
            reason, event_at, actor_pinyin,
        )

    def insert_mention(
        self,
        user_open_id: str,
        matter_id: str,
        filename: str,
        *,
        comment_at: str,
        actor_pinyin: str,
    ) -> bool:
        """INSERT OR IGNORE a kind='mention' row. comment_at is the comment
        created_at ISO string; actor_pinyin is the comment author's pinyin."""
        return self._insert_or_ignore(
            user_open_id, matter_id, filename, KIND_MENTION,
            REASON_COMMENT_MENTION, comment_at, actor_pinyin,
        )

    def _insert_or_ignore(
        self,
        user_open_id: str,
        matter_id: str,
        filename: str,
        kind: str,
        reason: str,
        event_at: str,
        actor_pinyin: str,
    ) -> bool:
        now = time()
        with self._db.connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO relevance_events"
                " (user_open_id, matter_id, filename, kind, reason,"
                "  event_at, actor_pinyin, created_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (user_open_id, matter_id, filename, kind, reason,
                 event_at, actor_pinyin, now),
            )
            return cur.rowcount > 0

    # ---------- scanner: explicit exists -> insert ----------

    def exists(
        self,
        *,
        user_open_id: str,
        matter_id: str,
        filename: str,
        kind: str,
        event_at: str,
        actor_pinyin: str,
    ) -> bool:
        """PK lookup. Scanner uses this to decide whether to insert."""
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM relevance_events"
                " WHERE user_open_id=? AND matter_id=? AND filename=?"
                "   AND kind=? AND event_at=? AND actor_pinyin=?"
                " LIMIT 1",
                (user_open_id, matter_id, filename,
                 kind, event_at, actor_pinyin),
            ).fetchone()
        return row is not None

    # ---------- read-state ----------

    def mark_all_read_for_file(
        self,
        user_open_id: str,
        matter_id: str,
        filename: str,
    ) -> int:
        """Mark every unread row on (user, matter, filename) as read.
        Returns the number of rows updated. Both kind='file' and
        kind='mention' rows on this file are touched.
        """
        now = time()
        with self._db.connect() as conn:
            cur = conn.execute(
                "UPDATE relevance_events SET read_at = ?"
                " WHERE user_open_id = ? AND matter_id = ? AND filename = ?"
                "   AND read_at IS NULL",
                (now, user_open_id, matter_id, filename),
            )
            return cur.rowcount

    # ---------- aggregates ----------

    def unread_breakdown_per_matter(
        self, user_open_id: str,
    ) -> dict[str, tuple[int, int]]:
        """Returns {matter_id: (red_files_count, red_mentions_count)} for
        every matter with at least one unread row for the user."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT matter_id,"
                "       SUM(CASE WHEN kind='file'    THEN 1 ELSE 0 END) AS files,"
                "       SUM(CASE WHEN kind='mention' THEN 1 ELSE 0 END) AS mentions"
                "  FROM relevance_events"
                " WHERE user_open_id = ? AND read_at IS NULL"
                " GROUP BY matter_id",
                (user_open_id,),
            ).fetchall()
        return {
            r["matter_id"]: (int(r["files"] or 0), int(r["mentions"] or 0))
            for r in rows
        }

    def unread_mention_keys_for_matter(
        self, user_open_id: str, matter_id: str,
    ) -> set[tuple[str, str, str]]:
        """Returns {(filename, event_at, actor_pinyin)} for unread
        kind='mention' rows on (user, matter). The detail interface uses this
        to populate `mention_unread_for_me` on each comment."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT filename, event_at, actor_pinyin FROM relevance_events"
                " WHERE user_open_id = ? AND matter_id = ?"
                "   AND kind = 'mention' AND read_at IS NULL",
                (user_open_id, matter_id),
            ).fetchall()
        return {
            (r["filename"], r["event_at"], r["actor_pinyin"]) for r in rows
        }

    def file_reasons_for_matter(
        self, user_open_id: str, matter_id: str,
    ) -> dict[str, str]:
        """Returns {filename: reason} for kind='file' rows on (user, matter).
        The detail interface uses this to populate `relevance_reason` on each
        timeline item. Per design, kind='file' has at most one row per
        (user, matter, filename), so the mapping is unambiguous."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT filename, reason FROM relevance_events"
                " WHERE user_open_id = ? AND matter_id = ?"
                "   AND kind = 'file'",
                (user_open_id, matter_id),
            ).fetchall()
        return {r["filename"]: r["reason"] for r in rows}
