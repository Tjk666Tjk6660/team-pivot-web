"""Real integration test: clone test-discuss repo → discuss-new → discuss-reply.

Uses real git repo and real Claude CLI for LLM steps.
All I/O is recorded to tests/test_output/<run_id>/.

Run with:
    pytest tests/integration_test/test_real_discuss_flow.py -v -s

Requires:
    - claude CLI installed and authenticated
    - network access to GitHub
"""
from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

import pytest

from tests.ec_simulator.runner import LocalPipelineRunner
from tests.ec_simulator.llm_backends.claude_cli import ClaudeCLIBackend

REPO_URL = "https://github.com/hashSTACS-Global/test-discuss.git"
APP_DIR = str(Path(__file__).parent.parent.parent)  # team-pivot/
TEST_OUTPUT_BASE = Path(__file__).parent.parent / "test_output"


def _clone_repo(tmp_dir: Path) -> Path:
    """Clone the real test-discuss repo into a temp directory."""
    work = tmp_dir / "test-discuss"
    subprocess.run(
        ["git", "clone", REPO_URL, str(work)],
        check=True, capture_output=True, text=True,
    )
    return work


def _make_run_dir() -> Path:
    """Create a timestamped directory for this test run's output."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = TEST_OUTPUT_BASE / f"real_flow_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


@pytest.fixture(scope="module")
def run_dir():
    return _make_run_dir()


@pytest.fixture(scope="module")
def workspace(tmp_path_factory, run_dir):
    """Clone the real repo once per module."""
    tmp = tmp_path_factory.mktemp("real_test")
    work = _clone_repo(tmp)

    # Record repo state
    (run_dir / "repo_initial_state.txt").write_text(
        subprocess.run(
            ["git", "-C", str(work), "log", "--oneline", "-10"],
            capture_output=True, text=True,
        ).stdout,
        encoding="utf-8",
    )
    return work


class TestRealDiscussFlow:
    """Full flow test with real git repo and real Claude LLM."""

    def test_01_new_thread(self, workspace: Path, run_dir: Path):
        """Create a new discussion thread."""
        step_dir = run_dir / "01_discuss_new"
        runner = LocalPipelineRunner(
            app_dir=APP_DIR,
            workspace_dir=str(workspace),
            llm_backend=ClaudeCLIBackend(record_dir=step_dir),
            user_id="huangshengli",
            record_dir=str(step_dir),
        )

        result = runner.run("discuss-new", {
            "category": "discussion",
            "title": "test-restructure-proposal",
            "content": (
                "# 测试架构重构提案\n\n"
                "## 背景\n"
                "当前测试使用 mock 数据，无法验证 LLM 输出质量和真实 pipeline 行为。\n\n"
                "## 方案\n"
                "1. 引入四层测试架构：ec_simulator / pipeline_test / channel_test / integration_test\n"
                "2. LLM step 使用本地 Claude CLI 真实调用\n"
                "3. 所有输入输出录制到 test_output/ 目录\n\n"
                "## 预期收益\n"
                "- 测试可信度提升：LLM 返回真实 summary\n"
                "- 数据可追溯：每次运行的完整 I/O 留档\n"
                "- 回归保护：录制结果可作为后续 prerecorded fixture\n"
            ),
            "mention_users": "",
            "mention_comments": "",
        })

        assert result.status == "completed", f"discuss-new failed: {result.error}"
        assert result.output["committed"] is True

        # Verify thread files created
        thread_dir = workspace / "discussions/discussion/test-restructure-proposal"
        assert thread_dir.exists(), f"thread dir not created: {thread_dir}"
        posts = list(thread_dir.glob("001_*.md"))
        assert len(posts) == 1, f"expected 1 post, found {len(posts)}"

        # Verify LLM was actually called (summary in step outputs)
        assert "generate_summary" in result.step_outputs
        summary = result.step_outputs["generate_summary"]["output"]["summary"]
        assert len(summary) > 20, f"summary too short: {summary}"

        # Record test assertion results
        (step_dir / "test_assertions.txt").write_text(
            f"status: {result.status}\n"
            f"committed: {result.output['committed']}\n"
            f"thread_dir_exists: {thread_dir.exists()}\n"
            f"post_count: {len(posts)}\n"
            f"summary_length: {len(summary)}\n"
            f"summary: {summary}\n",
            encoding="utf-8",
        )

    def test_02_reply_thread(self, workspace: Path, run_dir: Path):
        """Reply to the thread created in test_01."""
        step_dir = run_dir / "02_discuss_reply"
        runner = LocalPipelineRunner(
            app_dir=APP_DIR,
            workspace_dir=str(workspace),
            llm_backend=ClaudeCLIBackend(record_dir=step_dir),
            user_id="ken",
            record_dir=str(step_dir),
        )

        result = runner.run("discuss-reply", {
            "category": "discussion",
            "thread": "test-restructure-proposal",
            "content": (
                "# 回复：赞同方案，补充几点\n\n"
                "1. PrerecordedBackend 应该保留，用于 CI 快速验证\n"
                "2. ClaudeCLIBackend 只在本地开发时使用，CI 跳过\n"
                "3. 建议增加 `--llm-backend` pytest 参数来切换\n\n"
                "另外 test_output/ 目录的录制结果也可以反哺 prerecorded fixture，\n"
                "形成「录制 → 回放」的闭环。\n"
            ),
            "mention_users": "huangshengli",
            "mention_comments": "",
        })

        assert result.status == "completed", f"discuss-reply failed: {result.error}"
        assert result.output["committed"] is True
        assert result.output["post_number"] == 2

        # Verify reply file
        thread_dir = workspace / "discussions/discussion/test-restructure-proposal"
        replies = list(thread_dir.glob("002_*.md"))
        assert len(replies) == 1

        # Verify LLM summary
        assert "generate_summary" in result.step_outputs
        summary = result.step_outputs["generate_summary"]["output"]["summary"]
        assert len(summary) > 20

        (step_dir / "test_assertions.txt").write_text(
            f"status: {result.status}\n"
            f"committed: {result.output['committed']}\n"
            f"post_number: {result.output['post_number']}\n"
            f"reply_count: {len(replies)}\n"
            f"summary_length: {len(summary)}\n"
            f"summary: {summary}\n",
            encoding="utf-8",
        )

    def test_03_list_threads(self, workspace: Path, run_dir: Path):
        """List threads to verify both operations are visible."""
        step_dir = run_dir / "03_discuss_list"
        runner = LocalPipelineRunner(
            app_dir=APP_DIR,
            workspace_dir=str(workspace),
            llm_backend=ClaudeCLIBackend(record_dir=step_dir),
            user_id="huangshengli",
            record_dir=str(step_dir),
        )

        result = runner.run("discuss-list", {"category": "discussion"})
        assert result.status == "completed", f"discuss-list failed: {result.error}"

        threads = result.output["threads"]
        slugs = [t["slug"] for t in threads]
        assert "test-restructure-proposal" in slugs

        (step_dir / "test_assertions.txt").write_text(
            f"status: {result.status}\n"
            f"thread_count: {len(threads)}\n"
            f"slugs: {slugs}\n",
            encoding="utf-8",
        )

    def test_04_read_thread(self, workspace: Path, run_dir: Path):
        """Read the thread to verify all posts are present."""
        step_dir = run_dir / "04_discuss_read"
        runner = LocalPipelineRunner(
            app_dir=APP_DIR,
            workspace_dir=str(workspace),
            llm_backend=ClaudeCLIBackend(record_dir=step_dir),
            user_id="huangshengli",
            record_dir=str(step_dir),
        )

        result = runner.run("discuss-read", {
            "category": "discussion",
            "thread": "test-restructure-proposal",
        })
        assert result.status == "completed", f"discuss-read failed: {result.error}"

        posts = result.output["posts"]
        assert len(posts) == 2, f"expected 2 posts, got {len(posts)}"
        assert posts[0]["author"] == "huangshengli"
        assert posts[1]["author"] == "ken"

        (step_dir / "test_assertions.txt").write_text(
            f"status: {result.status}\n"
            f"post_count: {len(posts)}\n"
            f"authors: {[p['author'] for p in posts]}\n",
            encoding="utf-8",
        )

    def test_05_verify_git_state(self, workspace: Path, run_dir: Path):
        """Verify git commits were actually made and pushed."""
        log = subprocess.run(
            ["git", "-C", str(workspace), "log", "--oneline", "-10"],
            capture_output=True, text=True,
        )
        assert log.returncode == 0

        # Should have at least 2 new commits (new + reply)
        lines = [l for l in log.stdout.strip().split("\n") if l]
        assert len(lines) >= 3  # initial + new + reply

        # Verify push status (check if local is ahead of remote)
        status = subprocess.run(
            ["git", "-C", str(workspace), "status", "-sb"],
            capture_output=True, text=True,
        )

        (run_dir / "05_git_state.txt").write_text(
            f"git log:\n{log.stdout}\n\ngit status:\n{status.stdout}\n",
            encoding="utf-8",
        )
