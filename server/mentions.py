"""Display resolution for any "user reference string" that appears in stored
content (frontmatter `author` / `creator` / `owner` / `mentions[]`, comment
mentions, render-time @-replacement in body text).

The resolver is "direct-lookup with binding fallback" (see design §7.1):

  1. Direct lookup against `pivot_user.id` — the steady-state path for new
     content written under the §7.1.1 storage contract (Task 19.5+).
  2. Fallback through `external_binding` for legacy frontmatter that still
     stores feishu open_id / union_id from before the migration.
  3. Echo the original ref back with status='unknown' if nothing matches —
     never throws.

External feishu colleagues who never logged into Pivot used to render via
a third-priority ``contacts`` fallback; that path is gone (contacts table
is being retired). Such refs now display as their raw open_id with
status='unknown'.

The resolver memoises results within its lifetime; callers MUST call
``invalidate()`` after profile / status / binding changes so subsequent
renders see fresh state. Tests can rebuild a fresh resolver per case.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from server.external_bindings import ExternalBindingRepo
from server.pivot_users import PivotUserRepo

_FEISHU_ID_RE = re.compile(r"\b(?:ou|on)_[a-zA-Z0-9]{16,}\b")


@dataclass(frozen=True)
class DisplayInfo:
    display_name: str
    avatar_url: str
    status: str  # 'active' | 'suspended' | 'deleted' | 'unknown'


class DisplayResolver:
    def __init__(
        self,
        pivot_users: PivotUserRepo,
        bindings: ExternalBindingRepo,
    ) -> None:
        self._pivot_users = pivot_users
        self._bindings = bindings
        self._cached = lru_cache(maxsize=2048)(self._resolve_uncached)

    def resolve(self, ref: str | None) -> DisplayInfo:
        if not ref:
            return DisplayInfo("", "", "unknown")
        return self._cached(ref)

    def invalidate(self) -> None:
        self._cached.cache_clear()

    def _resolve_uncached(self, ref: str) -> DisplayInfo:
        u = self._pivot_users.get(ref)
        if u is not None:
            return DisplayInfo(u.display_name, u.avatar_url, u.status)

        u = self._pivot_users.get_by_pinyin(ref)
        if u is not None:
            return DisplayInfo(u.display_name, u.avatar_url, u.status)

        legacy = self._pivot_users.get_legacy_display(ref)
        if legacy is not None:
            name, avatar_url = legacy
            return DisplayInfo(name, avatar_url, "active")

        binding = self._bindings.lookup_any_provider(ref)
        if binding is not None:
            u = self._pivot_users.get(binding.pivot_user_id)
            if u is not None:
                return DisplayInfo(u.display_name, u.avatar_url, u.status)

        return DisplayInfo(ref, "", "unknown")


def resolve_id(value: str | None, resolver: DisplayResolver) -> str | None:
    if not value:
        return value
    return resolver.resolve(value).display_name or value


def resolve_avatar_url(
    value: str | None, resolver: DisplayResolver,
) -> str | None:
    if not value:
        return None
    return resolver.resolve(value).avatar_url or None


def resolve_text(text: str, resolver: DisplayResolver) -> str:
    def repl(m: re.Match[str]) -> str:
        ref = m.group(0)
        info = resolver.resolve(ref)
        if info.status != "unknown" or info.display_name != ref:
            return f"@{info.display_name}"
        return ref

    return _FEISHU_ID_RE.sub(repl, text)


def author_view(
    ref: str | None, resolver: DisplayResolver,
) -> dict | None:
    """Per design §7.1.1 + Task 20: serialize a user reference (ULID for
    new content / feishu open_id for legacy frontmatter) plus the
    resolver's view of who that ref points to.

    ``user_id`` is the storage-contract field; ``open_id`` is a
    transitional alias kept for one release while the frontend switches
    over. Returns ``None`` when called with an empty ref so callers can
    drop optional author fields cleanly.
    """
    if not ref:
        return None
    info = resolver.resolve(ref)
    return {
        "user_id": ref,
        "open_id": ref,
        "display_name": info.display_name,
        "avatar_url": info.avatar_url or None,
        "status": info.status,
    }
