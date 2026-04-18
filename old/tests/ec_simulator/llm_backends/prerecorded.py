"""Pre-recorded LLM backend — returns fixed responses from a JSON fixture.

No API calls. Safe for CI. Responses keyed by step name.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class PrerecordedBackend:
    def __init__(self, responses: dict[str, dict[str, Any]]):
        """responses: {step_name: {"output": {...}}}"""
        self.responses = responses

    @classmethod
    def from_file(cls, path: str) -> "PrerecordedBackend":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(responses=data)

    @classmethod
    def from_dict(cls, data: dict[str, dict[str, Any]]) -> "PrerecordedBackend":
        return cls(responses=data)

    def call(self, prompt: str, step_name: str, schema_path: str | None = None) -> dict:
        if step_name not in self.responses:
            raise KeyError(
                f"PrerecordedBackend: no response for step '{step_name}'. "
                f"Available: {list(self.responses.keys())}"
            )
        return self.responses[step_name]
