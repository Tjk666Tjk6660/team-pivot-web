"""Step-by-step pipeline runner — for Claude Code self-orchestration.

Instead of calling `claude -p` in a subprocess, this script runs one
pipeline step at a time.  For LLM steps it prints the rendered prompt
so the caller (Claude Code) can generate the response and feed it back.

Usage:
    # 1. Init — create context file
    python step_runner.py init \\
        --pipeline discuss-new \\
        --data_space /path/to/repo \\
        --user-id huangshengli \\
        --params '{"category":"discussion","title":"test","content":"..."}' \\
        --context run_ctx.json

    # 2. Run next step (auto-detects code vs llm)
    python step_runner.py next --context run_ctx.json
    #   → code step: executes & prints output
    #   → llm step: prints {"action":"need_llm","prompt":"...","step":"..."}

    # 3. Inject LLM response (only after an llm step)
    python step_runner.py respond --context run_ctx.json \\
        --response '{"output":{"summary":"..."}}'

    # 4. Repeat `next` until all steps done
    #    Final output: {"action":"done","output":{...}}
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


APP_DIR = str(Path(__file__).parent.parent.parent)  # team-pivot/


def _out(data: dict) -> None:
    """Write JSON to stdout using UTF-8, bypassing Windows GBK console encoding."""
    sys.stdout.buffer.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()


# ---------------------------------------------------------------------------
# Context helpers — persist state between invocations
# ---------------------------------------------------------------------------

def _load_ctx(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_ctx(path: str, ctx: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ctx, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Template rendering (same logic as LocalPipelineRunner)
# ---------------------------------------------------------------------------

def _render_template(template: str, params: dict, steps: dict) -> str:
    def replacer(match: re.Match) -> str:
        expr = match.group(1).strip()
        parts = expr.split(".")
        if parts[0] == "input":
            val = params
            for p in parts[1:]:
                val = val.get(p, "") if isinstance(val, dict) else ""
            return str(val) if val else ""
        step_name = parts[0]
        if step_name in steps:
            val = steps[step_name]
            for p in parts[1:]:
                val = val.get(p, "") if isinstance(val, dict) else ""
            return str(val) if val else ""
        return match.group(0)
    return re.sub(r"\{\{(.+?)\}\}", replacer, template)


def _eval_skip_if(expr: str, steps: dict) -> bool:
    parts = expr.split(".")
    if len(parts) < 2 or parts[0] not in steps:
        return False
    val = steps[parts[0]]
    for p in parts[1:]:
        if isinstance(val, dict):
            val = val.get(p)
        else:
            return False
    return bool(val)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_init(args):
    """Create a fresh context file for a pipeline run."""
    import yaml

    pipeline_dir = Path(APP_DIR) / "pipelines" / args.pipeline
    yaml_path = pipeline_dir / "pipeline.yaml"
    if not yaml_path.exists():
        _out({"error": f"pipeline.yaml not found: {yaml_path}"})
        sys.exit(1)

    with open(yaml_path, encoding="utf-8") as f:
        pipeline_def = yaml.safe_load(f)

    ctx = {
        "pipeline": args.pipeline,
        "pipeline_dir": str(pipeline_dir),
        "data_space": args.data_space,
        "user_id": args.user_id,
        "params": json.loads(args.params),
        "steps_def": pipeline_def.get("steps", []),
        "output_step": pipeline_def.get("output", ""),
        "step_results": {},
        "current_step_idx": 0,
        "status": "running",
    }
    _save_ctx(args.context, ctx)
    _out({
        "action": "initialized",
        "pipeline": args.pipeline,
        "total_steps": len(ctx["steps_def"]),
        "step_names": [s["name"] for s in ctx["steps_def"]],
    })


def cmd_next(args):
    """Execute the next step, or report what's needed."""
    ctx = _load_ctx(args.context)

    if ctx["status"] != "running":
        _out({"action": "done", "status": ctx["status"],
              "output": ctx.get("final_output", {})})
        return

    idx = ctx["current_step_idx"]
    if idx >= len(ctx["steps_def"]):
        # All steps done — finalize
        output_step = ctx["output_step"]
        final = ctx["step_results"].get(output_step, {}).get("output", {})
        ctx["status"] = "completed"
        ctx["final_output"] = final
        _save_ctx(args.context, ctx)
        _out({"action": "done", "output": final})
        return

    step_def = ctx["steps_def"][idx]
    step_name = step_def["name"]
    step_type = step_def["type"]

    # Check skip_if
    skip_if = step_def.get("skip_if")
    if skip_if and _eval_skip_if(skip_if, ctx["step_results"]):
        ctx["current_step_idx"] = idx + 1
        _save_ctx(args.context, ctx)
        _out({"action": "skipped", "step": step_name})
        return

    if step_type == "code":
        _exec_code_step(ctx, step_def, args.context)
    elif step_type == "llm":
        _request_llm_step(ctx, step_def, args.context)
    else:
        _out({"error": f"unknown step type: {step_type}"})
        sys.exit(1)


def _exec_code_step(ctx: dict, step_def: dict, ctx_path: str):
    """Run a code step via subprocess."""
    pipeline_dir = ctx["pipeline_dir"]
    params = ctx["params"]
    step_results = ctx["step_results"]
    step_name = step_def["name"]

    stdin_payload = json.dumps({
        "input": params,
        "steps": {k: {"output": v.get("output", {})}
                  for k, v in step_results.items()},
    })

    env = {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "PIVOT_DATA_SPACE_DIR": ctx["data_space"],
        "PIVOT_TENANT_ID": "test-tenant",
        "PIVOT_USER_ID": ctx["user_id"],
        "PIVOT_APP_NAME": "pivot",
    }

    cmd_parts = step_def["command"].split()
    if cmd_parts[0] == "python3":
        cmd_parts[0] = sys.executable

    proc = subprocess.run(
        cmd_parts,
        cwd=pipeline_dir,
        input=stdin_payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )

    if proc.returncode != 0:
        ctx["status"] = "error"
        ctx["error"] = proc.stderr.strip()
        _save_ctx(ctx_path, ctx)
        _out({
            "action": "error",
            "step": step_name,
            "stderr": proc.stderr.strip(),
        })
        sys.exit(1)

    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        ctx["status"] = "error"
        ctx["error"] = f"invalid JSON output: {proc.stdout[:300]}"
        _save_ctx(ctx_path, ctx)
        _out({
            "action": "error",
            "step": step_name,
            "raw_output": proc.stdout[:300],
        })
        sys.exit(1)

    ctx["step_results"][step_name] = result
    ctx["current_step_idx"] += 1
    _save_ctx(ctx_path, ctx)

    _out({
        "action": "step_done",
        "step": step_name,
        "type": "code",
        "output": result,
    })


def _request_llm_step(ctx: dict, step_def: dict, ctx_path: str):
    """Output the rendered prompt for the caller to generate a response."""
    params = ctx["params"]
    step_results = ctx["step_results"]
    step_name = step_def["name"]

    prompt = _render_template(
        step_def.get("prompt", ""), params, step_results
    )

    # Read schema if available
    schema = None
    if step_def.get("schema"):
        schema_path = Path(ctx["pipeline_dir"]) / step_def["schema"]
        if schema_path.exists():
            with open(schema_path, encoding="utf-8") as f:
                schema = json.load(f)

    # Mark waiting — don't advance step index yet
    ctx["pending_llm"] = step_name
    _save_ctx(ctx_path, ctx)

    output = {
        "action": "need_llm",
        "step": step_name,
        "prompt": prompt,
    }
    if schema:
        output["schema"] = schema
    _out(output)


def cmd_respond(args):
    """Inject an LLM response and advance to the next step."""
    ctx = _load_ctx(args.context)

    pending = ctx.get("pending_llm")
    if not pending:
        _out({"error": "no pending LLM step"})
        sys.exit(1)

    response = json.loads(args.response)
    if "output" not in response:
        response = {"output": response}

    ctx["step_results"][pending] = response
    ctx["current_step_idx"] += 1
    del ctx["pending_llm"]
    _save_ctx(args.context, ctx)

    _out({
        "action": "llm_injected",
        "step": pending,
        "output": response,
    })


def cmd_status(args):
    """Show current run status."""
    ctx = _load_ctx(args.context)
    idx = ctx["current_step_idx"]
    total = len(ctx["steps_def"])
    pending = ctx.get("pending_llm")

    info = {
        "pipeline": ctx["pipeline"],
        "status": ctx["status"],
        "progress": f"{idx}/{total}",
        "completed_steps": list(ctx["step_results"].keys()),
    }
    if pending:
        info["waiting_for_llm"] = pending
    if ctx["status"] == "completed":
        info["output"] = ctx.get("final_output", {})
    if ctx["status"] == "error":
        info["error"] = ctx.get("error", "")
    _out(info)


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Step-by-step pipeline runner")
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init")
    p_init.add_argument("--pipeline", required=True)
    p_init.add_argument("--data_space", required=True)
    p_init.add_argument("--user-id", default="test-user")
    p_init.add_argument("--params", required=True, help="JSON string")
    p_init.add_argument("--context", default="run_ctx.json")

    p_next = sub.add_parser("next")
    p_next.add_argument("--context", default="run_ctx.json")

    p_resp = sub.add_parser("respond")
    p_resp.add_argument("--context", default="run_ctx.json")
    p_resp.add_argument("--response", required=True, help="JSON string")

    p_status = sub.add_parser("status")
    p_status.add_argument("--context", default="run_ctx.json")

    args = parser.parse_args()
    if args.command == "init":
        cmd_init(args)
    elif args.command == "next":
        cmd_next(args)
    elif args.command == "respond":
        cmd_respond(args)
    elif args.command == "status":
        cmd_status(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
