"""Claude CLI backend — shells out to local `claude` for real LLM calls.

Records every prompt and response to disk for test evidence.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


class ClaudeCLIBackend:
    """Call the local claude CLI for LLM steps.

    Each call is recorded to ``record_dir`` (if set):
      - <step_name>_prompt.txt   — the full rendered prompt
      - <step_name>_response.json — the raw JSON response
    """

    def __init__(self, record_dir: str | Path | None = None):
        self.record_dir = Path(record_dir) if record_dir else None

    def call(
        self,
        prompt: str,
        step_name: str,
        schema_path: str | None = None,
    ) -> dict:
        # Build the claude CLI command
        cmd = ["claude", "-p", prompt, "--output-format", "json"]

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )

        if proc.returncode != 0:
            raise RuntimeError(
                f"claude CLI failed for step '{step_name}' "
                f"(exit {proc.returncode}):\n{proc.stderr.strip()}"
            )

        # claude --output-format json wraps the result; extract the text
        raw_output = proc.stdout.strip()
        try:
            cli_result = json.loads(raw_output)
        except json.JSONDecodeError:
            raise RuntimeError(
                f"claude CLI returned non-JSON for step '{step_name}':\n"
                f"{raw_output[:500]}"
            )

        # The claude CLI json output has a "result" field with the text
        if isinstance(cli_result, dict) and "result" in cli_result:
            text = cli_result["result"]
        elif isinstance(cli_result, str):
            text = cli_result
        else:
            text = raw_output

        # Parse the LLM's JSON response from the text
        try:
            response = json.loads(text)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code block
            import re
            match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
            if match:
                response = json.loads(match.group(1))
            else:
                raise RuntimeError(
                    f"LLM response for step '{step_name}' is not valid JSON:\n"
                    f"{text[:500]}"
                )

        # Wrap in the expected format if needed
        if "output" not in response:
            response = {"output": response}

        # Record to disk
        if self.record_dir:
            self.record_dir.mkdir(parents=True, exist_ok=True)
            (self.record_dir / f"{step_name}_prompt.txt").write_text(
                prompt, encoding="utf-8"
            )
            (self.record_dir / f"{step_name}_response.json").write_text(
                json.dumps(response, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        return response
