"""End-to-end daily-report orchestration (v2 多任务).

`run_daily_report_for_job(job, ...)` 是唯一入口:
  - 从 Job 对象拿配置(view / window_hours / push_time / receiver_type / receiver_ids)
  - 收集 matter 事件 + 聚合 + AI 叙事 + 渲染卡片
  - 按 receiver_type / receiver_ids 发送(broadcast 全部 / 指定群 / DM 个人)
  - runs 表 INSERT/finish 由 caller(JobScheduler / API)负责,本函数不碰

返回 (exit_code, debug_payload):
  0 — 成功(或 dry-run)
  1 — 部分发送失败 / broadcast 错误
  2 — 配置错误(workspace 未配置 / view 不识别等)
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
from server.daily_report.jobs_repo import Job
from server.daily_report.personal_narrate import narrate_personal
from server.daily_report.render import build_company_card, build_personal_card
from server.daily_report.shared_facts import build_shared_facts
from server.daily_report.types import TimeWindow
from server.daily_report.window import compute_window

log = logging.getLogger("server.daily_report.runner")


def run_daily_report_for_job(
    *,
    job: Job,
    db_path: Path,
    workspace_index_dir: Path,
    notifier,                                       # FeishuNotifier | NoOpNotifier
    dry_run: bool = False,
    no_ai: bool = False,
    now: datetime | None = None,
    explicit_window: TimeWindow | None = None,
    users_db_path: Path | None = None,
    report_url: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """跑一个 Job,返回 (rc, debug)。

    `users_db_path`(dev 用):如果给定,从该 sqlite 以 mode=ro 读取 users 列表
    (personal 视角全员),`db_path` 仍只用于 SettingsRepo(AI 配置)。这样
    可以本地启动 + 用主 data.db 的 AI key + 用生产快照的真实团队跑日报
    预览,绝不写入快照。生产/正常路径下置 None,二者都用 db_path。
    """
    if not db_path.exists():
        log.error("db_path does not exist: %s", db_path)
        return 2, {"error": f"db not found: {db_path}"}

    if not workspace_index_dir.is_dir():
        log.error("workspace_index_dir not found: %s", workspace_index_dir)
        return 2, {"error": f"workspace index dir missing: {workspace_index_dir}"}

    from server.db import Database
    from server.settings import SettingsRepo
    from server.users import ReadOnlyUserView, UserRepo

    db = Database(db_path)
    settings = SettingsRepo(db)

    if users_db_path is not None:
        if not users_db_path.exists():
            log.error("users_db_path does not exist: %s", users_db_path)
            return 2, {"error": f"users_db not found: {users_db_path}"}
        try:
            all_users = ReadOnlyUserView(users_db_path).list_all()
            log.info("daily-report users overridden: %s (%d users, read-only)",
                     users_db_path, len(all_users))
        except Exception as e:
            log.exception("ReadOnlyUserView failed for %s", users_db_path)
            return 2, {"error": f"users_db_path open failed: {e}"}
    else:
        all_users = UserRepo(db).list_all()

    # 1. 计算时间窗口
    if explicit_window is not None:
        window = explicit_window
    else:
        push_h, push_m = _parse_hhmm(job.push_time)
        window = compute_window(
            now or datetime.now().astimezone(),
            push_hour=push_h, push_minute=push_m,
            window_hours=job.window_hours,
        )

    # 2. 收集 + 聚合
    matter_events = collect_matter_events(workspace_index_dir, window)
    activities, summary = aggregate(matter_events, all_users, window)
    facts = build_shared_facts(matter_events, activities, summary, window)

    debug: dict[str, Any] = {
        "job_id": job.id,
        "view": job.view,
        "window": {
            "since": window.since.isoformat(),
            "until": window.until.isoformat(),
        },
        "n_users": len(activities),
        "n_active": facts.n_active,
        "n_inactive": len(summary.inactive_users),
        "n_matter_events": len(matter_events),
        "matters_touched": summary.matters_touched,
    }

    # 3. AI 调用 + 渲染卡片(根据 view)
    ai_settings = _load_ai_settings(settings)
    if job.view == "company":
        narrative = narrate_company(facts, ai_settings=ai_settings, no_ai=no_ai)
        full_card = build_company_card(facts, narrative)
        card = build_company_card(
            facts, narrative, report_url=report_url, compact=bool(report_url),
        )
        debug["narrative_status"] = narrative.status
        debug["tone"] = narrative.tone
        debug["fallback_reason"] = narrative.fallback_reason
    elif job.view == "personal":
        narrative = narrate_personal(facts, ai_settings=ai_settings, no_ai=no_ai)
        full_card = build_personal_card(facts, narrative)
        card = build_personal_card(
            facts, narrative, report_url=report_url, compact=bool(report_url),
        )
        debug["narrative_status"] = narrative.status
        debug["fallback_reason"] = narrative.fallback_reason
    else:
        return 2, {**debug, "error": f"unknown view: {job.view}"}
    debug["full_card"] = full_card

    # 4. dry-run 短路
    if dry_run:
        log.info("dry-run job=%d view=%s, skipping broadcast", job.id, job.view)
        debug["card"] = card
        debug["dry_run"] = True
        return 0, debug

    debug["card"] = card
    debug["report_url"] = report_url

    # 5. 按 receiver_type / receiver_ids 发送
    event_label = f"job-{job.id} {job.view} {window.label}"
    if job.receiver_type == "groups":
        if job.receiver_ids:
            sent, total, failures = notifier.send_card_to_chats(
                card, list(job.receiver_ids), event=event_label,
            )
            debug["receivers"] = {
                "type": "groups", "sent": sent, "total": total,
                "failures": failures,
            }
            if sent < total:
                debug["error"] = _summarize_failures(failures)
                return 1, debug
        else:
            # 默认全部 bot 群,沿用旧接口
            try:
                notifier.broadcast_card(card, event=event_label)
                debug["receivers"] = {"type": "groups", "mode": "broadcast_all"}
            except Exception as e:  # noqa: BLE001
                log.exception("broadcast failed for job %d", job.id)
                return 1, {**debug, "error": f"broadcast: {e}"}
    elif job.receiver_type == "users":
        if not job.receiver_ids:
            log.error("job %d receiver_type=users but receiver_ids is empty", job.id)
            return 2, {**debug, "error": "users receiver_type requires receiver_ids"}
        sent, total, failures = notifier.send_card_to_users(
            card, list(job.receiver_ids), event=event_label,
        )
        debug["receivers"] = {
            "type": "users", "sent": sent, "total": total,
            "failures": failures,
        }
        if sent < total:
            debug["error"] = _summarize_failures(failures)
            return 1, debug
    else:
        return 2, {**debug, "error": f"unknown receiver_type: {job.receiver_type}"}

    return 0, debug


def _summarize_failures(failures: list[dict]) -> str:
    """把 [{to, error}] 列表压成一段简短的人读字符串。
    用于 debug["error"] / runs.error / 失败告警卡的 error 字段。
    告警卡再单独附上 'name (open_id) — error' 详细行,这里只做兜底简介。"""
    if not failures:
        return "broadcast partial"
    n = len(failures)
    parts = []
    for f in failures[:2]:
        to = (f.get("to") or "?")
        # open_id 通常比较长,缩到尾 8 位
        short = to if len(to) <= 12 else f"…{to[-8:]}"
        parts.append(f"{short}({(f.get('error') or '?')[:40]})")
    suffix = f" +{n - 2} more" if n > 2 else ""
    return f"{n} failed: " + "; ".join(parts) + suffix


def _parse_hhmm(s: str) -> tuple[int, int]:
    """解析 'HH:MM',坏值兜底 09:30。"""
    try:
        hh, mm = s.split(":")
        h, m = int(hh), int(mm)
        if 0 <= h < 24 and 0 <= m < 60:
            return h, m
    except (ValueError, AttributeError):
        pass
    return 9, 30


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
