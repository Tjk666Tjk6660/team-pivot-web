"""Tests for publish step: create canonical file, update INDEX, commit, notify."""
import json
import os
import subprocess
import sys
from pathlib import Path


STEP = Path(__file__).parent / "publish.py"


class TestPublish:
    def test_publish_creates_file_and_updates_index(self, tmp_git_repo: Path):
        env = {
            **os.environ,
            "ENCLAWS_TENANT_ID": "t",
            "ENCLAWS_TENANT_USER_ID": "huangshengli",
            "PIVOT_DATA_SPACE_DIR": str(tmp_git_repo),
            "PIVOT_APP_NAME": "pivot",
        }
        proc = subprocess.run(
            [sys.executable, str(STEP)],
            input=json.dumps(
                {
                    "input": {
                        "category": "enclaws",
                        "title": "test-thread",
                        "content": "# My Proposal\n\nBody text here.",
                        "mention_users": "",
                        "mention_comments": "",
                    },
                    "steps": {
                        "prepare": {
                            "output": {
                                "category": "enclaws",
                                "title": "test-thread",
                                "content": "# My Proposal\n\nBody text here.",
                                "author": "huangshengli",
                                "mention_users": "",
                                "mention_comments": "",
                            }
                        },
                        "generate_summary": {
                            "output": {"summary": "Proposal summary"}
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

        thread_dir = tmp_git_repo / "discussions" / "enclaws" / "test-thread"
        canonical_files = list(thread_dir.glob("001_*.md"))
        assert len(canonical_files) == 1

        index_file = tmp_git_repo / "index" / "test-thread-discuss.index.yaml"
        assert index_file.exists()

        assert result["output"]["committed"] is True
        assert result["output"]["index_file"] is not None


class TestPublishNotification:
    def test_publish_sends_notification_via_bot(
        self, tmp_git_repo: Path, mock_feishu_server
    ):
        env = {
            **os.environ,
            "ENCLAWS_TENANT_ID": "t",
            "ENCLAWS_TENANT_USER_ID": "huangshengli",
            "PIVOT_DATA_SPACE_DIR": str(tmp_git_repo),
            "PIVOT_APP_NAME": "pivot",
            "FEISHU_TENANT_ACCESS_TOKEN": "t-test",
            "PIVOT_USER_MAP": '{"ken": {"feishu_id": "ou_ken"}}',
        }
        proc = subprocess.run(
            [sys.executable, str(STEP)],
            input=json.dumps(
                {
                    "input": {
                        "category": "enclaws",
                        "title": "notify-test",
                        "content": "# Proposal body\n\nDetails here.",
                        "mention_users": "ken",
                        "mention_comments": "",
                    },
                    "steps": {
                        "prepare": {
                            "output": {
                                "category": "enclaws",
                                "title": "notify-test",
                                "content": "# Proposal body\n\nDetails here.",
                                "author": "huangshengli",
                                "mention_users": "ken",
                                "mention_comments": "",
                            }
                        },
                        "generate_summary": {
                            "output": {"summary": "Test notification summary"}
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

    def test_publish_succeeds_without_bot_config(self, tmp_git_repo: Path):
        env = {
            **os.environ,
            "ENCLAWS_TENANT_ID": "t",
            "ENCLAWS_TENANT_USER_ID": "u",
            "PIVOT_DATA_SPACE_DIR": str(tmp_git_repo),
            "PIVOT_APP_NAME": "pivot",
        }
        env.pop("FEISHU_TENANT_ACCESS_TOKEN", None)
        proc = subprocess.run(
            [sys.executable, str(STEP)],
            input=json.dumps(
                {
                    "input": {
                        "category": "enclaws",
                        "title": "x",
                        "content": "# body",
                        "mention_users": "",
                        "mention_comments": "",
                    },
                    "steps": {
                        "prepare": {
                            "output": {
                                "category": "enclaws",
                                "title": "x",
                                "content": "# body",
                                "author": "u",
                                "mention_users": "",
                                "mention_comments": "",
                            }
                        },
                        "generate_summary": {
                            "output": {"summary": "Summary"}
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
