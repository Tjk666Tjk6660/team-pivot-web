"""Tests for discuss-new write_summary step."""
import json
import os
import subprocess
import sys
from pathlib import Path


STEP = Path(__file__).parent / "write_summary.py"


def run_step(input_obj: dict, steps: dict, env: dict) -> dict:
    proc = subprocess.run(
        [sys.executable, str(STEP)],
        input=json.dumps({"input": input_obj, "steps": steps}),
        capture_output=True,
        text=True,
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr)
    return json.loads(proc.stdout)


def _base_env(tmp_path: Path) -> dict:
    return {
        **os.environ,
        "PIVOT_TENANT_ID": "t",
        "PIVOT_USER_ID": "u",
        "PIVOT_WORKSPACE_DIR": str(tmp_path),
        "PIVOT_APP_NAME": "pivot",
    }


class TestWriteSummary:
    def test_writes_summary_to_draft_frontmatter(self, tmp_path: Path):
        draft = tmp_path / "draft.md"
        draft.write_text("# content\nbody text\n", encoding="utf-8")
        result = run_step(
            {
                "category": "enclaws",
                "title": "x",
                "draft_path": str(draft),
                "mention_users": "",
                "mention_comments": "",
            },
            {
                "prepare": {"output": {"draft_path": str(draft), "content": "body text"}},
                "generate_summary": {"output": {"summary": "**摘要**：x\n**亮点**：y"}},
            },
            _base_env(tmp_path),
        )
        assert result["output"]["written"] is True
        new_content = draft.read_text(encoding="utf-8")
        assert "**摘要**：x" in new_content
