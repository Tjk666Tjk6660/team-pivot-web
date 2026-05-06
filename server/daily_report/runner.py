"""End-to-end daily-report orchestration (v0.2).

被 scripts/daily-report/run.py(systemd timer)和 admin 手动触发端点
共用调用。

v0.2 进度:
  Phase 3 已落地:公司视角报告(company_narrate + build_company_card +
                  notifier.broadcast_card)
  Phase 4 待落地:个人视角报告(personal_narrate + build_personal_card)

返回 (exit_code, debug_payload):
  exit_code 0 — 成功(或 disabled / dry-run)
  exit_code 1 — 运行时失败(发送失败等)
  exit_code 2 — 配置错误(workspace 未配置等)
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from server.daily_report.aggregate import aggregate
from server.daily_report.collect_matter import collect_matter_events
from server.daily_report.company_narrate import (
    AISettings,
    narrate_company,
)
from server.daily_report.config_keys import (
    KEY_COMPANY_ENABLED,
    KEY_ENABLED,
    KEY_PERSONAL_ENABLED,
    KEY_PUSH_TIME,
    KEY_TIME_WINDOW_HOURS,
)
from server.daily_report.personal_narrate import narrate_personal
from server.daily_report.render import build_company_card, build_personal_card
from server.daily_report.shared_facts import build_shared_facts
from server.daily_report.types import TimeWindow
from server.daily_report.window import compute_window

log = logging.getLogger("server.daily_report.runner")


def run_daily_report(
    *,
    db_path: Path,
    workspace_index_dir: Path,
    now: datetime | None = None,
    window: TimeWindow | None = None,
    dry_run: bool = False,
    no_ai: bool = False,
    notifier=None,                 # FeishuNotifier | None
) -> tuple[int, dict[str, Any]]:
    """Run the daily report end-to-end."""
    # Lazy imports to avoid hard dependency on server boot for tests
    from server.db import Database
    from server.pivot_users import PivotUserRepo
    from server.settings import SettingsRepo

    if not db_path.exists():
        log.error("db_path does not exist: %s", db_path)
        return 2, {"error": f"db not found: {db_path}"}

    db = Database(db_path)
    settings = SettingsRepo(db)

    if _is_disabled(settings, KEY_ENABLED):
        log.info("daily report disabled (%s=0); skipping", KEY_ENABLED)
        return 0, {"status": "disabled"}

    if not workspace_index_dir.is_dir():
        log.error(
            "workspace_index_dir not found: %s — workspace not configured?",
            workspace_index_dir,
        )
        return 2, {"error": f"workspace index dir missing: {workspace_index_dir}"}

    user_repo = PivotUserRepo(db)
    all_users = user_repo.list_all()

    if window is None:
        # 从 settings 读 push_time + time_window_hours,这样 admin UI 改了即时生效
        push_h, push_m = _read_push_time(settings)
        win_hours = _read_window_hours(settings)
        window = compute_window(
            now or datetime.now().astimezone(),
            push_hour=push_h, push_minute=push_m,
            window_hours=win_hours,
        )

    # 1. Collect + aggregate
    matter_events = collect_matter_events(workspace_index_dir, window)
    activities, summary = aggregate(matter_events, all_users, window)
    facts = build_shared_facts(matter_events, activities, summary, window)

    debug: dict[str, Any] = {
        "window": {
            "since": window.since.isoformat(),
            "until": window.until.isoformat(),
        },
        "n_users": len(activities),
        "n_active": facts.n_active,
        "n_inactive": len(summary.inactive_users),
        "n_matter_events": len(matter_events),
        "matters_touched": summary.matters_touched,
        "matter_status_breakdown": dict(facts.matter_status_breakdown),
    }

    # 2. AI settings (shared by company / personal narratives)
    ai_settings = _load_ai_settings(settings)

    # 3. Company-view report (Phase 3)
    cards: list[tuple[str, dict]] = []
    if _is_enabled(settings, KEY_COMPANY_ENABLED, default=True):
        narrative = narrate_company(facts, ai_settings=ai_settings, no_ai=no_ai)
        debug["company"] = {
            "status": narrative.status,
            "tone": narrative.tone,
            "fallback_reason": narrative.fallback_reason,
            "summary_preview": (narrative.summary or "")[:80],
        }
        card = build_company_card(facts, narrative)
        cards.append((f"company_daily_report {window.label}", card))
    else:
        log.info("company report disabled (%s=0); skipping",
                 KEY_COMPANY_ENABLED)

    # 4. Personal-view report (Phase 4)
    if _is_enabled(settings, KEY_PERSONAL_ENABLED, default=True):
        p_narrative = narrate_personal(
            facts, ai_settings=ai_settings, no_ai=no_ai,
        )
        debug["personal"] = {
            "status": p_narrative.status,
            "fallback_reason": p_narrative.fallback_reason,
            "n_active": sum(1 for e in p_narrative.entries if e.has_activity),
            "n_inactive": sum(1 for e in p_narrative.entries if not e.has_activity),
        }
        cards.append((
            f"personal_daily_report {window.label}",
            build_personal_card(facts, p_narrative),
        ))
    else:
        log.info("personal report disabled (%s=0); skipping",
                 KEY_PERSONAL_ENABLED)

    debug["status"] = "rendered"
    debug["n_cards"] = len(cards)

    # 5. Send (or skip on dry-run)
    if dry_run:
        log.info("dry-run: skipping broadcast (would send %d card(s))",
                 len(cards))
        debug["cards"] = [c for _, c in cards]
        return 0, debug

    if not cards:
        log.info("no cards to send (all reports disabled)")
        return 0, debug

    if notifier is None:
        log.error("notifier not provided and not dry_run; cannot send")
        return 1, {**debug, "error": "no notifier"}

    sent = 0
    for event_label, card in cards:
        try:
            notifier.broadcast_card(card, event=event_label)
            sent += 1
        except Exception as e:  # noqa: BLE001
            log.exception("broadcast failed for %s", event_label)
            debug.setdefault("broadcast_errors", []).append(
                f"{event_label}: {e}",
            )

    debug["n_sent"] = sent
    if sent < len(cards):
        return 1, debug
    return 0, debug


# --------------------------------------------------------------------------- #
# Internals                                                                   #
# --------------------------------------------------------------------------- #


def _is_disabled(settings, key: str) -> bool:
    raw = (settings.get(key) or "1").strip().lower()
    return raw in ("0", "false", "off", "no")


def _is_enabled(settings, key: str, *, default: bool) -> bool:
    raw = settings.get(key)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() not in ("0", "false", "off", "no")


def _read_push_time(settings) -> tuple[int, int]:
    """读 push_time(HH:MM)→ (hour, minute)。坏值兜底 09:30。"""
    raw = (settings.get(KEY_PUSH_TIME) or "09:30").strip()
    try:
        hh, mm = raw.split(":")
        h, m = int(hh), int(mm)
        if 0 <= h < 24 and 0 <= m < 60:
            return h, m
    except (ValueError, AttributeError):
        pass
    return 9, 30


def _read_window_hours(settings) -> int:
    """读 time_window_hours,默认 24,合法范围 [1, 168]。"""
    raw = settings.get(KEY_TIME_WINDOW_HOURS)
    if raw is None or not str(raw).strip():
        return 24
    try:
        v = int(str(raw).strip())
        if 1 <= v <= 168:
            return v
    except (TypeError, ValueError):
        pass
    return 24


def _load_ai_settings(settings) -> AISettings | None:
    """复用主服务 chat 助手已配置的 AI 端点(server/api/ai.py 的 KEY_*)。
    api_key 为空时返回 None,company_narrate 会走 fallback。"""
    from server.ai.client import DEFAULT_BASE_URL, DEFAULT_MODEL

    api_key = (settings.get("ai.openrouter_api_key") or "").strip()
    if not api_key:
        return None
    return AISettings(
        api_key=api_key,
        base_url=(settings.get("ai.base_url") or DEFAULT_BASE_URL).strip(),
        model=(settings.get("ai.model") or DEFAULT_MODEL).strip(),
    )
