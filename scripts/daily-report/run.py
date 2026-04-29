#!/usr/bin/env python3
"""Pivot 团队日报 · CLI 入口 (v0.2)

由 systemd timer (`team-pivot-daily-report.timer`) 每天 09:30 (Asia/Shanghai)
触发。也可由 admin 手动触发(POST /api/admin/daily-report/trigger,Phase 5)。

v0.2 主轴(基于 dengke #013):
- 只读 Pivot matter 数据,不接代码仓库
- 生成两份独立报告:公司视角(Phase 3)+ 个人视角(Phase 4 待落地)
- 共享底层事实数据,不共享 LLM 中间结果

CLI flags:
  --dry-run / --no-send   不广播,把所有 card JSON 打到 stdout
  --no-ai                 跳过 AI 调用,使用 fallback 文案
  --since / --until       回放显式窗口(ISO 8601 with tz)
  --db-path / --workspace-index
                          覆盖 .env 的默认路径
  --report-out PATH       把完整 debug JSON 写到 PATH
  --log-level             DEBUG / INFO / WARNING / ERROR (默认 INFO)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from server.daily_report.runner import run_daily_report  # noqa: E402
from server.daily_report.window import parse_iso_window  # noqa: E402


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _force_utf8_stdout() -> None:
    """Windows 默认 stdout = GBK,emoji 卡片 JSON 输出会失败。强制 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass


def _resolve_default_paths() -> tuple[Path, Path | None]:
    """Read .env to derive default db_path / workspace_index."""
    from server.config import load_config

    cfg = load_config()
    data_dir = Path(cfg.data_dir).resolve()
    db_path = data_dir / "data.db"

    workspace_index: Path | None = None
    git_dir = data_dir / "git"
    if git_dir.is_dir():
        repos = sorted(p for p in git_dir.iterdir() if (p / ".git").is_dir())
        if len(repos) == 1:
            workspace_index = repos[0] / "index"

    return db_path, workspace_index


def _build_notifier():
    """Build a FeishuNotifier from .env config. Returns NoOpNotifier when
    NOTIFY_ENABLED=false (developer / CI environments)."""
    from server.config import load_config
    from server.feishu_token import FeishuTokenManager
    from server.notify import FeishuNotifier, NoOpNotifier

    cfg = load_config()
    if not cfg.notify_enabled:
        return NoOpNotifier()
    tokens = FeishuTokenManager(
        app_id=cfg.feishu_app_id,
        app_secret=cfg.feishu_app_secret,
        cache_dir=Path(cfg.data_dir),
    )
    return FeishuNotifier(
        tokens=tokens,
        web_base_url="",     # daily-report doesn't deep-link
        workspace=None,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pivot 日报 v0.2 · 公司视角 + 个人视角(Phase 4 待落地)",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--since", help="窗口起 (ISO 8601 with tz, 例 '2026-04-28T09:00:00+08:00')")
    parser.add_argument("--until", help="窗口止 (同上)")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="不发飞书,把所有 card JSON 打到 stdout",
    )
    parser.add_argument(
        "--no-send", action="store_true",
        help="--dry-run 的别名",
    )
    parser.add_argument(
        "--no-ai", action="store_true",
        help="跳过 AI 调用,所有报告走 fallback 文案",
    )
    parser.add_argument("--db-path", type=Path, help="覆盖 SQLite 路径")
    parser.add_argument(
        "--workspace-index", type=Path,
        help="覆盖 matter index 目录 (默认 DATA_DIR/git/<repo>/index)",
    )
    parser.add_argument(
        "--report-out", type=Path,
        help="把 debug JSON 写到该文件",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        help="日志级别 (DEBUG/INFO/WARNING/ERROR)",
    )
    args = parser.parse_args(argv)

    _force_utf8_stdout()
    _setup_logging(args.log_level.upper())
    log = logging.getLogger("daily-report.cli")

    try:
        default_db, default_ws_index = _resolve_default_paths()
    except Exception as e:  # noqa: BLE001
        log.error("failed to load defaults from .env: %s", e)
        return 2

    db_path = args.db_path or default_db
    workspace_index = args.workspace_index or default_ws_index

    if workspace_index is None:
        log.error(
            "could not auto-detect matter workspace under DATA_DIR/git/; "
            "use --workspace-index to specify"
        )
        return 2

    window = None
    if args.since and args.until:
        try:
            window = parse_iso_window(args.since, args.until)
        except ValueError as e:
            log.error("bad --since/--until: %s", e)
            return 2
    elif args.since or args.until:
        log.error("--since and --until must be provided together")
        return 2

    dry_run = args.dry_run or args.no_send

    notifier = None
    if not dry_run:
        try:
            notifier = _build_notifier()
        except Exception as e:  # noqa: BLE001
            log.error("could not build FeishuNotifier: %s", e)
            return 1

    rc, debug = run_daily_report(
        db_path=db_path,
        workspace_index_dir=workspace_index,
        window=window,
        dry_run=dry_run,
        no_ai=args.no_ai,
        notifier=notifier,
    )

    # dry-run 模式下 print 卡片 JSON(可能多张)到 stdout
    if dry_run and "cards" in debug:
        for i, card in enumerate(debug["cards"], start=1):
            print(f"========== card {i} ==========", flush=True)
            print(json.dumps(card, ensure_ascii=False, indent=2), flush=True)

    if args.report_out:
        args.report_out.parent.mkdir(parents=True, exist_ok=True)
        args.report_out.write_text(
            json.dumps(debug, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        log.info("wrote debug payload to %s", args.report_out)

    log.info("daily-report finished rc=%d status=%s",
             rc, debug.get("status"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
