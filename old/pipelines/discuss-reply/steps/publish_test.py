"""Tests for discuss-reply publish step."""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


STEP = Path(__file__).parent / "publish.py"


def _seed_thread(tmp_git_repo: Path, category: str, thread: str, author: str):
    """Create an existing thread with 001 proposal and a matching INDEX so reply can append."""
    thread_dir = tmp_git_repo / "discussions" / category / thread
    thread_dir.mkdir(parents=True)
    (thread_dir / "001_ken_proposal_aaaaaa.md").write_text(
        "---\ntype: proposal\nauthor: ken\nsummary: seed\nindex_state: indexed\n---\n# proposal\n",
        encoding="utf-8",
    )
    index_dir = tmp_git_repo / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).astimezone().isoformat()
    idx_content = (
        f"origin_path: discussions/{category}/{thread}/\n"
        f"created: {now}\n"
        f"last_updated: {now}\n"
        f"discussions:\n"
        f"  - path: discussions/{category}/{thread}/\n"
        f"    status: open\n"
        f"    files:\n"
        f"      - path: 001_ken_proposal_aaaaaa.md\n"
        f"        summary: seed\n"
        f"        refs: []\n"
        f"timeline: []\n"
    )
    (index_dir / f"{thread}-discuss.index.yaml").write_text(idx_content, encoding="utf-8")


class TestReplyPublish:
    def test_reply_appends_to_existing_thread(self, tmp_git_repo: Path):
        category = "enclaws"
        thread = "auth-redesign"
        _seed_thread(tmp_git_repo, category, thread, "ken")

        env = {
            **os.environ,
            "ENCLAWS_TENANT_ID": "t",
            "ENCLAWS_TENANT_USER_ID": "shengli",
            "PIVOT_DATA_SPACE_DIR": str(tmp_git_repo),
            "PIVOT_APP_NAME": "pivot",
        }
        proc = subprocess.run(
            [sys.executable, str(STEP)],
            input=json.dumps(
                {
                    "input": {
                        "category": category,
                        "thread": thread,
                        "content": "# My reply\n\nI agree with the proposal.",
                        "mention_users": "ken",
                        "mention_comments": "please review",
                    },
                    "steps": {
                        "prepare": {
                            "output": {
                                "category": category,
                                "thread": thread,
                                "content": "# My reply\n\nI agree with the proposal.",
                                "author": "shengli",
                                "mention_users": "ken",
                                "mention_comments": "please review",
                            }
                        },
                        "generate_summary": {
                            "output": {"summary": "Reply agreeing with proposal"}
                        },
                    },
                }
            ),
            capture_output=True,
            text=True,
            env=env,
        )
        assert proc.returncode == 0, proc.stderr
        result = json.loads(proc.stdout)
        assert result["output"]["committed"] is True
        assert result["output"]["post_number"] == 2

        thread_dir = tmp_git_repo / "discussions" / category / thread
        files = sorted(f.name for f in thread_dir.glob("002_*.md"))
        assert len(files) == 1
        assert files[0].startswith("002_shengli_reply_")


class TestReplyPublishNotification:
    def test_reply_succeeds_without_bot_config(self, tmp_git_repo: Path):
        category = "enclaws"
        thread = "reply-no-bot"
        _seed_thread(tmp_git_repo, category, thread, "ken")

        env = {
            **os.environ,
            "ENCLAWS_TENANT_ID": "t",
            "ENCLAWS_TENANT_USER_ID": "shengli",
            "PIVOT_DATA_SPACE_DIR": str(tmp_git_repo),
            "PIVOT_APP_NAME": "pivot",
        }
        env.pop("FEISHU_APP_ID", None)
        env.pop("FEISHU_APP_SECRET", None)
        proc = subprocess.run(
            [sys.executable, str(STEP)],
            input=json.dumps(
                {
                    "input": {
                        "category": category,
                        "thread": thread,
                        "content": "# reply",
                        "mention_users": "",
                        "mention_comments": "",
                    },
                    "steps": {
                        "prepare": {
                            "output": {
                                "category": category,
                                "thread": thread,
                                "content": "# reply",
                                "author": "shengli",
                                "mention_users": "",
                                "mention_comments": "",
                            }
                        },
                        "generate_summary": {
                            "output": {"summary": "Reply summary"}
                        },
                    },
                }
            ),
            capture_output=True,
            text=True,
            env=env,
        )
        assert proc.returncode == 0, proc.stderr
        result = json.loads(proc.stdout)
        assert result["output"]["committed"] is True
