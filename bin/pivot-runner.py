#!/usr/bin/env python3
"""APP Pipeline Runner — executes pipelines per APP v0.4 spec.

Standalone program that:
  1. Discovers pipelines from pipelines/*/pipeline.yaml
  2. Executes constructor → business pipeline → destructor
  3. Handles code steps (subprocess) and llm steps (delegate to LLM backend)
  4. Manages inter-step data context and template rendering

Usage:
    # Run a specific pipeline
    python3 bin/pivot-runner.py run <pipeline-name> --params '{"key": "value"}'

    # List all discovered pipelines
    python3 bin/pivot-runner.py list

    # Run with custom app/data dirs
    python3 bin/pivot-runner.py run discuss-list \\
        --app-dir /path/to/team-pivot \\
        --data-space-dir /path/to/data_space
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol

import yaml


# ---------------------------------------------------------------------------
# LLM Backend Protocol
# ---------------------------------------------------------------------------

class LLMBackend(Protocol):
    def call(self, prompt: str, step_name: str, schema_path: str | None = None) -> dict:
        """Send prompt to LLM, return parsed JSON response matching schema."""
        ...


class StubLLMBackend:
    """Placeholder backend that errors — real integrations override this."""
    def call(self, prompt: str, step_name: str, schema_path: str | None = None) -> dict:
        raise RuntimeError(
            f"LLM step '{step_name}' requires an LLM backend. "
            "Set PIVOT_LLM_BACKEND or provide --llm-backend."
        )


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class PipelineResult:
    status: str  # "completed" | "error"
    output: dict = field(default_factory=dict)
    step_outputs: dict[str, dict] = field(default_factory=dict)
    error: Optional[str] = None
    constructor_error: Optional[str] = None
    destructor_error: Optional[str] = None


@dataclass
class StepDef:
    name: str
    type: str  # "code" | "llm"
    command: Optional[str] = None
    prompt: Optional[str] = None
    schema: Optional[str] = None
    model: Optional[str] = None
    skip_if: Optional[str] = None
    retry: int = 0


@dataclass
class PipelineInfo:
    name: str
    description: str
    triggers: list[str]
    yaml_path: Path


# ---------------------------------------------------------------------------
# Pipeline Runner
# ---------------------------------------------------------------------------

class PipelineRunner:
    """APP v0.4 compliant Pipeline Runner."""

    def __init__(
        self,
        app_dir: str | Path,
        data_space_dir: str = "",
        llm_backend: LLMBackend | None = None,
        tenant_id: str = "",
        user_id: str = "",
        app_name: str = "team-pivot",
        env_extras: Optional[dict[str, str]] = None,
    ):
        self.app_dir = Path(app_dir)
        self.data_space_dir = data_space_dir
        self.llm_backend = llm_backend or StubLLMBackend()
        self.tenant_id = tenant_id or os.environ.get("PIVOT_TENANT_ID", "")
        self.user_id = user_id or os.environ.get("PIVOT_USER_ID", "")
        self.app_name = app_name
        self.env_extras = env_extras or {}

    # -- Discovery ----------------------------------------------------------

    def discover_pipelines(self) -> list[PipelineInfo]:
        """Scan pipelines/*/pipeline.yaml, skip _-prefixed directories."""
        pipelines_dir = self.app_dir / "pipelines"
        if not pipelines_dir.is_dir():
            return []

        result = []
        for d in sorted(pipelines_dir.iterdir()):
            if not d.is_dir() or d.name.startswith("_"):
                continue
            yaml_path = d / "pipeline.yaml"
            if not yaml_path.exists():
                continue
            with open(yaml_path, encoding="utf-8") as f:
                defn = yaml.safe_load(f) or {}
            result.append(PipelineInfo(
                name=defn.get("name", d.name),
                description=defn.get("description", ""),
                triggers=defn.get("triggers", []),
                yaml_path=yaml_path,
            ))
        return result

    # -- Execution ----------------------------------------------------------

    def run(self, pipeline_name: str, params: dict) -> PipelineResult:
        """Execute: constructor → business pipeline → destructor."""
        # Constructor
        constructor_dir = self.app_dir / "pipelines" / "_constructor"
        if (constructor_dir / "pipeline.yaml").exists():
            ctor_result = self._run_pipeline_steps(constructor_dir, params)
            if ctor_result.status == "error":
                return PipelineResult(
                    status="error",
                    constructor_error=ctor_result.error,
                    error=f"Constructor failed: {ctor_result.error}",
                )

        # Business pipeline
        pipeline_dir = self.app_dir / "pipelines" / pipeline_name
        biz_result = self._run_pipeline_steps(pipeline_dir, params)

        # Destructor (always runs, like finally)
        destructor_error = None
        destructor_dir = self.app_dir / "pipelines" / "_destructor"
        if (destructor_dir / "pipeline.yaml").exists():
            dtor_result = self._run_pipeline_steps(destructor_dir, params)
            if dtor_result.status == "error":
                destructor_error = dtor_result.error

        biz_result.destructor_error = destructor_error
        return biz_result

    def _run_pipeline_steps(self, pipeline_dir: Path, params: dict) -> PipelineResult:
        yaml_path = pipeline_dir / "pipeline.yaml"
        if not yaml_path.exists():
            return PipelineResult(
                status="error",
                error=f"pipeline.yaml not found: {yaml_path}",
            )

        with open(yaml_path, encoding="utf-8") as f:
            pipeline_def = yaml.safe_load(f) or {}

        steps = [self._parse_step(s) for s in pipeline_def.get("steps", [])]
        output_step = pipeline_def.get("output", "")

        if not steps:
            return PipelineResult(status="completed")

        context: dict[str, dict] = {}

        for step in steps:
            if step.skip_if and self._eval_skip_if(step.skip_if, context):
                continue

            try:
                if step.type == "code":
                    result = self._run_code_step(step, pipeline_dir, params, context)
                elif step.type == "llm":
                    result = self._run_llm_step(step, pipeline_dir, params, context)
                else:
                    return PipelineResult(status="error", error=f"Unknown step type: {step.type}")
            except Exception as e:
                return PipelineResult(status="error", error=str(e), step_outputs=context)

            context[step.name] = result

        final_output = {}
        if output_step and output_step in context:
            final_output = context[output_step].get("output", {})

        return PipelineResult(status="completed", output=final_output, step_outputs=context)

    # -- Step Execution -----------------------------------------------------

    def _run_code_step(self, step: StepDef, pipeline_dir: Path, params: dict, context: dict) -> dict:
        stdin_payload = json.dumps({
            "input": params,
            "steps": {k: {"output": v.get("output", {})} for k, v in context.items()},
        })

        env = {
            **os.environ,
            "PYTHONIOENCODING": "utf-8",
            "PIVOT_DATA_SPACE_DIR": self.data_space_dir,
            "PIVOT_TENANT_ID": self.tenant_id,
            "PIVOT_USER_ID": self.user_id,
            "PIVOT_APP_NAME": self.app_name,
            "PIVOT_SKIP_CONFIG_CHECK": "1",  # constructor handles config checks
            **self.env_extras,
        }

        cmd_parts = step.command.split()
        if cmd_parts[0] == "python3":
            cmd_parts[0] = sys.executable

        proc = subprocess.run(
            cmd_parts,
            cwd=str(pipeline_dir),
            input=stdin_payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )

        if proc.returncode != 0:
            raise RuntimeError(
                f'Code step "{step.name}" exited with code {proc.returncode}\n'
                f"stderr: {proc.stderr.strip()}"
            )

        try:
            parsed = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise RuntimeError(
                f'Code step "{step.name}" produced invalid JSON: {proc.stdout[:200]}'
            )

        return parsed

    def _run_llm_step(self, step: StepDef, pipeline_dir: Path, params: dict, context: dict) -> dict:
        prompt = self._render_template(step.prompt or "", params, context)
        schema_path = str(pipeline_dir / step.schema) if step.schema else None

        max_attempts = max(1, (step.retry or 0) + 1)
        last_error = None

        for attempt in range(max_attempts):
            response = self.llm_backend.call(
                prompt=prompt if attempt == 0 else f"{prompt}\n\nPrevious attempt failed: {last_error}\nPlease fix and try again.",
                step_name=step.name,
                schema_path=schema_path,
            )

            # Schema validation
            if step.schema:
                schema_file = pipeline_dir / step.schema
                if schema_file.exists():
                    import jsonschema
                    with open(schema_file, encoding="utf-8") as f:
                        schema = json.load(f)
                    try:
                        output = response.get("output", {})
                        jsonschema.validate(instance=output, schema=schema)
                        return response  # validation passed
                    except jsonschema.ValidationError as e:
                        last_error = str(e.message)
                        continue
            else:
                return response

        raise RuntimeError(
            f'LLM step "{step.name}" failed validation after {max_attempts} attempts: {last_error}'
        )

    # -- Helpers ------------------------------------------------------------

    def _parse_step(self, raw: dict) -> StepDef:
        return StepDef(
            name=raw["name"],
            type=raw["type"],
            command=raw.get("command"),
            prompt=raw.get("prompt"),
            schema=raw.get("schema"),
            model=raw.get("model"),
            skip_if=raw.get("skip_if"),
            retry=raw.get("retry", 0),
        )

    def _render_template(self, template: str, params: dict, context: dict) -> str:
        def replacer(match: re.Match) -> str:
            expr = match.group(1).strip()
            parts = expr.split(".")

            if parts[0] == "input":
                val = params
                for p in parts[1:]:
                    val = val.get(p, "") if isinstance(val, dict) else ""
                return str(val) if val else ""

            step_name = parts[0]
            if step_name in context:
                val = context[step_name]
                for p in parts[1:]:
                    val = val.get(p, "") if isinstance(val, dict) else ""
                return str(val) if val else ""

            return match.group(0)

        return re.sub(r"\{\{(.+?)\}\}", replacer, template)

    def _eval_skip_if(self, expr: str, context: dict) -> bool:
        parts = expr.split(".")
        if len(parts) < 2:
            return False
        step_name = parts[0]
        if step_name not in context:
            return False
        val = context[step_name]
        for p in parts[1:]:
            if isinstance(val, dict):
                val = val.get(p)
            else:
                return False
        return bool(val)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="APP Pipeline Runner")
    sub = parser.add_subparsers(dest="command")

    # run
    p_run = sub.add_parser("run", help="Execute a pipeline")
    p_run.add_argument("pipeline", help="Pipeline name")
    p_run.add_argument("--params", default="{}", help="JSON input parameters")
    p_run.add_argument("--app-dir", default=None, help="APP root directory")
    p_run.add_argument("--data-space-dir", default=None, help="Data space directory")

    # list
    sub.add_parser("list", help="List discovered pipelines")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Resolve app dir
    app_dir = args.app_dir if hasattr(args, "app_dir") and args.app_dir else str(Path(__file__).parent.parent)
    data_space_dir = ""
    if hasattr(args, "data_space_dir") and args.data_space_dir:
        data_space_dir = args.data_space_dir
    else:
        data_space_dir = os.environ.get("PIVOT_DATA_SPACE_DIR", str(Path(app_dir) / "data_space"))

    runner = PipelineRunner(
        app_dir=app_dir,
        data_space_dir=data_space_dir,
    )

    if args.command == "list":
        pipelines = runner.discover_pipelines()
        output = [{"name": p.name, "description": p.description, "triggers": p.triggers} for p in pipelines]
        print(json.dumps(output, ensure_ascii=False, indent=2))

    elif args.command == "run":
        params = json.loads(args.params)
        result = runner.run(args.pipeline, params)
        print(json.dumps({
            "status": result.status,
            "output": result.output,
            "error": result.error,
            "constructor_error": result.constructor_error,
            "destructor_error": result.destructor_error,
        }, ensure_ascii=False, indent=2))
        sys.exit(0 if result.status == "completed" else 1)


if __name__ == "__main__":
    main()
