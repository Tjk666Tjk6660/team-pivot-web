"""Smoke tests for `server.daily_report.runner.run_daily_report`. Exercises
the full pipeline end-to-end with fakes — no real AI / no real Feishu /
no real workspace."""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from server.daily_report.runner import run_daily_report
from server.daily_report.window import CHINA_TZ
from server.db import Database
from server.settings import SettingsRepo
from server.users import UserRepo


# --------------------------------------------------------------------------- #
# helpers (local fakes)                                                       #
# --------------------------------------------------------------------------- #


class _CapturingNotifier:
    """Records broadcast calls. Stand-in for FeishuNotifier."""
    def __init__(self):
        self.calls: list[tuple[dict, str]] = []

    def broadcast_card(self, card: dict, *, event: str) -> None:
        self.calls.append((card, event))


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
        encoding="utf-8", errors="replace",
        env={**os.environ, **(env or {})},
    )
    return proc.stdout


def _init_code_mirror(repo: Path) -> None:
    """Create a tiny git repo standing in for the code mirror workspace."""
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "--initial-branch=main", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")


def _commit(
    repo: Path, *, file: str, msg: str,
    author_name: str, author_email: str,
    when: str = "2026-04-26T15:00:00+08:00",
) -> None:
    (repo / file).write_text("x\n", encoding="utf-8")
    _git(repo, "add", file)
    env = {
        "GIT_AUTHOR_NAME": author_name,
        "GIT_AUTHOR_EMAIL": author_email,
        "GIT_COMMITTER_NAME": author_name,
        "GIT_COMMITTER_EMAIL": author_email,
        "GIT_AUTHOR_DATE": when,
        "GIT_COMMITTER_DATE": when,
    }
    _git(repo, "commit", "-m", msg, env=env)


def _write_matter(index_dir: Path, matter_id: str, item: dict) -> None:
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / f"{matter_id}.index.yaml").write_text(yaml.safe_dump({
        "version": 1,
        "matter": {
            "id": matter_id,
            "title": matter_id,
            "current_status": "executing",
            "created_at": "2026-04-26T08:00:00+08:00",
            "updated_at": "2026-04-26T18:00:00+08:00",
        },
        "timeline": [item],
    }, allow_unicode=True), encoding="utf-8")


def _setup_db(tmp_path: Path) -> Path:
    """Make a fresh SQLite db with one registered user, return its path."""
    db_path = tmp_path / "data.db"
    db = Database(db_path)
    repo = UserRepo(db)
    repo.upsert_from_feishu(
        open_id="ou_alice", union_id=None, name="Alice", avatar_url="",
    )
    repo.update_profile("ou_alice", pinyin="alice")
    return db_path


def _now() -> datetime:
    """Fixed point so window = [2026-04-26 09:30, 2026-04-27 09:30)."""
    return datetime(2026, 4, 27, 9, 30, tzinfo=CHINA_TZ)


# --------------------------------------------------------------------------- #
# smoke test: full pipeline with no AI                                        #
# --------------------------------------------------------------------------- #


def test_dry_run_full_pipeline_without_ai(tmp_path):
    """Full pipeline:setup db + workspace + code mirror, dry-run with --no-ai,
    expect exit=0 + a card dict in debug."""
    db_path = _setup_db(tmp_path)

    # Pivot data workspace
    workspace_index = tmp_path / "workspace" / "index"
    _write_matter(workspace_index, "demo", {
        "file": "discussions/x/demo/001_alice_think_aaa.md",
        "type": "think",
        "created_at": "2026-04-26T15:00:00+08:00",
        "creator": "alice", "owner": "alice",
        "summary": "morning thoughts",
    })

    # Code mirror
    code_repo = tmp_path / "code-mirror"
    _init_code_mirror(code_repo)
    _commit(
        code_repo, file="src.py", msg="feat: implement",
        author_name="alice", author_email="alice@stacs.cn",
    )

    rc, debug = run_daily_report(
        db_path=db_path,
        workspace_index_dir=workspace_index,
        code_repo_dir=code_repo,
        now=_now(),
        dry_run=True,
        no_ai=True,
    )
    assert rc == 0
    assert debug["status"] == "rendered"
    assert debug["scoring_status"] == "fallback"   # no AI
    assert debug["n_active"] == 1                   # alice
    assert debug["n_matter_events"] == 1
    assert debug["n_commits"] == 1
    assert debug["n_unattributed"] == 0             # alice@stacs.cn matches via tier 6
    assert debug["fetch_warning"] is None           # mirror was a real git repo

    card = debug["card"]
    assert "团队日报" in card["header"]["title"]["content"]


def test_pipeline_sends_via_notifier_when_not_dry_run(tmp_path):
    """Without dry_run, the runner calls notifier.broadcast_card once."""
    db_path = _setup_db(tmp_path)
    workspace_index = tmp_path / "workspace" / "index"
    workspace_index.mkdir(parents=True)
    code_repo = tmp_path / "code-mirror"
    _init_code_mirror(code_repo)

    notifier = _CapturingNotifier()
    rc, debug = run_daily_report(
        db_path=db_path,
        workspace_index_dir=workspace_index,
        code_repo_dir=code_repo,
        now=_now(),
        dry_run=False,
        no_ai=True,
        notifier=notifier,
    )
    assert rc == 0
    assert len(notifier.calls) == 1
    card, event = notifier.calls[0]
    assert "daily_report 4-26" == event
    assert card["header"]["title"]["content"] == "📊 团队日报 · 4-26"


def test_disabled_via_settings_returns_zero_no_send(tmp_path):
    """KEY_ENABLED=0 → exit 0, no broadcast, status='disabled'."""
    db_path = _setup_db(tmp_path)
    db = Database(db_path)
    SettingsRepo(db).set("daily_report.enabled", "0")

    workspace_index = tmp_path / "workspace" / "index"
    workspace_index.mkdir(parents=True)

    notifier = _CapturingNotifier()
    rc, debug = run_daily_report(
        db_path=db_path,
        workspace_index_dir=workspace_index,
        now=_now(),
        notifier=notifier,
    )
    assert rc == 0
    assert debug["status"] == "disabled"
    assert notifier.calls == []


def test_missing_workspace_returns_exit_code_2(tmp_path):
    db_path = _setup_db(tmp_path)
    rc, debug = run_daily_report(
        db_path=db_path,
        workspace_index_dir=tmp_path / "no-such-workspace",
        now=_now(),
        dry_run=True,
        no_ai=True,
    )
    assert rc == 2
    assert "workspace index dir missing" in debug["error"]


def test_missing_db_returns_exit_code_2(tmp_path):
    rc, debug = run_daily_report(
        db_path=tmp_path / "no-db.sqlite",
        workspace_index_dir=tmp_path,
        now=_now(),
        dry_run=True,
        no_ai=True,
    )
    assert rc == 2
    assert "db not found" in debug["error"]


def test_missing_code_mirror_surfaces_as_fetch_warning(tmp_path):
    """Mirror dir absent → fetch_warning populated, but report still produced."""
    db_path = _setup_db(tmp_path)
    workspace_index = tmp_path / "workspace" / "index"
    workspace_index.mkdir(parents=True)

    rc, debug = run_daily_report(
        db_path=db_path,
        workspace_index_dir=workspace_index,
        code_repo_dir=tmp_path / "no-mirror",
        now=_now(),
        dry_run=True,
        no_ai=True,
    )
    assert rc == 0   # report still goes out
    assert debug["fetch_warning"] is not None
    assert "未初始化" in debug["fetch_warning"]


def test_overrides_from_settings_applied(tmp_path):
    """Settings JSON override → unattributed commit gets matched."""
    db_path = _setup_db(tmp_path)
    db = Database(db_path)
    SettingsRepo(db).set(
        "daily_report.commit_author_overrides",
        json.dumps({"alice": ["weird@host.local"]}),
    )

    workspace_index = tmp_path / "workspace" / "index"
    workspace_index.mkdir(parents=True)
    code_repo = tmp_path / "code-mirror"
    _init_code_mirror(code_repo)
    # Commit with email that wouldn't match by any other tier
    _commit(
        code_repo, file="src.py", msg="feat: x",
        author_name="ext", author_email="weird@host.local",
    )

    rc, debug = run_daily_report(
        db_path=db_path,
        workspace_index_dir=workspace_index,
        code_repo_dir=code_repo,
        now=_now(),
        dry_run=True,
        no_ai=True,
    )
    assert rc == 0
    assert debug["n_commits"] == 1
    assert debug["n_unattributed"] == 0   # override worked


def test_broadcast_failure_returns_exit_code_1(tmp_path):
    """notifier.broadcast_card raises → exit 1."""
    db_path = _setup_db(tmp_path)
    workspace_index = tmp_path / "workspace" / "index"
    workspace_index.mkdir(parents=True)
    code_repo = tmp_path / "code-mirror"
    _init_code_mirror(code_repo)

    class _BoomNotifier:
        def broadcast_card(self, card, *, event):
            raise RuntimeError("simulated network failure")

    rc, debug = run_daily_report(
        db_path=db_path,
        workspace_index_dir=workspace_index,
        code_repo_dir=code_repo,
        now=_now(),
        dry_run=False,
        no_ai=True,
        notifier=_BoomNotifier(),
    )
    assert rc == 1
    assert "simulated network failure" in debug["error"]
