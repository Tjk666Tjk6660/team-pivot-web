"""Tests for discuss-inbox check_inbox step."""
import json
import os
import subprocess
import sys
from pathlib import Path


STEP = Path(__file__).parent / "check_inbox.py"


def _seed_thread(tmp_path: Path, slug: str, last_updated: str, status: str = "open"):
    thread_dir = tmp_path / "discussions" / "enclaws" / slug
    thread_dir.mkdir(parents=True)
    (thread_dir / "001_ken_proposal_x.md").write_text(
        "---\ntype: proposal\nauthor: ken\n---\n# t\n", encoding="utf-8"
    )
    idx_dir = tmp_path / "index"
    idx_dir.mkdir(parents=True, exist_ok=True)
    (idx_dir / f"{slug}-discuss.index.yaml").write_text(
        f"origin_path: discussions/enclaws/{slug}/\n"
        f"created: 2026-04-01T00:00:00+08:00\n"
        f"last_updated: {last_updated}\n"
        f"discussions:\n"
        f"  - path: discussions/enclaws/{slug}/\n"
        f"    status: {status}\n"
        f"    files: []\n"
        f"timeline: []\n",
        encoding="utf-8",
    )


def _run(tmp_path: Path) -> dict:
    env = {
        **os.environ,
        "PIVOT_TENANT_ID": "t",
        "PIVOT_USER_ID": "shengli",
        "PIVOT_DATA_SPACE_DIR": str(tmp_path),
        "PIVOT_APP_NAME": "pivot",
    }
    proc = subprocess.run(
        [sys.executable, str(STEP)],
        input=json.dumps({"input": {}, "steps": {}}),
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


class TestCheckInbox:
    def test_returns_unread_threads_with_status_display(self, tmp_path: Path):
        _seed_thread(tmp_path, "alpha", "2026-04-11T12:00:00+08:00", "open")
        _seed_thread(tmp_path, "beta", "2026-04-11T08:00:00+08:00", "closed")

        state_dir = tmp_path / ".pivot-state"
        state_dir.mkdir()
        (state_dir / "read_state_shengli.json").write_text(
            json.dumps(
                {
                    "user_id": "shengli",
                    "read_threads": {"enclaws/alpha": "2026-04-11T11:00:00+08:00"},
                }
            ),
            encoding="utf-8",
        )

        result = _run(tmp_path)
        unread = result["output"]["unread"]
        slugs = {u["slug"] for u in unread}
        assert "alpha" in slugs
        assert "beta" in slugs

        by_slug = {u["slug"]: u for u in unread}
        assert by_slug["alpha"]["status_display"] == "讨论中"
        assert by_slug["beta"]["status_display"] == "已关闭"

    def test_read_thread_not_in_unread(self, tmp_path: Path):
        _seed_thread(tmp_path, "alpha", "2026-04-11T10:00:00+08:00")
        state_dir = tmp_path / ".pivot-state"
        state_dir.mkdir()
        (state_dir / "read_state_shengli.json").write_text(
            json.dumps({"read_threads": {"enclaws/alpha": "2026-04-11T10:00:00+08:00"}}),
            encoding="utf-8",
        )
        result = _run(tmp_path)
        assert result["output"]["unread"] == []
