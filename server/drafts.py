from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from time import time

from server.db import Database

VALID_TYPES = ("proposal", "reply")


@dataclass(frozen=True)
class Draft:
    id: str
    pivot_user_id: str
    type: str
    title: str | None
    category: str | None
    body_md: str
    thread_key: str | None
    mentions_json: str | None
    reply_to: str | None
    references_json: str
    created_at: float
    updated_at: float
    # P4.6: matter 草稿走这一列，非 matter 草稿保持 NULL
    matter_payload_json: str | None = None


class DraftRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        *,
        pivot_user_id: str | None = None,
        user_open_id: str | None = None,
        type_: str,
        title: str | None = None,
        category: str | None = None,
        body_md: str = "",
        thread_key: str | None = None,
        mentions_json: str | None = None,
        reply_to: str | None = None,
        references_json: str = "[]",
        matter_payload_json: str | None = None,
    ) -> Draft:
        pivot_user_id = pivot_user_id or user_open_id
        if not pivot_user_id:
            raise ValueError("pivot_user_id is required")
        if type_ not in VALID_TYPES:
            raise ValueError(f"invalid draft type: {type_}")
        draft_id = uuid.uuid4().hex
        now = time()
        with self._db.connect() as conn:
            conn.execute(
                "INSERT INTO drafts"
                " (id, pivot_user_id, type, title, category, body_md, thread_key,"
                "  mentions_json, reply_to, references_json, matter_payload_json,"
                "  created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    draft_id,
                    pivot_user_id,
                    type_,
                    title,
                    category,
                    body_md,
                    thread_key,
                    mentions_json,
                    reply_to,
                    references_json,
                    matter_payload_json,
                    now,
                    now,
                ),
            )
        got = self.get(draft_id)
        assert got is not None
        return got

    def get(self, draft_id: str) -> Draft | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM drafts WHERE id=?", (draft_id,)
            ).fetchone()
        return _row(row) if row else None

    def list_for_user(self, pivot_user_id: str) -> list[Draft]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM drafts WHERE pivot_user_id=? ORDER BY updated_at DESC",
                (pivot_user_id,),
            ).fetchall()
        return [_row(r) for r in rows]

    def update(
        self,
        draft_id: str,
        *,
        title: str | None = None,
        category: str | None = None,
        body_md: str | None = None,
        thread_key: str | None = None,
        mentions_json: str | None = None,
        reply_to: str | None = None,
        references_json: str | None = None,
        matter_payload_json: str | None = None,
    ) -> Draft | None:
        fields: list[str] = []
        values: list[object] = []
        for name, val in (
            ("title", title),
            ("category", category),
            ("body_md", body_md),
            ("thread_key", thread_key),
            ("mentions_json", mentions_json),
            ("reply_to", reply_to),
            ("references_json", references_json),
            ("matter_payload_json", matter_payload_json),
        ):
            if val is not None:
                fields.append(f"{name}=?")
                values.append(val)
        if not fields:
            return self.get(draft_id)
        fields.append("updated_at=?")
        values.append(time())
        values.append(draft_id)
        with self._db.connect() as conn:
            conn.execute(
                f"UPDATE drafts SET {','.join(fields)} WHERE id=?", values
            )
        return self.get(draft_id)

    def delete(self, draft_id: str) -> bool:
        with self._db.connect() as conn:
            cur = conn.execute("DELETE FROM drafts WHERE id=?", (draft_id,))
            return cur.rowcount > 0


def _row(row: sqlite3.Row) -> Draft:
    cols = row.keys()
    return Draft(
        id=row["id"],
        pivot_user_id=row["pivot_user_id"],
        type=row["type"],
        title=row["title"],
        category=row["category"],
        body_md=row["body_md"],
        thread_key=row["thread_key"],
        mentions_json=row["mentions_json"] if "mentions_json" in cols else None,
        reply_to=row["reply_to"] if "reply_to" in cols else None,
        references_json=(row["references_json"] if "references_json" in cols else None) or "[]",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        matter_payload_json=(
            row["matter_payload_json"] if "matter_payload_json" in cols else None
        ),
    )
