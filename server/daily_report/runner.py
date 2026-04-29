"""End-to-end daily-report orchestration. Called by the CLI script
`scripts/daily-report/run.py` (which itself is invoked by systemd timer).

Returns `(exit_code, debug_payload)`:
  exit_code 0 — succeeded (or disabled / dry-run, both are 'OK')
  exit_code 1 — runtime failure (broadcast / etc) — systemd shows failed
  exit_code 2 — bad configuration (workspace missing, …)"""
from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from server.daily_report.aggregate import aggregate
from server.daily_report.attribution import attribute_commits
from server.daily_report.collect_git import collect_commits
from server.daily_report.collect_matter import collect_matter_events
from server.daily_report.config_keys import (
    DEFAULT_CODE_REPO_DIR,
    KEY_CODE_REPO_DIR,
    KEY_ENABLED,
    KEY_OVERRIDES,
)
from server.daily_report.render import build_daily_report_card
from server.daily_report.score import AISettings, score_team
from server.daily_report.types import TeamReport, TimeWindow
from server.daily_report.window import compute_window

log = logging.getLogger("server.daily_report.runner")


def run_daily_report(
    *,
    db_path: Path,
    workspace_index_dir: Path,
    code_repo_dir: Path | None = None,
    now: datetime | None = None,
    window: TimeWindow | None = None,
    dry_run: bool = False,
    no_ai: bool = False,
    notifier=None,                 # FeishuNotifier | None
) -> tuple[int, dict[str, Any]]:
    """Run the daily report end-to-end.

    Caller (CLI / smoke test) injects `db_path` / `workspace_index_dir` /
    optionally `notifier`. `dry_run=True` skips broadcast.

    The card has no CTA button (see render.py docstring), so this function
    no longer needs a `web_base_url` argument.
    """
    # Lazy imports to avoid hard dependency on server boot for tests
    from server.db import Database
    from server.settings import SettingsRepo
    from server.users import UserRepo

    if not db_path.exists():
        log.error("db_path does not exist: %s", db_path)
        return 2, {"error": f"db not found: {db_path}"}

    db = Database(db_path)
    settings = SettingsRepo(db)

    if _is_disabled(settings):
        log.info("daily report is disabled via settings (%s=0); skipping",
                 KEY_ENABLED)
        return 0, {"status": "disabled"}

    if not workspace_index_dir.is_dir():
        log.error(
            "workspace_index_dir not found: %s — workspace not configured?",
            workspace_index_dir,
        )
        return 2, {"error": f"workspace index dir missing: {workspace_index_dir}"}

    user_repo = UserRepo(db)
    all_users = user_repo.list_all()

    # Window: prefer explicit `window`, then `now`, else current time
    if window is None:
        window = compute_window(now or datetime.now().astimezone())

    # Code mirror dir: explicit arg → settings → default
    if code_repo_dir is None:
        code_repo_dir = Path(
            settings.get(KEY_CODE_REPO_DIR) or DEFAULT_CODE_REPO_DIR
        )

    # 1. fetch code mirror (best-effort, never fatal)
    fetch_warning = _fetch_code_mirror(code_repo_dir)

    # 2. collect both data sources
    matter_events = collect_matter_events(workspace_index_dir, window)
    raw_commits = collect_commits(code_repo_dir, window)

    # 3. attribute commits → pinyin
    overrides = _load_overrides(settings)
    matched, unmatched = attribute_commits(raw_commits, all_users, overrides)

    # 4. aggregate per user + team summary
    activities, summary = aggregate(
        matter_events, matched, unmatched, all_users, window,
        fetch_warning=fetch_warning,
    )

    # 5. AI scoring (or fallback)
    ai_settings = _load_ai_settings(settings)
    scoring = score_team(activities, summary,
                         ai_settings=ai_settings, no_ai=no_ai)

    # 6. order activities by score (descending) for renderer
    activities_sorted = _sort_activities_by_score(activities, scoring)
    report = TeamReport(
        summary=summary,
        user_activities=tuple(activities_sorted),
        scoring=scoring,
    )

    # 7. render card (no in-product page to deep-link to → no button)
    card = build_daily_report_card(report)

    debug = {
        "status": "rendered",
        "window": {
            "since": window.since.isoformat(),
            "until": window.until.isoformat(),
        },
        "team_score": scoring.team_score,
        "scoring_status": scoring.status,
        "fallback_reason": scoring.fallback_reason,
        "n_users": len(activities),
        "n_active": sum(1 for ua in activities if ua.is_active),
        "n_inactive": len(summary.inactive_users),
        "n_matter_events": len(matter_events),
        "n_commits": len(raw_commits),
        "n_unattributed": len(unmatched),
        "fetch_warning": fetch_warning,
    }

    # 8. send (or skip on dry-run)
    if dry_run:
        log.info("dry-run: skipping broadcast")
        debug["card"] = card
        return 0, debug

    if notifier is None:
        log.error("notifier not provided and not dry_run; cannot send")
        return 1, {**debug, "error": "no notifier"}

    try:
        notifier.broadcast_card(card, event=f"daily_report {window.label}")
    except Exception as e:  # noqa: BLE001
        log.exception("broadcast failed")
        return 1, {**debug, "error": f"broadcast: {e}"}

    return 0, debug


# --------------------------------------------------------------------------- #
# Internals                                                                   #
# --------------------------------------------------------------------------- #


def _is_disabled(settings) -> bool:
    raw = (settings.get(KEY_ENABLED) or "1").strip().lower()
    return raw in ("0", "false", "off", "no")


def _fetch_code_mirror(code_repo_dir: Path) -> str | None:
    """`git fetch --all --prune`. Returns None on success; an error string
    on failure (NOT raised — caller surfaces it as a fetch_warning on the
    card, the report still goes out).

    Timeout 60s — enough for a normal incremental fetch but not so long
    that systemd thinks the unit hung.
    """
    if not code_repo_dir.is_dir() or not (code_repo_dir / ".git").exists():
        msg = f"代码仓库 mirror 未初始化 ({code_repo_dir})"
        log.warning("daily-report: %s", msg)
        return msg
    try:
        proc = subprocess.run(
            ["git", "-C", str(code_repo_dir), "fetch", "--all", "--prune"],
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except subprocess.TimeoutExpired:
        log.warning("daily-report: code mirror fetch timed out (60s)")
        return "git fetch 超时(60s)"
    except Exception as e:  # noqa: BLE001
        log.warning("daily-report: code mirror fetch unexpected error: %s", e)
        return f"git fetch 异常:{type(e).__name__}"

    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        log.warning("daily-report: code mirror fetch rc=%d stderr=%s",
                    proc.returncode, err[:200])
        return f"git fetch 失败:{err[:80] or '(no stderr)'}"
    return None


def _load_overrides(settings) -> dict[str, list[str]]:
    raw = settings.get(KEY_OVERRIDES) or "{}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("daily-report: %s is not valid JSON, treating as {{}}",
                    KEY_OVERRIDES)
        return {}
    return data if isinstance(data, dict) else {}


def _load_ai_settings(settings) -> AISettings | None:
    """Pull the AI config the chat assistant already uses (server/api/ai.py).
    Returns None when api_key is empty (score_team will fall back)."""
    from server.ai.client import DEFAULT_BASE_URL, DEFAULT_MODEL

    api_key = (settings.get("ai.openrouter_api_key") or "").strip()
    if not api_key:
        return None
    return AISettings(
        api_key=api_key,
        base_url=(settings.get("ai.base_url") or DEFAULT_BASE_URL).strip(),
        model=(settings.get("ai.model") or DEFAULT_MODEL).strip(),
    )


def _sort_activities_by_score(activities, scoring):
    """Sort activities by AI / fallback score (descending). Activities not
    in scoring.per_user (i.e. inactive users) sort to the end."""
    score_by_pinyin = {us.pinyin: us.score for us in scoring.per_user}
    return sorted(
        activities,
        key=lambda a: (-score_by_pinyin.get(a.pinyin, -1.0), a.pinyin),
    )
