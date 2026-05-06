"""Pick a unique pinyin slug for a newly-approved Feishu user.

We feed the IM's display name through pypinyin (via server.contacts.
name_to_pinyin) and then disambiguate against existing PivotUser.pinyin
values. Names that produce an unusable slug (empty, leading non-letter,
illegal chars) fall back to user_<openid 后 8 位> — a stable but uglier
default the user can change later via /api/me/profile."""
from __future__ import annotations

import re

from server.contacts import name_to_pinyin
from server.pivot_users import PINYIN_RE_PATTERN, PivotUserRepo

_PINYIN_RE = re.compile(PINYIN_RE_PATTERN)


def assign_pinyin(*, name: str, open_id: str, repo: PivotUserRepo) -> str:
    base = name_to_pinyin(name) if name else ""
    if not _PINYIN_RE.match(base):
        suffix = (open_id or "")[:8] or "anon"
        base = f"user_{suffix}"
        # The fallback can itself collide if two open_ids share the same 8
        # head (extremely unlikely). Run it through the same uniquify loop.
    return _next_unused(base, repo)


def _next_unused(base: str, repo: PivotUserRepo) -> str:
    if repo.get_by_pinyin(base) is None:
        return base
    n = 2
    while True:
        candidate = f"{base}_{n}"
        if repo.get_by_pinyin(candidate) is None:
            return candidate
        n += 1
