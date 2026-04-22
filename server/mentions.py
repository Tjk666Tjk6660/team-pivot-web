from __future__ import annotations

import re

from server.contacts import ContactRepo
from server.users import UserRepo

_FEISHU_ID_RE = re.compile(r"\b(?:ou|on)_[a-zA-Z0-9]{16,}\b")


def resolve_id(
    value: str | None,
    users: UserRepo,
    contacts: ContactRepo | None = None,
) -> str | None:
    if not value:
        return value
    u = users.get_by_any_id(value)
    if u:
        return u.name
    c = contacts.get_by_any_id(value) if contacts else None
    return c.name if c else value


def resolve_avatar_url(
    value: str | None,
    users: UserRepo,
    contacts: ContactRepo | None = None,
) -> str | None:
    if not value:
        return None
    u = users.get_by_any_id(value)
    if u and u.avatar_url:
        return u.avatar_url
    c = contacts.get_by_any_id(value) if contacts else None
    if c and c.avatar_url:
        return c.avatar_url
    return None


def resolve_text(text: str, users: UserRepo, contacts: ContactRepo | None = None) -> str:
    def repl(m: re.Match[str]) -> str:
        oid = m.group(0)
        u = users.get_by_any_id(oid)
        if u:
            return f"@{u.name}"
        c = contacts.get_by_any_id(oid) if contacts else None
        return f"@{c.name}" if c else oid

    return _FEISHU_ID_RE.sub(repl, text)
