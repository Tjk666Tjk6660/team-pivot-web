"""End-to-end test: new thread -> reply -> list -> read -> result."""
import json
import os
import subprocess
import sys
from pathlib import Path


def run_pipeline_step(step_path: Path, input_obj, steps, env):
    proc = subprocess.run(
        [sys.executable, str(step_path)],
        input=json.dumps({"input": input_obj, "steps": steps}),
        capture_output=True,
        text=True,
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"step {step_path} failed: {proc.stderr}")
    return json.loads(proc.stdout)


class TestDiscussFlow:
    def test_full_lifecycle(self, tmp_git_repo: Path):
        repo = tmp_git_repo
        env = {
            **os.environ,
            "PIVOT_TENANT_ID": "tenant-a",
            "PIVOT_USER_ID": "ken",
            "PIVOT_WORKSPACE_DIR": str(repo),
            "PIVOT_APP_NAME": "pivot",
        }

        draft_dir = repo / "discussions/enclaws/test-thread/members/ken"
        draft_dir.mkdir(parents=True)
        draft = draft_dir / "draft_proposal.md"
        draft.write_text(
            "---\ntype: proposal\nauthor: ken\nsummary: \"**摘要**：test thread\"\n---\n# Proposal\nbody\n",
            encoding="utf-8",
        )

        project_root = Path(__file__).parent.parent.parent
        publish_step = project_root / "pipelines/discuss-new/steps/publish.py"
        result = run_pipeline_step(
            publish_step,
            input_obj={
                "category": "enclaws",
                "title": "test-thread",
                "draft_path": str(draft),
                "mention_users": "",
                "mention_comments": "",
            },
            steps={
                "prepare": {
                    "output": {
                        "category": "enclaws",
                        "title": "test-thread",
                        "draft_path": str(draft),
                        "author": "ken",
                        "mention_users": "",
                        "mention_comments": "",
                    }
                }
            },
            env=env,
        )
        assert result["output"]["committed"] is True

        thread_dir = repo / "discussions/enclaws/test-thread"
        posts = list(thread_dir.glob("001_*.md"))
        assert len(posts) == 1

        index_file = repo / "index/test-thread-discuss.index.yaml"
        assert index_file.exists()

        from tools import index as index_mod
        idx = index_mod.load(str(index_file))
        assert len(idx.discussions) == 1
        assert idx.discussions[0].status == "open"
        assert len(idx.timeline) == 1

        reply_draft_dir = repo / "discussions/enclaws/test-thread/members/shengli"
        reply_draft_dir.mkdir(parents=True)
        reply_draft = reply_draft_dir / "draft_reply.md"
        reply_draft.write_text(
            "---\ntype: reply\nauthor: shengli\nsummary: reply summary\n---\n# reply body\n",
            encoding="utf-8",
        )

        reply_env = {**env, "PIVOT_USER_ID": "shengli"}
        reply_step = project_root / "pipelines/discuss-reply/steps/publish.py"
        reply_result = run_pipeline_step(
            reply_step,
            input_obj={
                "category": "enclaws",
                "thread": "test-thread",
                "draft_path": str(reply_draft),
                "mention_users": "",
                "mention_comments": "",
            },
            steps={
                "prepare": {
                    "output": {
                        "category": "enclaws",
                        "thread": "test-thread",
                        "draft_path": str(reply_draft),
                        "author": "shengli",
                        "mention_users": "",
                        "mention_comments": "",
                    }
                }
            },
            env=reply_env,
        )
        assert reply_result["output"]["committed"] is True
        assert reply_result["output"]["post_number"] == 2

        list_step = project_root / "pipelines/discuss-list/steps/list_threads.py"
        list_result = run_pipeline_step(
            list_step,
            input_obj={"category": "enclaws"},
            steps={},
            env=env,
        )
        threads = list_result["output"]["threads"]
        assert len(threads) == 1
        assert threads[0]["slug"] == "test-thread"
        assert threads[0]["status_display"] == "讨论中"
