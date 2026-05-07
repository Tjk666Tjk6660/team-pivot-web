"""Join applications & same-person match candidates.

Match candidate algorithm (per spec §5.2):
- email_exact: raw_profile.email matches a pivot_user.email (case-insensitive)
- name_exact: raw_profile.name matches a pivot_user.display_name (exact)
- pinyin_full: raw_profile.name → pinyin matches pivot_user.pinyin (skipped this
  iteration: pinyin auto-conversion deferred per plan revision A; if needed,
  callers can pass profile['pinyin'] explicitly)
- pinyin_initials: same source, first letters

Only matches against status='active' users. Capped at 5 candidates.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from time import time
from typing import Any

from server.db import Database
from server.pivot_users import PivotUserRepo


@dataclass(frozen=True)
class JoinApplication:
    id: str
    provider: str
    external_id: str
    external_union_id: str | None
    raw_profile: dict[str, Any]
    suggested_match_user_id: str | None
    status: str
    applied_at: float
    reviewed_at: float | None
    reviewed_by: str | None
    reject_reason: str | None
    via_invite_id: str | None = None


@dataclass(frozen=True)
class MatchCandidate:
    user_id: str
    display_name: str
    email: str | None
    avatar_url: str
    reason: str  # 'email_exact' | 'name_exact' | 'pinyin_full' | 'pinyin_initials'


def _row_to_app(row: sqlite3.Row) -> JoinApplication:
    return JoinApplication(
        id=row["id"],
        provider=row["provider"],
        external_id=row["external_id"],
        external_union_id=row["external_union_id"],
        raw_profile=json.loads(row["raw_profile"]) if row["raw_profile"] else {},
        suggested_match_user_id=row["suggested_match_user_id"],
        status=row["status"],
        applied_at=row["applied_at"],
        reviewed_at=row["reviewed_at"],
        reviewed_by=row["reviewed_by"],
        reject_reason=row["reject_reason"],
        via_invite_id=row["via_invite_id"] if "via_invite_id" in row.keys() else None,
    )


class JoinApplicationRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        *,
        provider: str,
        external_id: str,
        external_union_id: str | None,
        raw_profile: dict[str, Any],
        suggested_match_user_id: str | None,
        via_invite_id: str | None = None,
    ) -> JoinApplication:
        new_id = uuid.uuid4().hex
        with self._db.connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO join_application"
                    " (id, provider, external_id, external_union_id, raw_profile,"
                    "  suggested_match_user_id, status, applied_at, via_invite_id)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (new_id, provider, external_id, external_union_id,
                     json.dumps(raw_profile, ensure_ascii=False),
                     suggested_match_user_id, "pending", time(),
                     via_invite_id),
                )
            except sqlite3.IntegrityError as e:
                raise ValueError(f"duplicate pending application: {e}") from e
        got = self.get(new_id)
        assert got is not None
        return got

    def set_via_invite(self, *, application_id: str, via_invite_id: str) -> None:
        """Patch via_invite_id on an existing application — used when the
        Feishu callback finds a pre-existing pending application that the
        invite-bearing flow now wants to credit."""
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE join_application SET via_invite_id=? WHERE id=?",
                (via_invite_id, application_id),
            )

    def get(self, application_id: str) -> JoinApplication | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM join_application WHERE id=?", (application_id,)
            ).fetchone()
        return _row_to_app(row) if row else None

    def lookup_blocking(
        self, provider: str, external_id: str
    ) -> JoinApplication | None:
        """Returns a pending or rejected application for (provider, external_id),
        or None. Used by login flow to decide whether to create new application."""
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM join_application"
                " WHERE provider=? AND external_id=?"
                " AND status IN ('pending','rejected')"
                " ORDER BY applied_at DESC LIMIT 1",
                (provider, external_id),
            ).fetchone()
        return _row_to_app(row) if row else None

    def list_pending(self) -> list[JoinApplication]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM join_application WHERE status='pending'"
                " ORDER BY applied_at ASC"
            ).fetchall()
        return [_row_to_app(r) for r in rows]

    def list_with_filter(self, status: str | None = None) -> list[JoinApplication]:
        sql = "SELECT * FROM join_application"
        params: list[object] = []
        if status:
            sql += " WHERE status=?"
            params.append(status)
        sql += " ORDER BY applied_at DESC"
        with self._db.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_app(r) for r in rows]

    def approve(self, *, application_id: str, reviewed_by: str) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE join_application"
                " SET status='approved', reviewed_at=?, reviewed_by=?"
                " WHERE id=?",
                (time(), reviewed_by, application_id),
            )

    def reject(
        self, *, application_id: str, reviewed_by: str, reason: str | None
    ) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE join_application"
                " SET status='rejected', reviewed_at=?, reviewed_by=?, reject_reason=?"
                " WHERE id=?",
                (time(), reviewed_by, reason, application_id),
            )

    def unblock(self, *, application_id: str) -> None:
        """Physical delete of a rejected row, freeing the (provider, external_id)
        for re-application. Per spec §5.4, this is the simplest implementation
        of "unblock" without adding new status enum values."""
        with self._db.connect() as conn:
            conn.execute(
                "DELETE FROM join_application WHERE id=? AND status='rejected'",
                (application_id,),
            )


def compute_match_candidates(
    users: PivotUserRepo,
    raw_profile: dict[str, Any],
    *,
    limit: int = 5,
) -> list[MatchCandidate]:
    """Compute same-person match candidates for an applicant.

    Matches only against status='active' users. Capped at `limit`.
    """
    name = (raw_profile.get("name") or "").strip()
    email = (raw_profile.get("email") or "").strip().lower()

    candidates: list[MatchCandidate] = []
    seen_ids: set[str] = set()

    actives = users.list_for_admin(include_deleted=False)
    actives = [u for u in actives if u.status == "active"]

    if email:
        for u in actives:
            if u.email and u.email.lower() == email and u.id not in seen_ids:
                candidates.append(MatchCandidate(
                    user_id=u.id, display_name=u.display_name,
                    email=u.email, avatar_url=u.avatar_url, reason="email_exact",
                ))
                seen_ids.add(u.id)

    if name:
        for u in actives:
            if u.display_name == name and u.id not in seen_ids:
                candidates.append(MatchCandidate(
                    user_id=u.id, display_name=u.display_name,
                    email=u.email, avatar_url=u.avatar_url, reason="name_exact",
                ))
                seen_ids.add(u.id)

    # Pinyin matches: only if applicant raw_profile carries an explicit pinyin
    # field (callers may pre-compute it from feishu open_user info or user input).
    applicant_pinyin = (raw_profile.get("pinyin") or "").strip().lower()
    if applicant_pinyin:
        for u in actives:
            if u.pinyin and u.pinyin.lower() == applicant_pinyin and u.id not in seen_ids:
                candidates.append(MatchCandidate(
                    user_id=u.id, display_name=u.display_name,
                    email=u.email, avatar_url=u.avatar_url, reason="pinyin_full",
                ))
                seen_ids.add(u.id)
        # Initials match
        applicant_initials = "".join(p[0] for p in applicant_pinyin.split() if p)
        if applicant_initials and len(applicant_initials) >= 2:
            for u in actives:
                if u.pinyin and u.id not in seen_ids:
                    user_initials = "".join(p[0] for p in u.pinyin.lower().split() if p)
                    if user_initials == applicant_initials:
                        candidates.append(MatchCandidate(
                            user_id=u.id, display_name=u.display_name,
                            email=u.email, avatar_url=u.avatar_url,
                            reason="pinyin_initials",
                        ))
                        seen_ids.add(u.id)

    return candidates[:limit]
