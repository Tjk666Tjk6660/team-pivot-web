"""Dev-only preview: render the daily report card against a local matter
index without touching git or sending to Feishu.

Designed for iterating on the AI prompt against real data.

Safety guarantees(对生产数据零写风险):
- 不实例化 `Workspace` → 不会 git pull / git push
- 仅 `collect_matter_events` 读 `index/*.index.yaml`(纯读 YAML)
- `dry_run=True` 让 runner 跳过 broadcast 路径
- 显式传 `NoOpNotifier` 作为兜底 — 即使 dry-run 失效也不会发飞书

Usage:
    uv run python scripts/preview_daily_report.py [options]

Examples:
    # 公司视角,过去 36 小时,跳 AI(快速看分桶 + 兜底文案)
    uv run python scripts/preview_daily_report.py --view company --hours 36 --no-ai

    # 个人视角,过去 24 小时,启用 AI(读 dev data.db 里配的 AI key)
    uv run python scripts/preview_daily_report.py --view personal --hours 24

    # 从指定 db 读 AI 配置 + 用户列表
    uv run python scripts/preview_daily_report.py --db tests/test_output/data.db
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from server.daily_report.jobs_repo import Job
from server.daily_report.runner import run_daily_report_for_job
from server.daily_report.types import TimeWindow
from server.daily_report.window import CHINA_TZ
from server.notify import NoOpNotifier

# Windows cp936 终端打不出 emoji,把 stdout 强制成 utf-8;
# 不可显示字符 fallback 为 \u 转义,不会因为编码错误整个打断输出。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:
    pass


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument(
        "--view", choices=["company", "personal"], default="company",
        help="视角:公司或个人",
    )
    p.add_argument(
        "--hours", type=int, default=36,
        help="窗口往前回看小时数(默认 36)",
    )
    p.add_argument(
        "--index-dir", type=Path,
        default=Path("tests/test_output/git/pivot-database/index"),
        help="matter index 目录(默认指向 dev/prod 共用的本地克隆)",
    )
    p.add_argument(
        "--db", type=Path,
        default=Path("tests/test_output/data.db"),
        help="SQLite 数据库(用于读 AI 配置 + 用户列表)",
    )
    p.add_argument(
        "--no-ai", action="store_true",
        help="跳过 AI 调用,使用 fallback 文案(快 + 不烧 key)",
    )
    p.add_argument(
        "--dump-debug", action="store_true",
        help="打印完整 debug payload(JSON)而不是仅卡片",
    )
    p.add_argument(
        "--out", type=Path, default=None,
        help="同时写到指定文件(utf-8),适合 Windows 终端看不全 emoji 时",
    )
    args = p.parse_args()

    if not args.index_dir.is_dir():
        print(f"ERROR: index dir not found: {args.index_dir}")
        return 1
    if not args.db.exists():
        print(f"ERROR: db not found: {args.db}")
        return 1

    now = datetime.now(tz=CHINA_TZ)
    window = TimeWindow(since=now - timedelta(hours=args.hours), until=now)

    # 构造一个 dummy Job —— runner 在 dry_run=True 时不读 receiver/channel
    dummy = Job(
        id=0, name="preview", view=args.view, status="active",
        push_time="09:30", push_freq="daily",
        window_hours=args.hours,
        channel="feishu",
        receiver_type="groups", receiver_ids=None,
        next_run_at=None, last_run_id=None, last_status=None,
        retry_count=0, last_notified_at=None,
        created_by=None, created_at=now, updated_at=now,
    )

    rc, debug = run_daily_report_for_job(
        job=dummy,
        db_path=args.db,
        workspace_index_dir=args.index_dir,
        notifier=NoOpNotifier(),                  # 双保险:即便 dry-run 失效也不发
        dry_run=True,
        no_ai=args.no_ai,
        now=now,
        explicit_window=window,
    )

    lines: list[str] = []
    lines.append(f"=== preview rc={rc} view={args.view} window={args.hours}h ===")
    lines.append(f"window: {debug['window']['since']} → {debug['window']['until']}")
    lines.append(f"matter events: {debug.get('n_matter_events')}, "
                 f"matters touched: {debug.get('matters_touched')}")
    lines.append(f"users active: {debug.get('n_active')}, "
                 f"inactive: {debug.get('n_inactive')}")
    lines.append(f"narrative status: {debug.get('narrative_status')}")
    if debug.get("tone"):
        lines.append(f"tone: {debug['tone']}")
    if debug.get("fallback_reason"):
        lines.append(f"fallback reason: {debug['fallback_reason']}")

    if args.dump_debug:
        lines.append("")
        lines.append("=== full debug payload ===")
        lines.append(json.dumps(debug, ensure_ascii=False, indent=2, default=str))
    else:
        card = debug.get("card")
        if not card:
            lines.append("")
            lines.append("(no card payload — likely error)")
        else:
            header = card.get("header", {})
            title = header.get("title", {}).get("content", "?")
            template = header.get("template", "?")
            lines.append("")
            lines.append(f"=== rendered card · template={template} ===")
            lines.append(f"# {title}")
            lines.append("")
            for el in card.get("body", {}).get("elements", []):
                if el.get("tag") == "markdown":
                    lines.append(el.get("content", ""))

    text = "\n".join(lines) + "\n"
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"\n(also written to {args.out})", flush=True)

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
