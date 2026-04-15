"""Tests for discuss-list list_threads step."""
import json
import os
import subprocess
import sys
from pathlib import Path


STEP = Path(__file__).parent / "list_threads.py"


def _seed(tmp_path: Path, category: str, thread: str, status: str):
    thread_dir = tmp_path / "discussions" / category / thread
    thread_dir.mkdir(parents=True)
    (thread_dir / "001_ken_proposal_xxxxxx.md").write_text(
        "---\ntype: proposal\nauthor: ken\n---\n# p\n", encoding="utf-8"
    )
    idx_dir = tmp_path / "index"
    idx_dir.mkdir(parents=True, exist_ok=True)
    (idx_dir / f"{thread}-discuss.index.yaml").write_text(
        f"origin_path: discussions/{category}/{thread}/\n"
        f"created: 2026-04-11T10:00:00+08:00\n"
        f"last_updated: 2026-04-11T12:00:00+08:00\n"
        f"discussions:\n"
        f"  - path: discussions/{category}/{thread}/\n"
        f"    status: {status}\n"
        f"    files:\n"
        f"      - path: 001_ken_proposal_xxxxxx.md\n"
        f"        summary: first proposal\n"
        f"        refs: []\n"
        f"timeline: []\n",
        encoding="utf-8",
    )


def _run(tmp_path: Path, category_filter: str = "") -> dict:
    env = {
        **os.environ,
        "PIVOT_TENANT_ID": "t",
        "PIVOT_USER_ID": "u",
        "PIVOT_DATA_SPACE_DIR": str(tmp_path),
        "PIVOT_APP_NAME": "pivot",
    }
    proc = subprocess.run(
        [sys.executable, str(STEP)],
        input=json.dumps({"input": {"category": category_filter}, "steps": {}}),
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


class TestListThreads:
    def test_enriches_with_status_display(self, tmp_path: Path):
        _seed(tmp_path, "enclaws", "alpha", "open")
        _seed(tmp_path, "enclaws", "beta", "concluded")
        result = _run(tmp_path)
        names = sorted(t["slug"] for t in result["output"]["threads"])
        assert names == ["alpha", "beta"]
        by_slug = {t["slug"]: t for t in result["output"]["threads"]}
        assert by_slug["alpha"]["status_display"] == "讨论中"
        assert by_slug["beta"]["status_display"] == "已达成结论"
        assert by_slug["alpha"]["summary"] == "first proposal"

    def test_category_filter(self, tmp_path: Path):
        _seed(tmp_path, "enclaws", "a", "open")
        _seed(tmp_path, "marketing", "b", "open")
        result = _run(tmp_path, category_filter="enclaws")
        assert len(result["output"]["threads"]) == 1
        assert result["output"]["threads"][0]["slug"] == "a"
