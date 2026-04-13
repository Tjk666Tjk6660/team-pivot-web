"""Shared fixtures for pipeline tests."""
from pathlib import Path

import pytest

from tests.ec_simulator.runner import LocalPipelineRunner
from tests.ec_simulator.llm_backends.prerecorded import PrerecordedBackend


APP_DIR = str(Path(__file__).parent.parent.parent)

LLM_RESPONSES = {
    "generate_summary": {
        "output": {"summary": "Overview: Test content. Highlights: 1) Point A; 2) Point B."}
    },
    "generate_result": {
        "output": {
            "result_body": (
                "# Result\n\n## Background\nTest.\n\n## Options\n1. A\n2. B\n\n"
                "## Decision\nA selected.\n\n## Action Items\n- [ ] Implement"
            )
        }
    },
}


@pytest.fixture
def runner(tmp_git_repo: Path) -> LocalPipelineRunner:
    return LocalPipelineRunner(
        app_dir=APP_DIR,
        workspace_dir=str(tmp_git_repo),
        llm_backend=PrerecordedBackend.from_dict(LLM_RESPONSES),
    )
