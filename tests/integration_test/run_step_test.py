"""One-shot orchestrator for step_runner integration test.

This script automates the full discuss-new + discuss-reply flow,
pausing at LLM steps to read/write exchange files.

Usage (by Claude Code):
    1. python run_step_test.py setup          → clone repo, create output dir
    2. python run_step_test.py run-new        → run discuss-new until LLM needed
    3. (Claude Code writes LLM response to exchange file)
    4. python run_step_test.py resume-new     → inject response, finish discuss-new
    5. python run_step_test.py run-reply      → run discuss-reply until LLM needed
    6. (Claude Code writes LLM response to exchange file)
    7. python run_step_test.py resume-reply   → inject response, finish discuss-reply
    8. python run_step_test.py verify         → verify all artifacts

Usage (by human, fully manual):
    python run_step_test.py manual            → interactive mode, prompts for LLM input
"""
from __future__ import annotations

import json
import subprocess
import sys
import shutil
from datetime import datetime
from pathlib import Path

REPO_URL = "https://github.com/hashSTACS-Global/test-discuss.git"
BASE_DIR = Path(__file__).parent.parent.parent  # team-pivot/
TEST_OUTPUT = Path(__file__).parent.parent / "test_output"
STEP_RUNNER = str(Path(__file__).parent / "step_runner.py")
PYTHON = sys.executable


def _ts():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _run_step(args: list[str]) -> dict:
    """Run step_runner.py with given args, return parsed JSON output."""
    cmd = [PYTHON, STEP_RUNNER] + args
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=str(BASE_DIR))
    if proc.returncode != 0:
        return {"error": proc.stderr.strip(), "stdout": proc.stdout.strip()}
    try:
        return json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        return {"raw": proc.stdout.strip()}


def _print_json(data: dict):
    print(json.dumps(data, ensure_ascii=False, indent=2))


class StepTestSession:
    """Manages a single test session's state."""

    def __init__(self, session_dir: Path | None = None):
        if session_dir:
            self.session_dir = session_dir
        else:
            self.session_dir = TEST_OUTPUT / f"step_test_{_ts()}"
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.workspace = self.session_dir / "workspace"
        self.new_ctx = str(self.session_dir / "new_ctx.json")
        self.reply_ctx = str(self.session_dir / "reply_ctx.json")
        self.exchange_file = str(self.session_dir / "llm_exchange.json")

    def setup(self) -> dict:
        """Clone repo into session workspace."""
        if self.workspace.exists():
            shutil.rmtree(self.workspace)
        proc = subprocess.run(
            ["git", "clone", REPO_URL, str(self.workspace)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            return {"error": f"clone failed: {proc.stderr.strip()}"}

        # Save session info
        info = {
            "session_dir": str(self.session_dir),
            "workspace": str(self.workspace),
            "new_ctx": self.new_ctx,
            "reply_ctx": self.reply_ctx,
            "exchange_file": self.exchange_file,
            "created": _ts(),
        }
        (self.session_dir / "session_info.json").write_text(
            json.dumps(info, indent=2), encoding="utf-8"
        )
        return {"action": "setup_done", **info}

    def run_new(self) -> dict:
        """Init + run discuss-new until LLM step."""
        params = {
            "category": "discussion",
            "title": f"step-test-{_ts()}",
            "content": (
                "# 分步集成测试\n\n"
                "由 Claude Code step_runner 自动编排执行的集成测试。\n\n"
                "## 验证目标\n"
                "1. prepare 步骤正确解析参数\n"
                "2. Claude Code 自身作为 LLM 生成摘要\n"
                "3. publish 步骤写文件并 git commit\n"
            ),
            "mention_users": "",
            "mention_comments": "",
        }

        # Save title for reply step
        (self.session_dir / "thread_title.txt").write_text(
            params["title"], encoding="utf-8"
        )

        # Init
        r = _run_step(["init",
                        "--pipeline", "discuss-new",
                        "--workspace", str(self.workspace),
                        "--user-id", "huangshengli",
                        "--params", json.dumps(params),
                        "--context", self.new_ctx])
        if "error" in r:
            return r

        # Run prepare
        r = _run_step(["next", "--context", self.new_ctx])
        if r.get("action") == "error":
            return r

        # Run next — should be LLM step
        r = _run_step(["next", "--context", self.new_ctx])

        # Save prompt for Claude Code to read
        if r.get("action") == "need_llm":
            (Path(self.exchange_file)).write_text(
                json.dumps({"step": "new", "prompt": r["prompt"],
                            "schema": r.get("schema")},
                           ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return r

    def resume_new(self) -> dict:
        """Read LLM response from exchange file, inject, finish discuss-new."""
        exchange = Path(self.exchange_file)
        if not exchange.exists():
            return {"error": "exchange file not found — write LLM response first"}

        data = json.loads(exchange.read_text(encoding="utf-8"))
        response = data.get("response")
        if not response:
            return {"error": "no 'response' field in exchange file"}

        # Inject
        r = _run_step(["respond", "--context", self.new_ctx,
                        "--response", json.dumps(response)])
        if "error" in r:
            return r

        # Run publish
        r = _run_step(["next", "--context", self.new_ctx])
        if r.get("action") == "error":
            return r

        # Finalize
        r2 = _run_step(["next", "--context", self.new_ctx])
        return r2 if r2.get("action") == "done" else r

    def run_reply(self) -> dict:
        """Init + run discuss-reply until LLM step."""
        title = (self.session_dir / "thread_title.txt").read_text(encoding="utf-8").strip()
        params = {
            "category": "discussion",
            "thread": title,
            "content": (
                "# 回复：测试验证通过\n\n"
                "step_runner 分步编排方案已验证可行。\n\n"
                "1. 代码步骤直接执行\n"
                "2. LLM 步骤由 Claude Code 自身生成\n"
                "3. 无子进程嵌套问题\n"
            ),
            "mention_users": "huangshengli",
            "mention_comments": "",
        }

        # Init
        r = _run_step(["init",
                        "--pipeline", "discuss-reply",
                        "--workspace", str(self.workspace),
                        "--user-id", "ken",
                        "--params", json.dumps(params),
                        "--context", self.reply_ctx])
        if "error" in r:
            return r

        # Run prepare
        r = _run_step(["next", "--context", self.reply_ctx])
        if r.get("action") == "error":
            return r

        # Run next — should be LLM step
        r = _run_step(["next", "--context", self.reply_ctx])

        if r.get("action") == "need_llm":
            (Path(self.exchange_file)).write_text(
                json.dumps({"step": "reply", "prompt": r["prompt"],
                            "schema": r.get("schema")},
                           ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return r

    def resume_reply(self) -> dict:
        """Read LLM response from exchange file, inject, finish discuss-reply."""
        exchange = Path(self.exchange_file)
        if not exchange.exists():
            return {"error": "exchange file not found — write LLM response first"}

        data = json.loads(exchange.read_text(encoding="utf-8"))
        response = data.get("response")
        if not response:
            return {"error": "no 'response' field in exchange file"}

        # Inject
        r = _run_step(["respond", "--context", self.reply_ctx,
                        "--response", json.dumps(response)])
        if "error" in r:
            return r

        # Run publish
        r = _run_step(["next", "--context", self.reply_ctx])
        if r.get("action") == "error":
            return r

        # Finalize
        r2 = _run_step(["next", "--context", self.reply_ctx])
        return r2 if r2.get("action") == "done" else r

    def verify(self) -> dict:
        """Verify git state and generated files."""
        ws = str(self.workspace)
        log = subprocess.run(
            ["git", "-C", ws, "log", "--oneline", "-10"],
            capture_output=True, text=True,
        )
        title = (self.session_dir / "thread_title.txt").read_text(encoding="utf-8").strip()
        thread_dir = self.workspace / "discussions" / "discussion" / title
        files = sorted(str(f.name) for f in thread_dir.glob("*.md")) if thread_dir.exists() else []

        result = {
            "git_log": log.stdout.strip().split("\n"),
            "thread_dir_exists": thread_dir.exists(),
            "thread_files": files,
            "file_count": len(files),
            "index_exists": (self.workspace / "index" / f"{title}-discuss.index.yaml").exists(),
        }

        # Save verification result
        (self.session_dir / "verify_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return result


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=[
        "setup", "run-new", "resume-new",
        "run-reply", "resume-reply", "verify",
    ])
    parser.add_argument("--session-dir", help="Reuse existing session directory")
    args = parser.parse_args()

    session_dir = Path(args.session_dir) if args.session_dir else None
    session = StepTestSession(session_dir)

    cmd_map = {
        "setup": session.setup,
        "run-new": session.run_new,
        "resume-new": session.resume_new,
        "run-reply": session.run_reply,
        "resume-reply": session.resume_reply,
        "verify": session.verify,
    }

    result = cmd_map[args.command]()
    _print_json(result)


if __name__ == "__main__":
    main()
