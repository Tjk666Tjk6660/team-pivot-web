from __future__ import annotations

import re

from server.users import UserRepo

_FEISHU_ID_RE = re.compile(r"\b(?:ou|on)_[a-zA-Z0-9]{16,}\b")


def resolve_id(value: str | None, users: UserRepo) -> str | None:
    if not value:
        return value
    u = users.get_by_any_id(value)
    return u.name if u else value


def resolve_text(text: str, users: UserRepo) -> str:
    def repl(m: re.Match[str]) -> str:
        oid = m.group(0)
        u = users.get_by_any_id(oid)
        return f"@{u.name}" if u else oid

    return _FEISHU_ID_RE.sub(repl, text)
