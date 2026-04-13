"""Pipeline test: monitor-scan."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml


def _write_stale_index(workspace: str, slug: str):
    """Create a stale-open thread INDEX file directly."""
    ws = Path(workspace)
    thread_dir = ws / "discussions" / "test" / slug
    thread_dir.mkdir(parents=True)
    (thread_dir / "001_ken_proposal_x.md").write_text(
        "---\ntype: proposal\nauthor: ken\nindex_state: indexed\n---\n# p\n",
        encoding="utf-8",
    )
    idx_dir = ws / "index"
    idx_dir.mkdir(parents=True, exist_ok=True)
    old_time = (datetime.now(timezone.utc).astimezone() - timedelta(days=10)).isoformat()
    idx_content = (
        f"origin_path: discussions/test/{slug}/\n"
        f"created: '{old_time}'\n"
        f"last_updated: '{old_time}'\n"
        f"discussions:\n"
        f"  - path: discussions/test/{slug}/\n"
        f"    status: open\n"
        f"    files:\n"
        f"      - path: 001_ken_proposal_x.md\n"
        f"        summary: seed\n"
        f"        refs: []\n"
        f"timeline: []\n"
    )
    (idx_dir / f"{slug}-discuss.index.yaml").write_text(idx_content, encoding="utf-8")


class TestMonitorScan:
    def test_detects_stale_open_thread(self, runner):
        _write_stale_index(runner.workspace_dir, "stale-thread")
        result = runner.run("monitor-scan", {
            "window_hours": "24",
            "mention_window_hours": "48",
        })
        assert result.status == "completed", result.error
        assert result.output["stale_open_threads_count"] >= 1

    def test_empty_workspace_no_issues(self, runner):
        result = runner.run("monitor-scan", {
            "window_hours": "24",
            "mention_window_hours": "48",
        })
        assert result.status == "completed"
        assert result.output["stale_open_threads_count"] == 0
        assert result.output["un_replied_mentions_count"] == 0
