"""Tests for discuss-summarize gather step (includes permission check)."""
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
        f"---\ntype: proposal\nauthor: {author}\n---\n# proposal body\n",
        encoding="utf-8",
    )


def _run(tmp_path: Path, user: str) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "PIVOT_TENANT_ID": "t",
        "PIVOT_USER_ID": user,
        "PIVOT_WORKSPACE_DIR": str(tmp_path),
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


class TestGather:
    def test_author_can_gather(self, tmp_path: Path):
        _seed(tmp_path, author="ken")
        proc = _run(tmp_path, user="ken")
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        assert len(out["output"]["posts"]) == 1
        assert out["output"]["posts"][0]["author"] == "ken"

    def test_non_author_is_rejected(self, tmp_path: Path):
        _seed(tmp_path, author="ken")
        proc = _run(tmp_path, user="shengli")
        assert proc.returncode != 0
        assert "PermissionError" in proc.stderr or "Only the thread author" in proc.stderr
