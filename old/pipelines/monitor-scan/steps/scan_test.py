"""Tests for monitor-scan scan step."""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


STEP = Path(__file__).parent / "scan.py"


def _write_idx(tmp_path: Path, slug: str, status: str, last_updated: str, timeline_entries=None):
    idx_dir = tmp_path / "index"
    idx_dir.mkdir(parents=True, exist_ok=True)
    thread_dir = tmp_path / "discussions" / "enclaws" / slug
    thread_dir.mkdir(parents=True, exist_ok=True)
    (thread_dir / "001_ken_proposal_x.md").write_text(
        "---\ntype: proposal\nauthor: ken\nindex_state: indexed\n---\n# p\n",
        encoding="utf-8",
    )
    tl_text = ""
    if timeline_entries:
        tl_text = "timeline:\n"
        for e in timeline_entries:
            tl_text += f"  - time: '{e['time']}'\n"
            tl_text += f"    event: {e['event']}\n"
            if e.get("mention"):
                tl_text += f"    mention:\n"
                for m in e["mention"]:
                    tl_text += f"      - user: {m['user']}\n"
                    tl_text += f"        comments: {m.get('comments','')}\n"
    else:
        tl_text = "timeline: []\n"
    (idx_dir / f"{slug}-discuss.index.yaml").write_text(
        f"origin_path: discussions/enclaws/{slug}/\n"
        f"created: '2026-04-01T00:00:00+08:00'\n"
        f"last_updated: '{last_updated}'\n"
        f"discussions:\n"
        f"  - path: discussions/enclaws/{slug}/\n"
        f"    status: {status}\n"
        f"    files:\n"
        f"      - path: 001_ken_proposal_x.md\n"
        f"        summary: seed\n"
        f"        refs: []\n"
        f"{tl_text}",
        encoding="utf-8",
    )


def _run(tmp_path: Path, window: str = "24", mention_window: str = "48") -> dict:
    env = {
        **os.environ,
        "ENCLAWS_TENANT_ID": "t",
        "ENCLAWS_TENANT_USER_ID": "monitor",
        "PIVOT_DATA_SPACE_DIR": str(tmp_path),
        "PIVOT_APP_NAME": "pivot",
    }
    proc = subprocess.run(
        [sys.executable, str(STEP)],
        input=json.dumps(
            {
                "input": {
                    "window_hours": window,
                    "mention_window_hours": mention_window,
                },
                "steps": {},
            }
        ),
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


class TestScan:
    def test_finds_stale_open_thread(self, tmp_path: Path):
        long_ago = (datetime.now(timezone.utc).astimezone() - timedelta(days=10)).isoformat()
        _write_idx(tmp_path, "alpha", "open", long_ago)
        result = _run(tmp_path, window="24")
        assert result["output"]["stale_open_threads_count"] >= 1

    def test_does_not_flag_recent_thread(self, tmp_path: Path):
        recent = datetime.now(timezone.utc).astimezone().isoformat()
        _write_idx(tmp_path, "beta", "open", recent)
        result = _run(tmp_path, window="24")
        assert result["output"]["stale_open_threads_count"] == 0

    def test_recovers_un_indexed_file(self, tmp_path: Path):
        now_iso = datetime.now(timezone.utc).astimezone().isoformat()
        _write_idx(tmp_path, "gamma", "open", now_iso)

        thread_dir = tmp_path / "discussions" / "enclaws" / "gamma"
        unindexed = thread_dir / "002_shengli_reply_y.md"
        unindexed.write_text(
            "---\ntype: reply\nauthor: shengli\nsummary: r\nindex_state: un-indexed\n---\n# reply body\n",
            encoding="utf-8",
        )

        result = _run(tmp_path)
        assert result["output"]["un_indexed_recovered_count"] == 1

        content = unindexed.read_text(encoding="utf-8")
        assert "index_state: indexed" in content
        assert "un-indexed" not in content

    def test_flags_un_replied_mention(self, tmp_path: Path):
        long_ago = (datetime.now(timezone.utc).astimezone() - timedelta(hours=72)).isoformat()
        recent = datetime.now(timezone.utc).astimezone().isoformat()
        _write_idx(
            tmp_path,
            "delta",
            "open",
            recent,
            timeline_entries=[
                {
                    "time": long_ago,
                    "event": "ken 发起并 @ shengli",
                    "mention": [{"user": "shengli", "comments": "please review"}],
                }
            ],
        )
        result = _run(tmp_path, mention_window="48")
        flagged = result["output"]["un_replied_mentions"]
        assert len(flagged) >= 1
        assert flagged[0]["mentioned_user"] == "shengli"


class TestScanNotification:
    def test_scan_succeeds_without_bot_config(self, tmp_path: Path):
        long_ago = (datetime.now(timezone.utc).astimezone() - timedelta(days=10)).isoformat()
        _write_idx(tmp_path, "no-bot", "open", long_ago)

        env = {
            **os.environ,
            "ENCLAWS_TENANT_ID": "t",
            "ENCLAWS_TENANT_USER_ID": "monitor",
            "PIVOT_DATA_SPACE_DIR": str(tmp_path),
            "PIVOT_APP_NAME": "pivot",
        }
        env.pop("FEISHU_APP_ID", None)
        env.pop("FEISHU_APP_SECRET", None)
        proc = subprocess.run(
            [sys.executable, str(STEP)],
            input=json.dumps(
                {
                    "input": {"window_hours": "24", "mention_window_hours": "48"},
                    "steps": {},
                }
            ),
            capture_output=True,
            text=True,
            env=env,
        )
        assert proc.returncode == 0, proc.stderr
        result = json.loads(proc.stdout)
        assert result["output"]["stale_open_threads_count"] >= 1
        assert result["output"]["notifications_sent"] == 0
