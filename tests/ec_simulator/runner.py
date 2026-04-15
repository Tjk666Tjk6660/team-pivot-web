"""Local Pipeline Runner — executes pipeline.yaml locally for testing.

Mirrors EC's Pipeline Runner behavior:
  - code steps: spawn Python subprocess with stdin JSON / stdout JSON
  - llm steps: delegate to a configurable LLM backend
  - skip_if: evaluate conditions against step context
  - template rendering: {{step.output.field}} replacement
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from tests.ec_simulator.llm_backends.base import LLMBackend


@dataclass
class PipelineResult:
    status: str  # "completed" | "error"
    output: dict = field(default_factory=dict)
    step_outputs: dict[str, dict] = field(default_factory=dict)
    error: Optional[str] = None


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


class LocalPipelineRunner:
    """Execute a pipeline locally, same behavior as EC's Pipeline Runner."""

    def __init__(
        self,
        app_dir: str,
        data_space_dir: str,
        llm_backend: LLMBackend,
        tenant_id: str = "test-tenant",
        user_id: str = "test-user",
        app_name: str = "pivot",
        env_extras: Optional[dict[str, str]] = None,
        record_dir: Optional[str] = None,
    ):
        self.app_dir = Path(app_dir)
        self.data_space_dir = data_space_dir
        self.llm_backend = llm_backend
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.app_name = app_name
        self.env_extras = env_extras or {}
        self.record_dir = Path(record_dir) if record_dir else None

    def run(self, pipeline_name: str, params: dict) -> PipelineResult:
        pipeline_dir = self.app_dir / "pipelines" / pipeline_name
        yaml_path = pipeline_dir / "pipeline.yaml"

        if not yaml_path.exists():
            return PipelineResult(
                status="error",
                error=f"pipeline.yaml not found: {yaml_path}",
            )

        with open(yaml_path, encoding="utf-8") as f:
            pipeline_def = yaml.safe_load(f)

        steps = [self._parse_step(s) for s in pipeline_def.get("steps", [])]
        output_step = pipeline_def.get("output", "")

        context: dict[str, dict] = {}  # {step_name: {"output": {...}}}

        for step in steps:
            # Check skip_if
            if step.skip_if and self._eval_skip_if(step.skip_if, context):
                continue

            try:
                if step.type == "code":
                    result = self._run_code_step(
                        step, pipeline_dir, params, context
                    )
                elif step.type == "llm":
                    result = self._run_llm_step(
                        step, pipeline_dir, params, context
                    )
                else:
                    return PipelineResult(
                        status="error",
                        error=f"unknown step type: {step.type}",
                    )
            except Exception as e:
                return PipelineResult(
                    status="error",
                    error=str(e),
                    step_outputs=context,
                )

            context[step.name] = result

        # Final output
        final_output = {}
        if output_step and output_step in context:
            final_output = context[output_step].get("output", {})

        result = PipelineResult(
            status="completed",
            output=final_output,
            step_outputs=context,
        )
        self._record_pipeline_result(pipeline_name, params, result)
        return result

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

    def _run_code_step(
        self,
        step: StepDef,
        pipeline_dir: Path,
        params: dict,
        context: dict,
    ) -> dict:
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
            **self.env_extras,
        }

        cmd_parts = step.command.split()
        # Replace python3 with sys.executable for Windows compatibility
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
                f"code step \"{step.name}\" exited with code {proc.returncode}\n"
                f"stderr: {proc.stderr.strip()}"
            )

        try:
            parsed = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise RuntimeError(
                f"code step \"{step.name}\" produced invalid JSON: "
                f"{proc.stdout[:200]}"
            )

        self._record_step(step.name, "code", stdin_payload, parsed, proc.stderr)
        return parsed

    def _run_llm_step(
        self,
        step: StepDef,
        pipeline_dir: Path,
        params: dict,
        context: dict,
    ) -> dict:
        # Render prompt template
        prompt = self._render_template(step.prompt or "", params, context)

        # Call LLM backend
        schema_path = str(pipeline_dir / step.schema) if step.schema else None
        response = self.llm_backend.call(
            prompt=prompt,
            step_name=step.name,
            schema_path=schema_path,
        )

        self._record_step(step.name, "llm", prompt, response)
        return response

    def _render_template(
        self, template: str, params: dict, context: dict
    ) -> str:
        """Replace {{step.output.field}} and {{input.field}} with values."""
        def replacer(match: re.Match) -> str:
            expr = match.group(1).strip()
            parts = expr.split(".")

            if parts[0] == "input":
                val = params
                for p in parts[1:]:
                    val = val.get(p, "") if isinstance(val, dict) else ""
                return str(val) if val else ""

            # step_name.output.field
            step_name = parts[0]
            if step_name in context:
                val = context[step_name]
                for p in parts[1:]:
                    val = val.get(p, "") if isinstance(val, dict) else ""
                return str(val) if val else ""

            return match.group(0)  # leave unchanged if not resolvable

        return re.sub(r"\{\{(.+?)\}\}", replacer, template)

    def _record_step(
        self, step_name: str, step_type: str,
        input_data: Any, output_data: Any, stderr: str = "",
    ) -> None:
        if not self.record_dir:
            return
        self.record_dir.mkdir(parents=True, exist_ok=True)
        prefix = f"step_{step_name}"
        if step_type == "llm":
            (self.record_dir / f"{prefix}_prompt.txt").write_text(
                str(input_data), encoding="utf-8"
            )
        else:
            (self.record_dir / f"{prefix}_input.json").write_text(
                input_data if isinstance(input_data, str)
                else json.dumps(input_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        (self.record_dir / f"{prefix}_output.json").write_text(
            json.dumps(output_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if stderr and stderr.strip():
            (self.record_dir / f"{prefix}_stderr.txt").write_text(
                stderr, encoding="utf-8"
            )

    def _record_pipeline_result(
        self, pipeline_name: str, params: dict, result: "PipelineResult"
    ) -> None:
        if not self.record_dir:
            return
        self.record_dir.mkdir(parents=True, exist_ok=True)
        (self.record_dir / "pipeline_input.json").write_text(
            json.dumps({"pipeline": pipeline_name, "params": params},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (self.record_dir / "pipeline_result.json").write_text(
            json.dumps({
                "status": result.status,
                "output": result.output,
                "step_outputs": result.step_outputs,
                "error": result.error,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _eval_skip_if(self, expr: str, context: dict) -> bool:
        """Evaluate skip_if expression like 'prepare.output.has_summary'."""
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
