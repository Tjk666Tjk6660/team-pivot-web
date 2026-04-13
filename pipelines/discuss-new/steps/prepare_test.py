"""Tests for discuss-new prepare step."""
import json
import os
import subprocess
import sys
from pathlib import Path


STEP = Path(__file__).parent / "prepare.py"


def _base_env(tmp_path: Path) -> dict:
    return {
        **os.environ,
        "PIVOT_TENANT_ID": "t",
        "PIVOT_USER_ID": "u",
        "PIVOT_WORKSPACE_DIR": str(tmp_path),
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
    def test_passes_content_through(self, tmp_path: Path):
        result = _run(
            {
                "category": "enclaws",
                "title": "test thread",
                "content": "# My Proposal\n\nThis is the body.",
                "mention_users": "ken",
                "mention_comments": "",
            },
            _base_env(tmp_path),
        )
        assert result["output"]["category"] == "enclaws"
        assert result["output"]["title"] == "test thread"
        assert "# My Proposal" in result["output"]["content"]
        assert result["output"]["has_summary"] is False
        assert result["output"]["mention_users"] == "ken"

    def test_fails_without_content(self, tmp_path: Path):
        proc = subprocess.run(
            [sys.executable, str(STEP)],
            input=json.dumps({"input": {"category": "a", "title": "b"}, "steps": {}}),
            capture_output=True,
            text=True,
            env=_base_env(tmp_path),
        )
        assert proc.returncode != 0
        assert "content" in proc.stderr.lower()

    def test_fails_without_category(self, tmp_path: Path):
        proc = subprocess.run(
            [sys.executable, str(STEP)],
            input=json.dumps({"input": {"title": "b", "content": "x"}, "steps": {}}),
            capture_output=True,
            text=True,
            env=_base_env(tmp_path),
        )
        assert proc.returncode != 0
        assert "category" in proc.stderr.lower()
