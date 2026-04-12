"""Tests for discuss-new prepare step."""
import json
import os
import subprocess
import sys
from pathlib import Path


STEP = Path(__file__).parent / "prepare.py"


def run_step(input_obj: dict, env: dict) -> dict:
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


def _base_env(tmp_path: Path) -> dict:
    return {
        **os.environ,
        "PIVOT_TENANT_ID": "t",
        "PIVOT_USER_ID": "u",
        "PIVOT_WORKSPACE_DIR": str(tmp_path),
        "PIVOT_APP_NAME": "pivot",
    }


class TestPrepareStep:
    def test_reads_draft_and_returns_content(self, tmp_path: Path):
        draft = tmp_path / "draft.md"
        draft.write_text(
            "---\nsummary: \"**摘要**：existing\"\n---\n# test\nbody\n",
            encoding="utf-8",
        )
        result = run_step(
            {
                "category": "enclaws",
                "title": "test thread",
                "draft_path": str(draft),
                "mention_users": "",
                "mention_comments": "",
            },
            _base_env(tmp_path),
        )
        assert "output" in result
        assert result["output"]["has_summary"] is True
        assert result["output"]["title"] == "test thread"
        assert "# test" in result["output"]["content"]

    def test_returns_has_summary_false_when_draft_lacks_summary(self, tmp_path: Path):
        draft = tmp_path / "draft.md"
        draft.write_text("# no frontmatter\nbody\n", encoding="utf-8")
        result = run_step(
            {
                "category": "enclaws",
                "title": "x",
                "draft_path": str(draft),
                "mention_users": "",
                "mention_comments": "",
            },
            _base_env(tmp_path),
        )
        assert result["output"]["has_summary"] is False
