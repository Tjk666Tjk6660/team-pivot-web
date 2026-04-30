from __future__ import annotations

from dataclasses import dataclass
from time import time

from server.db import Database


KIND_FILE = "file"
KIND_MENTION = "mention"
REASON_COMMENT_MENTION = "comment_mention"
REASON_MATTER_OWNER_CHANGED = "matter_owner_changed"

# Matter-level events (e.g. owner transfer) aren't tied to a specific file,
# but the schema requires a filename. Use empty string as the sentinel:
# - excluded from `file_reasons_for_matter` (kind='file' only)
# - excluded from comment-highlight matching in `unread_mention_keys_for_matter`
#   because no real comment lives on the empty filename
# - cleared via `mark_all_read_for_file` whenever the user reads any file in
#   the same matter (see SQL below)
MATTER_EVENT_FILENAME = ""


@dataclass(frozen=True)
class RelevanceRow:
    pivot_user_id: str
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
        pivot_user_id: str,
        matter_id: str,
        filename: str,
        *,
        reason: str,
        event_at: str,
        actor_pinyin: str,
        read_at: float | None = None,
    ) -> bool:
        """INSERT OR IGNORE a kind='file' row. Returns True if a new row was
        inserted, False if the PK was already present.

        ``read_at`` lets callers pre-mark the row as already-read (used by the
        cold-start backfill so historical timeline activity doesn't surface
        as a tsunami of red unread badges). Default ``None`` = unread."""
        return self._insert_or_ignore(
            pivot_user_id, matter_id, filename, KIND_FILE,
            reason, event_at, actor_pinyin, read_at,
        )

    def insert_mention(
        self,
        pivot_user_id: str,
        matter_id: str,
        filename: str,
        *,
        comment_at: str,
        actor_pinyin: str,
        read_at: float | None = None,
    ) -> bool:
        """INSERT OR IGNORE a kind='mention' row. comment_at is the comment
        created_at ISO string; actor_pinyin is the comment author's pinyin.

        ``read_at`` — see ``insert_file``. Default ``None`` = unread."""
        return self._insert_or_ignore(
            pivot_user_id, matter_id, filename, KIND_MENTION,
            REASON_COMMENT_MENTION, comment_at, actor_pinyin, read_at,
        )

    def insert_matter_event(
        self,
        pivot_user_id: str,
        matter_id: str,
        *,
        reason: str,
        event_at: str,
        actor_pinyin: str,
        read_at: float | None = None,
    ) -> bool:
        """INSERT OR IGNORE a matter-level event row (kind='mention' so it
        adds to the red badge, filename='' sentinel since no specific file).
        Used for matter owner transfers."""
        return self._insert_or_ignore(
            pivot_user_id, matter_id, MATTER_EVENT_FILENAME, KIND_MENTION,
            reason, event_at, actor_pinyin, read_at,
        )

    def _insert_or_ignore(
        self,
        pivot_user_id: str,
        matter_id: str,
        filename: str,
        kind: str,
        reason: str,
        event_at: str,
        actor_pinyin: str,
        read_at: float | None,
    ) -> bool:
        now = time()
        with self._db.connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO relevance_events"
                " (pivot_user_id, matter_id, filename, kind, reason,"
                "  event_at, actor_pinyin, created_at, read_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (pivot_user_id, matter_id, filename, kind, reason,
                 event_at, actor_pinyin, now, read_at),
            )
            return cur.rowcount > 0

    def is_empty(self) -> bool:
        """True if the table holds no rows yet. Used by the startup backfill
        to decide whether to mark all newly-inserted rows as already-read
        (true cold start) versus leave them unread (subsequent backfills,
        which act as compensation for missed real-time writes)."""
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM relevance_events LIMIT 1",
            ).fetchone()
        return row is None

    # ---------- scanner: explicit exists -> insert ----------

    def exists(
        self,
        *,
        pivot_user_id: str,
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
                " WHERE pivot_user_id=? AND matter_id=? AND filename=?"
                "   AND kind=? AND event_at=? AND actor_pinyin=?"
                " LIMIT 1",
                (pivot_user_id, matter_id, filename,
                 kind, event_at, actor_pinyin),
            ).fetchone()
        return row is not None

    # ---------- read-state ----------

    def mark_all_read_for_file(
        self,
        pivot_user_id: str,
        matter_id: str,
        filename: str,
    ) -> int:
        """Mark every unread row on (user, matter, filename) as read.
        Returns the number of rows updated. Both kind='file' and
        kind='mention' rows on this file are touched.

        Also clears matter-level event rows (filename=MATTER_EVENT_FILENAME)
        for the same (user, matter): owner-transfer notifications have no
        natural file to bind to, and reading any file in the matter implies
        the user has engaged with it.
        """
        now = time()
        with self._db.connect() as conn:
            cur = conn.execute(
                "UPDATE relevance_events SET read_at = ?"
                " WHERE pivot_user_id = ? AND matter_id = ?"
                "   AND (filename = ? OR filename = ?)"
                "   AND read_at IS NULL",
                (now, pivot_user_id, matter_id, filename, MATTER_EVENT_FILENAME),
            )
            return cur.rowcount

    # ---------- aggregates ----------

    def unread_breakdown_per_matter(
        self, pivot_user_id: str,
    ) -> dict[str, tuple[int, int]]:
        """Returns {matter_id: (red_files_count, red_mentions_count)} for
        every matter with at least one unread row for the user."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT matter_id,"
                "       SUM(CASE WHEN kind='file'    THEN 1 ELSE 0 END) AS files,"
                "       SUM(CASE WHEN kind='mention' THEN 1 ELSE 0 END) AS mentions"
                "  FROM relevance_events"
                " WHERE pivot_user_id = ? AND read_at IS NULL"
                " GROUP BY matter_id",
                (pivot_user_id,),
            ).fetchall()
        return {
            r["matter_id"]: (int(r["files"] or 0), int(r["mentions"] or 0))
            for r in rows
        }

    def unread_mention_keys_for_matter(
        self, pivot_user_id: str, matter_id: str,
    ) -> set[tuple[str, str, str]]:
        """Returns {(filename, event_at, actor_pinyin)} for unread
        kind='mention' rows on (user, matter). The detail interface uses this
        to populate `mention_unread_for_me` on each comment."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT filename, event_at, actor_pinyin FROM relevance_events"
                " WHERE pivot_user_id = ? AND matter_id = ?"
                "   AND kind = 'mention' AND read_at IS NULL",
                (pivot_user_id, matter_id),
            ).fetchall()
        return {
            (r["filename"], r["event_at"], r["actor_pinyin"]) for r in rows
        }

    def file_reasons_for_matter(
        self, pivot_user_id: str, matter_id: str,
    ) -> dict[str, str]:
        """Returns {filename: reason} for kind='file' rows on (user, matter).
        The detail interface uses this to populate `relevance_reason` on each
        timeline item. Per design, kind='file' has at most one row per
        (user, matter, filename), so the mapping is unambiguous."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT filename, reason FROM relevance_events"
                " WHERE pivot_user_id = ? AND matter_id = ?"
                "   AND kind = 'file'",
                (pivot_user_id, matter_id),
            ).fetchall()
        return {r["filename"]: r["reason"] for r in rows}
