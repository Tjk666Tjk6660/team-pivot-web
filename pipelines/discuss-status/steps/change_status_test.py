"""Tests for discuss-status change_status step (close/pending/reopen)."""
import json
import os
import subprocess
import sys
from pathlib import Path


STEP = Path(__file__).parent / "change_status.py"


def _seed(tmp_git_repo: Path, status: str = "open"):
    thread_dir = tmp_git_repo / "discussions" / "enclaws" / "alpha"
    thread_dir.mkdir(parents=True)
    (thread_dir / "001_ken_proposal_x.md").write_text(
        "---\ntype: proposal\nauthor: ken\n---\n# p\n", encoding="utf-8"
    )
    idx_dir = tmp_git_repo / "index"
    idx_dir.mkdir(parents=True, exist_ok=True)
    (idx_dir / "alpha-discuss.index.yaml").write_text(
        f"origin_path: discussions/enclaws/alpha/\n"
        f"created: '2026-04-11T10:00:00+08:00'\n"
        f"last_updated: '2026-04-11T10:00:00+08:00'\n"
        f"discussions:\n"
        f"  - path: discussions/enclaws/alpha/\n"
        f"    status: {status}\n"
        f"    files: []\n"
        f"timeline: []\n",
        encoding="utf-8",
    )


def _run(tmp_git_repo: Path, action: str, reason: str = "") -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "PIVOT_TENANT_ID": "t",
        "PIVOT_USER_ID": "ken",
        "PIVOT_DATA_SPACE_DIR": str(tmp_git_repo),
        "PIVOT_APP_NAME": "pivot",
    }
    return subprocess.run(
        [sys.executable, str(STEP)],
        input=json.dumps(
            {
                "input": {
                    "category": "enclaws",
                    "thread": "alpha",
                    "action": action,
                    "reason": reason,
                },
                "steps": {},
            }
        ),
        capture_output=True,
        text=True,
        env=env,
    )


class TestChangeStatus:
    def test_close_action_transitions_open_to_closed(self, tmp_git_repo: Path):
        _seed(tmp_git_repo, status="open")
        proc = _run(tmp_git_repo, "close")
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)["output"]
        assert out["prev_status"] == "open"
        assert out["new_status"] == "closed"
        assert out["new_status_display"] == "已关闭"

    def test_pending_action(self, tmp_git_repo: Path):
        _seed(tmp_git_repo, status="open")
        proc = _run(tmp_git_repo, "pending")
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)["output"]
        assert out["new_status"] == "pending"
        assert out["new_status_display"] == "暂时搁置"

    def test_reopen_requires_reason(self, tmp_git_repo: Path):
        _seed(tmp_git_repo, status="closed")
        proc = _run(tmp_git_repo, "reopen", reason="")
        assert proc.returncode != 0
        assert "reason" in proc.stderr.lower()

    def test_reopen_with_reason_transitions_to_open(self, tmp_git_repo: Path):
        _seed(tmp_git_repo, status="closed")
        proc = _run(tmp_git_repo, "reopen", reason="new info emerged")
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)["output"]
        assert out["prev_status"] == "closed"
        assert out["new_status"] == "open"

    def test_unknown_action_raises(self, tmp_git_repo: Path):
        _seed(tmp_git_repo)
        proc = _run(tmp_git_repo, "foo")
        assert proc.returncode != 0
        assert "Unknown action" in proc.stderr
