"""Match git commits to Pivot users (= `users.pinyin`).

Rationale lives in `AI-docs/daily-report/product-design.md` §3.5. The 8-tier
chain is from-strict-to-loose:

    1. manual override (settings)
    2. GitHub noreply email → users.github_username
    3. author_name == users.pinyin
    4. author_name == users.github_username (case-insensitive)
    5. author_name == users.name (Chinese / arbitrary)
    6. email local-part == users.pinyin
    7. email local-part == users.github_username (case-insensitive)
    8. miss → unattributed bucket

Decisions:
- Users **without** pinyin are not eligible to receive an attribution
  (they haven't completed setup; we'd be guessing the canonical key)
- No fuzzy / substring matching — wrong attribution is worse than "未识别"
- On a tie at level 5 (multiple users share the same `name`), the first
  match wins; we log a warning so admins notice and add an override"""
from __future__ import annotations

import logging
import re
from dataclasses import replace

from server.daily_report.types import CommitRecord
from server.users import User

log = logging.getLogger("server.daily_report.attribution")

# Matches both the legacy form `username@users.noreply.github.com` and the
# privacy form `12345+username@users.noreply.github.com`.
_GITHUB_NOREPLY_RE = re.compile(
    r"^(?:\d+\+)?([a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?)@users\.noreply\.github\.com$",
    re.IGNORECASE,
)


def attribute_commits(
    commits: list[CommitRecord],
    users: list[User],
    overrides: dict[str, list[str]],
) -> tuple[list[CommitRecord], list[CommitRecord]]:
    """Run the 8-tier match against every commit.

    Returns `(matched, unmatched)`:
      - `matched`   - new CommitRecord instances with `matched_pinyin` filled
      - `unmatched` - original CommitRecord instances (unchanged) for the
                      "未识别 commits" bucket on the card

    `overrides` is the JSON shape from settings:
        { "<pinyin>": ["alt-email1", "alt-email2"], ... }
    Empty / malformed overrides are treated as no overrides.
    """
    email_to_pinyin = _invert_overrides(overrides)
    eligible_users = [u for u in users if u.pinyin]   # need pinyin to be a target

    matched: list[CommitRecord] = []
    unmatched: list[CommitRecord] = []
    for c in commits:
        pinyin = _match_one(c, eligible_users, email_to_pinyin)
        if pinyin:
            matched.append(replace(c, matched_pinyin=pinyin))
        else:
            unmatched.append(c)
    return matched, unmatched


# --------------------------------------------------------------------------- #
# Internals                                                                   #
# --------------------------------------------------------------------------- #


def _invert_overrides(overrides: dict[str, list[str]] | None) -> dict[str, str]:
    """Build a normalized email → pinyin map. Lowercases emails for
    case-insensitive matching; silently drops malformed entries."""
    out: dict[str, str] = {}
    if not isinstance(overrides, dict):
        return out
    for pinyin, emails in overrides.items():
        if not isinstance(pinyin, str) or not pinyin.strip():
            continue
        if not isinstance(emails, list):
            continue
        for email in emails:
            if isinstance(email, str) and email.strip():
                out[email.strip().lower()] = pinyin.strip()
    return out


def _match_one(
    c: CommitRecord,
    users: list[User],
    email_to_pinyin: dict[str, str],
) -> str | None:
    email_lower = (c.author_email or "").strip().lower()
    name_raw = (c.author_name or "").strip()
    name_lower = name_raw.lower()

    # 1. manual override (settings JSON, exact email match, case-insensitive)
    if email_lower and email_lower in email_to_pinyin:
        return email_to_pinyin[email_lower]

    # 2. GitHub noreply email → users.github_username
    m = _GITHUB_NOREPLY_RE.match(email_lower)
    if m:
        gh_user = m.group(1).lower()
        for u in users:
            if u.github_username and u.github_username.lower() == gh_user:
                return u.pinyin   # type: ignore[return-value]

    # 3. author_name == users.pinyin (exact)
    if name_raw:
        for u in users:
            if u.pinyin == name_raw:
                return u.pinyin

    # 4. author_name == users.github_username (case-insensitive)
    if name_lower:
        for u in users:
            if u.github_username and u.github_username.lower() == name_lower:
                return u.pinyin   # type: ignore[return-value]

    # 5. author_name == users.name (Chinese / arbitrary)
    if name_raw:
        candidates = [u for u in users if u.name == name_raw]
        if len(candidates) > 1:
            log.warning(
                "commit %s author_name=%r matched %d users by name (%s); "
                "picking first — add daily_report.commit_author_overrides "
                "if this is wrong",
                c.sha[:7], name_raw, len(candidates),
                [u.pinyin for u in candidates],
            )
        if candidates:
            return candidates[0].pinyin   # type: ignore[return-value]

    # 6 + 7. email local-part
    if "@" in email_lower:
        local = email_lower.split("@", 1)[0]
        if local:
            for u in users:
                if u.pinyin == local:
                    return u.pinyin
            for u in users:
                if u.github_username and u.github_username.lower() == local:
                    return u.pinyin   # type: ignore[return-value]

    return None
