from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class VisibilityScope:
    mode: str = "public"
    roles: list[str] = field(default_factory=list)
    user_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: dict | None) -> "VisibilityScope":
        if not value:
            return cls()
        mode = str(value.get("mode") or value.get("visibility") or "public")
        roles = _clean_list(value.get("roles") or [])
        user_ids = _clean_list(value.get("user_ids") or [])
        return cls(mode=_validate_mode(mode), roles=roles, user_ids=user_ids)

    def to_dict(self) -> dict:
        if self.mode == "public":
            return {"mode": "public", "roles": [], "user_ids": []}
        return {
            "mode": "restricted",
            "roles": list(self.roles),
            "user_ids": list(self.user_ids),
        }


@dataclass(frozen=True)
class CategoryVisibilityScope:
    mode: str = "public"
    authorized_roles: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: dict | None) -> "CategoryVisibilityScope":
        if not value:
            return cls()
        mode = str(value.get("mode") or value.get("visibility") or "public")
        roles = _clean_list(value.get("authorized_roles") or value.get("roles") or [])
        return cls(mode=_validate_mode(mode), authorized_roles=roles)

    def to_dict(self) -> dict:
        if self.mode == "public":
            return {"mode": "public", "authorized_roles": []}
        return {
            "mode": "restricted",
            "authorized_roles": list(self.authorized_roles),
        }


def _validate_mode(mode: str) -> str:
    if mode not in ("public", "restricted"):
        raise ValueError(f"invalid visibility mode: {mode}")
    return mode


def _clean_list(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in values:
        value = str(item).strip()
        if value and value not in seen:
            out.append(value)
            seen.add(value)
    return out
