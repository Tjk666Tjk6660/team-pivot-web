"""Tenant/user context resolution + status display mapping for Pivot.

Unlike appv2 which reads ~/.config/claude-discuss/config.json (single-user),
Pivot pipeline steps receive their context via environment variables
injected by the EC Pipeline Runner. User identity mapping (name <-> feishu_id
<-> pivot_token, see 004 8.4) is handled by the EC Agent config backend,
NOT in Pivot APP code — by the time a pipeline step runs, ENCLAWS_TENANT_USER_ID
is already resolved to the canonical name.

This module also owns the discuss module's status display map (004 8.3).
All pipelines returning a status value must call get_status_display() so
the frontend (CLI, Bot, Web UI) uniformly shows the Chinese label.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


class ConfigError(Exception):
    """Raised when a required configuration env var is missing."""


class ConfigNotReady(Exception):
    """Raised when pivot-config.yaml has empty required fields."""

    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__(f"Config not ready, missing: {', '.join(missing)}")


_REQUIRED_FIELDS = ["data_space_repo", "git_token"]


def _resolve_data_dir() -> str:
    """Resolve the data directory from env vars.

    Priority: PIVOT_DATA_DIR > PIVOT_REPO_PATH (legacy) > parent of PIVOT_DATA_SPACE_DIR > app dir.
    """
    data_dir = os.environ.get("PIVOT_DATA_DIR", "")
    if data_dir:
        return data_dir
    repo_path = os.environ.get("PIVOT_REPO_PATH", "")
    if repo_path:
        return repo_path
    ds = os.environ.get("PIVOT_DATA_SPACE_DIR", "")
    if ds:
        return str(Path(ds).parent)
    candidate = Path(__file__).parent.parent / "pivot.yaml"
    if candidate.exists():
        return str(candidate.parent)
    return ""


def get_version() -> str:
    """Read version from pivot.yaml (git-tracked project info).

    Falls back to PIVOT_VERSION env var, then "unknown".
    """
    # pivot.yaml lives in the app dir, not the data dir
    app_dir = os.environ.get("PIVOT_APP_DIR", "")
    if not app_dir:
        candidate = Path(__file__).parent.parent / "pivot.yaml"
        if candidate.exists():
            app_dir = str(candidate.parent)
    if app_dir:
        pivot_file = Path(app_dir) / "pivot.yaml"
        if pivot_file.exists():
            try:
                with open(pivot_file, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                v = data.get("version")
                if v:
                    return str(v)
            except Exception:
                pass

    # Fallback to env var (set by Runner)
    return os.environ.get("PIVOT_VERSION", "unknown")


def check_config(data_dir: str | Path) -> dict:
    """Check pivot-config.yaml for completeness.

    Args:
        data_dir: The data directory containing pivot-config.yaml and data_space/.

    Returns {"ready": True} or {"ready": False, "missing": [...]}.
    """
    config_file = Path(data_dir) / "pivot-config.yaml"
    if not config_file.exists():
        return {"ready": False, "missing": ["config_file"]}

    with open(config_file, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    missing = [k for k in _REQUIRED_FIELDS if not data.get(k)]

    data_space_dir = Path(data_dir) / "data_space"
    if not data_space_dir.is_dir():
        missing.append("data_space_dir")

    if missing:
        return {"ready": False, "missing": missing}
    return {"ready": True}


def require_config_ready(data_dir: str | Path) -> None:
    """Raise ConfigNotReady if pivot-config.yaml is incomplete.

    Call this at the start of any pipeline step to fail fast with a
    structured error instead of crashing mid-execution.
    """
    result = check_config(data_dir)
    if not result["ready"]:
        raise ConfigNotReady(result["missing"])


@dataclass(frozen=True)
class PipelineContext:
    tenant_id: str
    user_id: Optional[str]
    data_space_dir: str
    app_name: str

    @property
    def repo_path(self) -> str:
        return self.data_space_dir


def _require(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        raise ConfigError(f"Required environment variable {key} is not set")
    return val


def from_env() -> PipelineContext:
    """Construct a PipelineContext from environment variables.

    Config completeness is checked by the _constructor pipeline, not here.
    """
    return PipelineContext(
        tenant_id=_require("ENCLAWS_TENANT_ID"),
        user_id=os.environ.get("ENCLAWS_TENANT_USER_ID"),
        data_space_dir=_require("PIVOT_DATA_SPACE_DIR"),
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
