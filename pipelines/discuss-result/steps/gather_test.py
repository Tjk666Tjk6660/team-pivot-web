"""Tests for discuss-result gather step (permission check)."""
import json
import os
import subprocess
import sys
from pathlib import Path


STEP = Path(__file__).parent / "gather.py"


def _seed(tmp_path: Path, author: str = "ken"):
    thread_dir = tmp_path / "discussions" / "enclaws" / "alpha"
    thread_dir.mkdir(parents=True)
    (thread_dir / "001_ken_proposal_x.md").write_text(
        f"---\ntype: proposal\nauthor: {author}\n---\n# proposal\n",
        encoding="utf-8",
    )


def _run(tmp_path: Path, user: str) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "ENCLAWS_TENANT_ID": "t",
        "ENCLAWS_TENANT_USER_ID": user,
        "PIVOT_DATA_SPACE_DIR": str(tmp_path),
        "PIVOT_APP_NAME": "pivot",
    }
    return subprocess.run(
        [sys.executable, str(STEP)],
        input=json.dumps(
            {"input": {"category": "enclaws", "thread": "alpha"}, "steps": {}}
        ),
        capture_output=True,
        text=True,
        env=env,
    )


class TestResultGather:
    def test_author_can_gather(self, tmp_path: Path):
        _seed(tmp_path)
        proc = _run(tmp_path, user="ken")
        assert proc.returncode == 0, proc.stderr

    def test_non_author_rejected(self, tmp_path: Path):
        _seed(tmp_path)
        proc = _run(tmp_path, user="shengli")
        assert proc.returncode != 0
        assert "PermissionError" in proc.stderr or "Only the thread author" in proc.stderr
