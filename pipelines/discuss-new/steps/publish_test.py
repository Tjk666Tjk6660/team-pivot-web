"""Tests for publish step: move draft to canonical path, update INDEX, commit, notify."""
import json
import os
import subprocess
import sys
from pathlib import Path


STEP = Path(__file__).parent / "publish.py"


class TestPublish:
    def test_publish_moves_draft_to_thread_dir_and_updates_index(
        self, tmp_git_repo: Path
    ):
        draft_dir = tmp_git_repo / "discussions" / "enclaws" / "test-thread" / "members" / "huangshengli"
        draft_dir.mkdir(parents=True)
        draft = draft_dir / "draft_proposal.md"
        draft.write_text(
            "---\ntype: proposal\nauthor: huangshengli\nsummary: \"**摘要**：test\"\n---\n# test body\n",
            encoding="utf-8",
        )

        env = {
            **os.environ,
            "PIVOT_TENANT_ID": "t",
            "PIVOT_USER_ID": "huangshengli",
            "PIVOT_WORKSPACE_DIR": str(tmp_git_repo),
            "PIVOT_APP_NAME": "pivot",
        }
        proc = subprocess.run(
            [sys.executable, str(STEP)],
            input=json.dumps(
                {
                    "input": {
                        "category": "enclaws",
                        "title": "test-thread",
                        "draft_path": str(draft),
                        "mention_users": "",
                        "mention_comments": "",
                    },
                    "steps": {
                        "prepare": {
                            "output": {
                                "draft_path": str(draft),
                                "category": "enclaws",
                                "title": "test-thread",
                                "author": "huangshengli",
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

        thread_dir = tmp_git_repo / "discussions" / "enclaws" / "test-thread"
        canonical_files = list(thread_dir.glob("001_*.md"))
        assert len(canonical_files) == 1

        index_file = tmp_git_repo / "index" / "test-thread-discuss.index.yaml"
        assert index_file.exists()

        assert result["output"]["committed"] is True
        assert result["output"]["index_file"] is not None


class TestPublishNotification:
    def test_publish_sends_notification_when_webhook_set(
        self, tmp_git_repo: Path, mock_feishu_server
    ):
        draft_dir = tmp_git_repo / "discussions" / "enclaws" / "notify-test" / "members" / "huangshengli"
        draft_dir.mkdir(parents=True)
        draft = draft_dir / "draft_proposal.md"
        draft.write_text(
            "---\ntype: proposal\nauthor: huangshengli\nsummary: \"**摘要**：testing notification flow\"\n---\n# body\n",
            encoding="utf-8",
        )
        env = {
            **os.environ,
            "PIVOT_TENANT_ID": "t",
            "PIVOT_USER_ID": "huangshengli",
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
                        "category": "enclaws",
                        "title": "notify-test",
                        "draft_path": str(draft),
                        "mention_users": "ken",
                        "mention_comments": "",
                    },
                    "steps": {
                        "prepare": {
                            "output": {
                                "draft_path": str(draft),
                                "category": "enclaws",
                                "title": "notify-test",
                                "author": "huangshengli",
                                "mention_users": "ken",
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

        assert len(mock_feishu_server["received"]) == 1
        body = mock_feishu_server["received"][0]
        assert body["msg_type"] == "interactive"
        content = body["card"]["elements"][0]["text"]["content"]
        assert '<at id="ou_ken"></at>' in content
        assert "New thread" in body["card"]["header"]["title"]["content"]

    def test_publish_succeeds_when_webhook_unreachable(self, tmp_git_repo: Path):
        draft_dir = tmp_git_repo / "discussions" / "enclaws" / "x" / "members" / "u"
        draft_dir.mkdir(parents=True)
        draft = draft_dir / "draft_proposal.md"
        draft.write_text(
            "---\ntype: proposal\nauthor: u\nsummary: test\n---\n# body\n",
            encoding="utf-8",
        )
        env = {
            **os.environ,
            "PIVOT_TENANT_ID": "t",
            "PIVOT_USER_ID": "u",
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
                        "category": "enclaws",
                        "title": "x",
                        "draft_path": str(draft),
                        "mention_users": "",
                        "mention_comments": "",
                    },
                    "steps": {
                        "prepare": {
                            "output": {
                                "draft_path": str(draft),
                                "category": "enclaws",
                                "title": "x",
                                "author": "u",
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
