"""Tests for discuss-new prepare step."""
import json
import os
import subprocess
import sys
from pathlib import Path


STEP = Path(__file__).parent / "prepare.py"


def _base_env(tmp_path: Path, user_workspace: Path) -> dict:
    return {
        **os.environ,
        "ENCLAWS_TENANT_ID": "t",
        "ENCLAWS_TENANT_USER_ID": "u",
        "ENCLAWS_USER_WORKSPACE": str(user_workspace),
        "PIVOT_DATA_SPACE_DIR": str(tmp_path),
        "PIVOT_APP_NAME": "pivot",
    }


def _run(input_obj: dict, env: dict) -> dict:
    proc = subprocess.run(
        [sys.executable, str(STEP)],
        input=json.dumps({"input": input_obj, "steps": {}}),
        capture_output=True,
        text=True,
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"step failed: {proc.stderr}")
    return json.loads(proc.stdout)


class TestPrepareStep:
    def test_passes_content_through(self, tmp_path: Path, user_workspace: Path, make_proposal_draft):
        draft_id = make_proposal_draft(
            title="test thread", content="# My Proposal\n\nThis is the body.",
        )
        result = _run(
            {
                "draft_id": draft_id,
                "category": "enclaws",
                "mention_users": "ken",
                "mention_comments": "",
            },
            _base_env(tmp_path, user_workspace),
        )
        assert result["output"]["category"] == "enclaws"
        assert result["output"]["title"] == "test thread"
        assert "# My Proposal" in result["output"]["content"]
        assert result["output"]["has_summary"] is False
        assert result["output"]["mention_users"] == "ken"

    def test_fails_without_draft_id(self, tmp_path: Path, user_workspace: Path):
        proc = subprocess.run(
            [sys.executable, str(STEP)],
            input=json.dumps({"input": {"category": "a"}, "steps": {}}),
            capture_output=True,
            text=True,
            env=_base_env(tmp_path, user_workspace),
        )
        assert proc.returncode != 0
        assert "draft_id" in proc.stderr.lower()

    def test_fails_on_wrong_draft_type(self, tmp_path: Path, user_workspace: Path, make_reply_draft):
        # A reply draft must not be usable by discuss-new.
        draft_id = make_reply_draft(thread="some-thread", content="reply body")
        proc = subprocess.run(
            [sys.executable, str(STEP)],
            input=json.dumps({"input": {"draft_id": draft_id, "category": "a"}, "steps": {}}),
            capture_output=True,
            text=True,
            env=_base_env(tmp_path, user_workspace),
        )
        assert proc.returncode != 0
        assert "proposal" in proc.stderr.lower()

    def test_category_defaults_to_general(self, tmp_path: Path, user_workspace: Path, make_proposal_draft):
        draft_id = make_proposal_draft(title="t", content="body")
        result = _run(
            {"draft_id": draft_id},
            _base_env(tmp_path, user_workspace),
        )
        assert result["output"]["category"] == "general"
