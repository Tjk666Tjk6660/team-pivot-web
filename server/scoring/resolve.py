"""pinyin ↔ pivot_user.id 解析层.

Git 时间线（discussions/+ index/）里 creator/owner/comment.author 落的是写入时的
pinyin（不可变）；SQLite 端 Scoring 表用 pivot_user.id（uuid hex，永久不变）。
两边的桥梁就是这个模块。

调用点（见 design §1.4）:
    入队前         → matter.owner pinyin → resolve_pinyin → user_id
    Prompt 注入   → 把 commenter_weights 表 join pivot_user → 得 (pinyin, weight)
    AI 输出落库   → AI 返回的 pinyin → resolve_pinyin → user_id
    历史 pinyin 改名 → 不做版本回溯；匹不上即 None，调用方降级处理

策略：
- 任何 status 的用户都能匹（包括 deleted），保留历史归因
- 同 pinyin 多用户 → 优先 active > suspended > deleted，次按 created_at 早的优先
- 空字符串 / None → 直接返回 None
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from server.db import Database

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedUser:
    """Minimal projection of pivot_user used inside Scoring layer.

    Avoids dragging the full PivotUser dataclass through resolve+store; those
    callers only need id + pinyin + display_name + status.
    """
    id: str
    pinyin: str | None
    display_name: str
    status: str


class PinyinResolver:
    """Look up pivot_user rows by pinyin. Caches per-instance to amortize the
    scoring batch (a single matter's evidence resolution may touch the same
    pinyin many times)."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._cache: dict[str, ResolvedUser | None] = {}

    def resolve(self, pinyin: str | None) -> ResolvedUser | None:
        """Return the user with matching pinyin, or None.

        Multi-match precedence: active > suspended > deleted, then created_at ASC.
        """
        if not pinyin:
            return None
        if pinyin in self._cache:
            return self._cache[pinyin]
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT id, pinyin, display_name, status FROM pivot_user"
                " WHERE pinyin = ?"
                " ORDER BY CASE status"
                "   WHEN 'active' THEN 0"
                "   WHEN 'suspended' THEN 1"
                "   WHEN 'deleted' THEN 2"
                "   ELSE 3 END,"
                " created_at ASC"
                " LIMIT 1",
                (pinyin,),
            ).fetchone()
        resolved = _row_to_resolved(row) if row else None
        if resolved is None:
            log.debug("pinyin not resolved: %s", pinyin)
        self._cache[pinyin] = resolved
        return resolved

    def resolve_id(self, pinyin: str | None) -> str | None:
        """Convenience: return just the user_id, or None if not found."""
        u = self.resolve(pinyin)
        return u.id if u else None

    def get_by_id(self, user_id: str | None) -> ResolvedUser | None:
        """Reverse lookup: pivot_user.id → ResolvedUser. Used by store readers
        that need the current pinyin / display_name for a stored user_id."""
        if not user_id:
            return None
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT id, pinyin, display_name, status FROM pivot_user"
                " WHERE id = ?",
                (user_id,),
            ).fetchone()
        return _row_to_resolved(row) if row else None


def _row_to_resolved(row: sqlite3.Row) -> ResolvedUser:
    return ResolvedUser(
        id=row["id"],
        pinyin=row["pinyin"],
        display_name=row["display_name"],
        status=row["status"],
    )
