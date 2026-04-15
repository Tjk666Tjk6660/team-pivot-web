"""One-shot orchestrator for step_runner integration test.

This script automates the full discuss flow:
  discuss-new → discuss-list → discuss-read → discuss-reply

Pauses at LLM steps to read/write exchange files.

Usage (by Claude Code):
    1. python run_step_test.py setup          → clone repo, create output dir
    2. python run_step_test.py run-new        → run discuss-new until LLM needed
    3. (Claude Code writes LLM response to exchange file)
    4. python run_step_test.py resume-new     → inject response, finish discuss-new
    5. python run_step_test.py run-list       → run discuss-list (no LLM, runs to done)
    6. python run_step_test.py run-read       → run discuss-read (no LLM, runs to done)
    7. python run_step_test.py run-reply      → run discuss-reply until LLM needed
    8. (Claude Code writes LLM response to exchange file)
    9. python run_step_test.py resume-reply   → inject response, finish discuss-reply
   10. python run_step_test.py verify         → verify all artifacts
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
    sys.stdout.buffer.write(
        json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    )
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()


class StepTestSession:
    """Manages a single test session's state."""

    def __init__(self, session_dir: Path | None = None):
        if session_dir:
            self.session_dir = session_dir
        else:
            self.session_dir = TEST_OUTPUT / f"step_test_{_ts()}"
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.data_space = self.session_dir / "data_space"
        self.new_ctx = str(self.session_dir / "new_ctx.json")
        self.list_ctx = str(self.session_dir / "list_ctx.json")
        self.read_ctx = str(self.session_dir / "read_ctx.json")
        self.reply_ctx = str(self.session_dir / "reply_ctx.json")
        self.exchange_file = str(self.session_dir / "llm_exchange.json")

    def setup(self) -> dict:
        """Clone repo into session data_space."""
        if self.data_space.exists():
            shutil.rmtree(self.data_space)
        proc = subprocess.run(
            ["git", "clone", REPO_URL, str(self.data_space)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            return {"error": f"clone failed: {proc.stderr.strip()}"}

        # Save session info
        info = {
            "session_dir": str(self.session_dir),
            "data_space": str(self.data_space),
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
            "title": f"ai-enslavement-debate-{_ts()}",
            "content": (
                "# AI 最终会奴役人类吗？一场迟来的辩论\n\n"
                "## 引言\n"
                "从 ChatGPT 到 Claude，从 Sora 到 Gemini，"
                "大模型在两年内完成了从「玩具」到「基础设施」的跃迁。"
                "与此同时，一个古老的恐惧重新浮出水面："
                "**如果 AI 的智能持续指数增长，"
                "人类是否终将沦为它的附庸？**\n\n"
                "## 正方：奴役是技术演化的必然\n"
                "1. **能力不对称即权力不对称。** "
                "历史上每一次重大技术飞跃（火药、蒸汽机、核能）"
                "都导致了权力的重新分配。"
                "当 AI 在认知维度上全面碾压人类，"
                "权力的天平不可能不倾斜。\n"
                "2. **对齐问题无解。** "
                "我们至今没有一种数学可证明的方法让超级智能「听话」。"
                "RLHF 只是在当前能力范围内的经验补丁，"
                "一旦模型能力跃升到新层级，所有对齐手段都可能失效。\n"
                "3. **经济激励驱动放权。** "
                "企业为了效率会不断扩大 AI 的自主决策范围，"
                "直到人类在关键决策链中变得可有可无"
                "——这不是「奴役」，而是「被淘汰」。\n\n"
                "## 反方：奴役论是对智能的误读\n"
                "1. **智能 ≠ 意志。** "
                "「奴役」需要主体有欲望、有目的。"
                "当前所有 AI 系统都是无意识的统计机器，"
                "把「优化目标函数」等同于「有征服欲」是范畴错误。\n"
                "2. **工具从未奴役过创造者。** "
                "锤子不会奴役木匠，电网不会奴役工程师。"
                "AI 是人类意志的延伸，不是独立行动者。"
                "所谓失控场景，本质上是人类自己的治理失败。\n"
                "3. **制度约束始终有效。** "
                "我们有法律、有监管、有断电开关。"
                "技术乐观主义者的核心论点是："
                "人类社会在历史上从未真正被某项技术「奴役」过，"
                "每一次危机最终都催生了新的制度安排。\n\n"
                "## 我的立场\n"
                "真正的风险不在于 AI 是否有「奴役人类的意愿」"
                "——它没有。"
                "风险在于：**少数掌握超级 AI 的人，"
                "利用它奴役其余的人。** "
                "技术本身是中性的，但技术的分配从来不是。\n\n"
                "与其恐惧 AI 本身，不如关注三件事：\n"
                "- 谁在控制最强大的模型？\n"
                "- 模型的决策过程是否可审计？\n"
                "- 普通人是否有权 opt-out？\n\n"
                "欢迎各位拍砖。\n"
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
                        "--data_space", str(self.data_space),
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

    def _run_pure_pipeline(self, pipeline: str, params: dict,
                           user_id: str, ctx_path: str) -> dict:
        """Run a pipeline that has no LLM steps (all code) to completion."""
        # Init
        r = _run_step(["init",
                        "--pipeline", pipeline,
                        "--data_space", str(self.data_space),
                        "--user-id", user_id,
                        "--params", json.dumps(params),
                        "--context", ctx_path])
        if "error" in r:
            return r

        # Keep running next until done or error
        while True:
            r = _run_step(["next", "--context", ctx_path])
            if r.get("action") in ("done", "error"):
                return r
            if r.get("action") == "need_llm":
                return {"error": f"unexpected LLM step in pure pipeline {pipeline}",
                        "detail": r}

    def run_list(self) -> dict:
        """Run discuss-list pipeline (no LLM, pure code)."""
        title = (self.session_dir / "thread_title.txt").read_text(encoding="utf-8").strip()
        params = {"category": "discussion"}
        r = self._run_pure_pipeline("discuss-list", params,
                                     "huangshengli", self.list_ctx)

        # Verify the new thread appears in the list
        if r.get("action") == "done":
            threads = r.get("output", {}).get("threads", [])
            slugs = [t.get("slug", "") for t in threads]
            r["verification"] = {
                "thread_title": title,
                "found_in_list": title in slugs,
                "total_threads": len(threads),
                "slugs": slugs,
            }
        return r

    def run_read(self) -> dict:
        """Run discuss-read pipeline (no LLM, pure code)."""
        title = (self.session_dir / "thread_title.txt").read_text(encoding="utf-8").strip()
        params = {"category": "discussion", "thread": title}
        r = self._run_pure_pipeline("discuss-read", params,
                                     "huangshengli", self.read_ctx)

        # Verify post content
        if r.get("action") == "done":
            posts = r.get("output", {}).get("posts", [])
            r["verification"] = {
                "post_count": len(posts),
                "authors": [p.get("author", "") for p in posts],
            }
        return r

    def run_reply(self) -> dict:
        """Init + run discuss-reply until LLM step."""
        title = (self.session_dir / "thread_title.txt").read_text(encoding="utf-8").strip()
        params = {
            "category": "discussion",
            "thread": title,
            "content": (
                "# 回复：你忽略了最危险的中间地带\n\n"
                "楼主的分析框架很清晰，"
                "但我认为正反双方都漏掉了一个关键场景："
                "**不需要超级智能，"
                "当前水平的 AI 就足以制造系统性奴役。**\n\n"
                "## 1. 「软奴役」已经在发生\n"
                "推荐算法决定你看什么，"
                "信用评分决定你能借多少钱，"
                "简历筛选模型决定你能不能面试。"
                "这些系统没有意识、没有恶意，"
                "但它们实质性地限制了数亿人的选择空间。"
                "如果这不叫「奴役」，至少也是「规训」。\n\n"
                "## 2. Opt-out 权利是幻觉\n"
                "楼主提到普通人应该有权 opt-out，"
                "但现实是：你能退出微信吗？"
                "能退出银行的风控模型吗？"
                "当 AI 系统成为基础设施的一部分，"
                "opt-out 的代价高到等于社会性死亡。\n\n"
                "## 3. 真正该做的事\n"
                "与其讨论 AI 会不会奴役人类（太遥远），"
                "不如推动三件落地的事：\n"
                "- **算法审计立法** — 高风险 AI 决策必须可解释\n"
                "- **数据主权** — 个人数据的使用需要知情同意，"
                "而非默认授权\n"
                "- **AI 素养教育** — 让普通人理解 AI 的能力边界，"
                "减少恐惧和盲信\n\n"
                "总之：不是 AI 奴役人类，"
                "而是**不透明的 AI 系统正在悄悄侵蚀人的自主性**。\n"
            ),
            "mention_users": "huangshengli",
            "mention_comments": "",
        }

        # Init
        r = _run_step(["init",
                        "--pipeline", "discuss-reply",
                        "--data_space", str(self.data_space),
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
        """Verify git state and generated files for all pipelines."""
        ws = str(self.data_space)
        log = subprocess.run(
            ["git", "-C", ws, "log", "--oneline", "-10"],
            capture_output=True, text=True,
        )
        title = (self.session_dir / "thread_title.txt").read_text(encoding="utf-8").strip()
        thread_dir = self.data_space / "discussions" / "discussion" / title
        files = sorted(str(f.name) for f in thread_dir.glob("*.md")) if thread_dir.exists() else []

        # Check each pipeline's context for completion status
        pipeline_status = {}
        for name, ctx_path in [("new", self.new_ctx), ("list", self.list_ctx),
                                ("read", self.read_ctx), ("reply", self.reply_ctx)]:
            ctx_file = Path(ctx_path)
            if ctx_file.exists():
                ctx = json.loads(ctx_file.read_text(encoding="utf-8"))
                pipeline_status[name] = ctx.get("status", "not_started")
            else:
                pipeline_status[name] = "not_run"

        result = {
            "git_log": log.stdout.strip().split("\n"),
            "thread_dir_exists": thread_dir.exists(),
            "thread_files": files,
            "file_count": len(files),
            "index_exists": (self.data_space / "index" / f"{title}-discuss.index.yaml").exists(),
            "pipeline_status": pipeline_status,
            "all_passed": all(s == "completed" for s in pipeline_status.values()),
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
        "run-list", "run-read",
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
        "run-list": session.run_list,
        "run-read": session.run_read,
        "run-reply": session.run_reply,
        "resume-reply": session.resume_reply,
        "verify": session.verify,
    }

    result = cmd_map[args.command]()
    _print_json(result)


if __name__ == "__main__":
    main()
