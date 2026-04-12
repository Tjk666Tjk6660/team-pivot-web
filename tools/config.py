"""Tenant/user context resolution + status display mapping for Pivot.

Unlike appv2 which reads ~/.config/claude-discuss/config.json (single-user),
Pivot pipeline steps receive their context via environment variables
injected by the EC Pipeline Runner. User identity mapping (name <-> feishu_id
<-> pivot_token, see 004 8.4) is handled by the EC Agent config backend,
NOT in Pivot APP code — by the time a pipeline step runs, PIVOT_USER_ID
is already resolved to the canonical name.

This module also owns the discuss module's status display map (004 8.3).
All pipelines returning a status value must call get_status_display() so
the frontend (CLI, Bot, Web UI) uniformly shows the Chinese label.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional


class ConfigError(Exception):
    """Raised when a required configuration env var is missing."""


@dataclass(frozen=True)
class PipelineContext:
    tenant_id: str
    user_id: Optional[str]
    workspace_dir: str
    app_name: str

    @property
    def repo_path(self) -> str:
        return self.workspace_dir


def _require(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        raise ConfigError(f"Required environment variable {key} is not set")
    return val


def from_env() -> PipelineContext:
    """Construct a PipelineContext from environment variables."""
    return PipelineContext(
        tenant_id=_require("PIVOT_TENANT_ID"),
        user_id=os.environ.get("PIVOT_USER_ID"),
        workspace_dir=_require("PIVOT_WORKSPACE_DIR"),
        app_name=_require("PIVOT_APP_NAME"),
    )


STATUS_DISPLAY: dict[str, dict[str, str]] = {
    "discuss": {
        "open": "讨论中",
        "concluded": "已达成结论",
        "produced": "已转为项目",
        "closed": "已关闭",
        "pending": "暂时搁置",
    },
}


def get_status_display(module: str, status: str) -> str:
    """Return the localized display name for a status, or the raw status as fallback."""
    return STATUS_DISPLAY.get(module, {}).get(status, status)


# ---------- User map (Phase 1.1, see docs/TODO-ec-phase-1-1.md) ----------
#
# EC Runner injects PIVOT_USER_MAP as a JSON env var before spawning each
# Python code step subprocess, containing the tenant's {name -> {feishu_id,
# wecom_id, ...}} mapping from EC's user table. Pivot APP reads it at runtime
# to build @mention cards. Missing or malformed env -> empty dict so downstream
# degrades gracefully to text @name.

def get_user_map() -> dict[str, dict[str, str]]:
    """Read PIVOT_USER_MAP env var and parse as JSON.

    Returns empty dict on any failure (missing, malformed, non-object top level).
    """
    raw = os.environ.get("PIVOT_USER_MAP", "")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


# ---------- Thread URL builder (placeholder until Web UI ships) ----------
#
# Phase 1.1 uses a placeholder host because Web UI is blocked in EC.
# Replace with the real URL template when Web UI lands.

def build_thread_url(*, category: str = "", thread: str) -> str:
    """Build a placeholder thread URL.

    Pass `category` when you have it (discuss-new/reply); omit it for
    monitor-scan where issues only carry the thread slug.
    """
    if category:
        return f"https://pivot.example.com/thread/{category}/{thread}"
    return f"https://pivot.example.com/thread/{thread}"
