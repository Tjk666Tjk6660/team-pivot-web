#!/usr/bin/env python3
"""Pivot 团队日报 · CLI 入口

Triggered by systemd timer (`team-pivot-daily-report.timer`) every day at
09:30 (Asia/Shanghai). Default behavior: produce yesterday-09:30 →
today-09:30 daily report and broadcast to all Feishu groups the bot is in.

CLI flags:
  --dry-run / --no-send   Don't broadcast; print card JSON to stdout
  --no-ai                 Skip AI scoring (forces fallback)
  --since / --until       Replay an explicit window (ISO 8601 with tz)
  --db-path / --workspace-index / --code-repo-dir
                          Override paths discovered from .env
  --report-out PATH       Dump full debug JSON to PATH (debug aid)
  --log-level             DEBUG / INFO / WARNING / ERROR (default INFO)

Default paths come from the project's .env:
  db        = $DATA_DIR/data.db
  workspace = $DATA_DIR/git/<single-repo>/index   (auto-detected)

`code_repo_dir` is read from SQLite settings `daily_report.code_repo_dir`
(default `/opt/team-pivot-web/var/code-mirror/team-pivot-web`).

The card has no "进入 Pivot" button — daily report is decoupled from the
Pivot product, and there's no admin page that supports this task."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path


# This script lives at <repo>/scripts/daily-report/run.py
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
    """Windows defaults stdout to GBK, which fails on emoji in our card JSON.
    Force UTF-8 so `--dry-run` output is readable everywhere. No-op on Linux
    (stdout is already UTF-8)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass


def _resolve_default_paths() -> tuple[Path, Path | None]:
    """Read .env to derive default db_path / workspace_index.

    Returns (db_path, workspace_index_or_None). `workspace_index` is None
    when auto-detection is ambiguous (multiple repos under DATA_DIR/git/) —
    caller must specify --workspace-index.
    """
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
        # if 0 or >1 → leave None, force --workspace-index

    return db_path, workspace_index


def _build_notifier():
    """Build a FeishuNotifier from .env config. Returns NoOpNotifier when
    NOTIFY_ENABLED=false (developer / CI environments).

    The daily report only calls `broadcast_card`, which doesn't touch
    `_post_url` / `_matter_url`, so we can pass an empty `web_base_url`
    placeholder — it's never read on this code path."""
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
        description="Pivot 团队日报 - 24h 窗口聚合 + AI 评分 + 飞书群广播",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--since", help="窗口起 (ISO 8601 with tz, 例 '2026-04-26T09:30:00+08:00')")
    parser.add_argument("--until", help="窗口止 (同上格式)")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="不发飞书,把 card JSON 打到 stdout",
    )
    parser.add_argument(
        "--no-send", action="store_true",
        help="--dry-run 的别名,语义更清晰",
    )
    parser.add_argument(
        "--no-ai", action="store_true",
        help="跳过 AI 评分,直接 fallback (产出 + 推进 + 阻塞 + 协作 维度全空,用粗分)",
    )
    parser.add_argument("--db-path", type=Path, help="覆盖 SQLite 路径")
    parser.add_argument(
        "--workspace-index", type=Path,
        help="覆盖 matter index 目录 (默认 DATA_DIR/git/<repo>/index)",
    )
    parser.add_argument(
        "--code-repo-dir", type=Path,
        help="覆盖代码仓库 mirror 路径 (默认 settings 里 daily_report.code_repo_dir)",
    )
    parser.add_argument(
        "--report-out", type=Path,
        help="把 debug JSON 写到该文件 (回放调试用)",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        help="日志级别 (DEBUG/INFO/WARNING/ERROR)",
    )
    args = parser.parse_args(argv)

    _force_utf8_stdout()
    _setup_logging(args.log_level.upper())
    log = logging.getLogger("daily-report.cli")

    # Resolve defaults from .env
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

    # Window
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

    # Notifier (only when actually sending)
    notifier = None
    if not dry_run:
        try:
            notifier = _build_notifier()
        except Exception as e:  # noqa: BLE001
            log.error("could not build FeishuNotifier: %s", e)
            return 1

    # Run pipeline
    rc, debug = run_daily_report(
        db_path=db_path,
        workspace_index_dir=workspace_index,
        code_repo_dir=args.code_repo_dir,
        window=window,
        dry_run=dry_run,
        no_ai=args.no_ai,
        notifier=notifier,
    )

    if dry_run and "card" in debug:
        print(json.dumps(debug["card"], ensure_ascii=False, indent=2))

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
