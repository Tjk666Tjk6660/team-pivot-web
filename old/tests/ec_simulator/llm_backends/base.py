"""LLM backend protocol for the local pipeline runner."""
from __future__ import annotations

from typing import Protocol


class LLMBackend(Protocol):
    def call(self, prompt: str, step_name: str, schema_path: str | None = None) -> dict:
        """Send prompt to LLM, return parsed JSON response matching schema."""
        ...
