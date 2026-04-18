"""Tests for discuss-read fetch_posts step."""
import json
import os
import subprocess
import sys
from pathlib import Path


FETCH_STEP = Path(__file__).parent / "fetch_posts.py"
MARK_STEP = Path(__file__).parent / "mark_read.py"


def _seed(tmp_path: Path):
    cat = "enclaws"
    thread = "alpha"
    thread_dir = tmp_path / "discussions" / cat / thread
    thread_dir.mkdir(parents=True)
    (thread_dir / "001_ken_proposal_x.md").write_text(
        "---\ntype: proposal\nauthor: ken\nsummary: s1\n---\n# proposal body\n",
        encoding="utf-8",
    )
    (thread_dir / "002_shengli_reply_y.md").write_text(
        "---\ntype: reply\nauthor: shengli\nsummary: s2\n---\n# reply body\n",
        encoding="utf-8",
    )
    idx_dir = tmp_path / "index"
    idx_dir.mkdir(parents=True, exist_ok=True)
    (idx_dir / "alpha-discuss.index.yaml").write_text(
        "origin_path: discussions/enclaws/alpha/\n"
        "created: 2026-04-11T10:00:00+08:00\n"
        "last_updated: 2026-04-11T12:00:00+08:00\n"
        "discussions:\n"
        "  - path: discussions/enclaws/alpha/\n"
        "    status: open\n"
        "    files: []\n"
        "timeline: []\n",
        encoding="utf-8",
    )


def _run(step: Path, stdin: dict, env: dict) -> dict:
    proc = subprocess.run(
        [sys.executable, str(step)],
        input=json.dumps(stdin),
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _base_env(tmp_path: Path) -> dict:
    return {
        **os.environ,
        "ENCLAWS_TENANT_ID": "t",
        "ENCLAWS_TENANT_USER_ID": "shengli",
        "PIVOT_DATA_SPACE_DIR": str(tmp_path),
        "PIVOT_APP_NAME": "pivot",
    }


class TestFetchPosts:
    def test_returns_posts_and_status_display(self, tmp_path: Path):
        _seed(tmp_path)
        result = _run(
            FETCH_STEP,
            {"input": {"category": "enclaws", "thread": "alpha"}, "steps": {}},
            _base_env(tmp_path),
        )
        out = result["output"]
        assert out["status"] == "open"
        assert out["status_display"] == "讨论中"
        assert len(out["posts"]) == 2
        assert out["posts"][0]["filename"].startswith("001")
        assert out["posts"][1]["author"] == "shengli"


class TestMarkRead:
    def test_writes_read_state(self, tmp_path: Path):
        _seed(tmp_path)
        fetched = _run(
            FETCH_STEP,
            {"input": {"category": "enclaws", "thread": "alpha"}, "steps": {}},
            _base_env(tmp_path),
        )
        result = _run(
            MARK_STEP,
            {
                "input": {"category": "enclaws", "thread": "alpha"},
                "steps": {"fetch_posts": fetched},
            },
            _base_env(tmp_path),
        )
        assert result["output"]["marked"] is True
        state_path = tmp_path / ".pivot-state" / "read_state_shengli.json"
        assert state_path.exists()
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert "enclaws/alpha" in state["read_threads"]
