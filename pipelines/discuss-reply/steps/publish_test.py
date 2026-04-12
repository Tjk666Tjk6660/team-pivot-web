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

        draft_dir = tmp_git_repo / "discussions" / category / thread / "members" / "shengli"
        draft_dir.mkdir(parents=True)
        draft = draft_dir / "draft_reply.md"
        draft.write_text(
            "---\ntype: reply\nauthor: shengli\nsummary: my reply\n---\n# reply body\n",
            encoding="utf-8",
        )

        env = {
            **os.environ,
            "PIVOT_TENANT_ID": "t",
            "PIVOT_USER_ID": "shengli",
            "PIVOT_WORKSPACE_DIR": str(tmp_git_repo),
            "PIVOT_APP_NAME": "pivot",
        }
        proc = subprocess.run(
            [sys.executable, str(STEP)],
            input=json.dumps(
                {
                    "input": {
                        "category": category,
                        "thread": thread,
                        "draft_path": str(draft),
                        "mention_users": "ken",
                        "mention_comments": "please review",
                    },
                    "steps": {
                        "prepare": {
                            "output": {
                                "category": category,
                                "thread": thread,
                                "draft_path": str(draft),
                                "author": "shengli",
                                "mention_users": "ken",
                                "mention_comments": "please review",
                            }
                        }
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
    def test_reply_sends_notification_when_webhook_set(
        self, tmp_git_repo: Path, mock_feishu_server
    ):
        category = "enclaws"
        thread = "reply-notify-test"
        _seed_thread(tmp_git_repo, category, thread, "ken")

        draft_dir = tmp_git_repo / "discussions" / category / thread / "members" / "shengli"
        draft_dir.mkdir(parents=True)
        draft = draft_dir / "draft_reply.md"
        draft.write_text(
            "---\ntype: reply\nauthor: shengli\nsummary: replying\n---\n# body\n",
            encoding="utf-8",
        )

        env = {
            **os.environ,
            "PIVOT_TENANT_ID": "t",
            "PIVOT_USER_ID": "shengli",
            "PIVOT_WORKSPACE_DIR": str(tmp_git_repo),
            "PIVOT_APP_NAME": "pivot",
            "FEISHU_WEBHOOK_URL": mock_feishu_server["url"],
            "FEISHU_SECRET": "",
            "PIVOT_USER_MAP": '{"ken": {"feishu_id": "ou_ken"}}',
        }
        proc = subprocess.run(
            [sys.executable, str(STEP)],
            input=json.dumps(
                {
                    "input": {
                        "category": category,
                        "thread": thread,
                        "draft_path": str(draft),
                        "mention_users": "ken",
                        "mention_comments": "pls review",
                    },
                    "steps": {
                        "prepare": {
                            "output": {
                                "category": category,
                                "thread": thread,
                                "draft_path": str(draft),
                                "author": "shengli",
                                "mention_users": "ken",
                                "mention_comments": "pls review",
                            }
                        }
                    },
                }
            ),
            capture_output=True,
            text=True,
            env=env,
        )
        assert proc.returncode == 0, proc.stderr

        assert len(mock_feishu_server["received"]) == 1
        body = mock_feishu_server["received"][0]
        content = body["card"]["elements"][0]["text"]["content"]
        assert '<at id="ou_ken"></at>' in content
        assert "回复" in body["card"]["header"]["title"]["content"]

    def test_reply_succeeds_when_webhook_unreachable(self, tmp_git_repo: Path):
        category = "enclaws"
        thread = "reply-unreach"
        _seed_thread(tmp_git_repo, category, thread, "ken")

        draft_dir = tmp_git_repo / "discussions" / category / thread / "members" / "shengli"
        draft_dir.mkdir(parents=True)
        draft = draft_dir / "draft_reply.md"
        draft.write_text(
            "---\ntype: reply\nauthor: shengli\nsummary: replying\n---\n# body\n",
            encoding="utf-8",
        )

        env = {
            **os.environ,
            "PIVOT_TENANT_ID": "t",
            "PIVOT_USER_ID": "shengli",
            "PIVOT_WORKSPACE_DIR": str(tmp_git_repo),
            "PIVOT_APP_NAME": "pivot",
            "FEISHU_WEBHOOK_URL": "http://127.0.0.1:1",
            "FEISHU_SECRET": "",
        }
        proc = subprocess.run(
            [sys.executable, str(STEP)],
            input=json.dumps(
                {
                    "input": {
                        "category": category,
                        "thread": thread,
                        "draft_path": str(draft),
                        "mention_users": "",
                        "mention_comments": "",
                    },
                    "steps": {
                        "prepare": {
                            "output": {
                                "category": category,
                                "thread": thread,
                                "draft_path": str(draft),
                                "author": "shengli",
                                "mention_users": "",
                                "mention_comments": "",
                            }
                        }
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
