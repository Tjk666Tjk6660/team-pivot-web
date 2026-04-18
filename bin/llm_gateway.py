"""Stub LLM Backend.

Temporary placeholder: EC Gateway's agent chat endpoint is being reworked.
Until that lands, every `llm` step in a pipeline returns a shape-valid stub
populated with the string "大模型stub占位符" so other parts of the pipeline
can keep running end-to-end.

When EC's replacement endpoint is ready, revive this file from git history
(previous revision called `POST /v1/agent/chat/completions` via urllib).
"""
from __future__ import annotations

import json
from typing import Any, Protocol


STUB_TEXT = "大模型stub占位符"


class LLMBackend(Protocol):
    def call(self, prompt: str, step_name: str, schema_path: str | None = None) -> dict:
        """Send prompt to LLM, return parsed JSON response matching schema."""
        ...


def resolve_gateway_url() -> str:
    """Retained for app-runner import compatibility; stub mode ignores URL."""
    return ""


def _stub_from_schema(schema: dict[str, Any]) -> Any:
    """Build a minimal value that satisfies the given JSON schema.

    String → STUB_TEXT. Number/integer → 0. Boolean → False. Array → [].
    Object → dict with each `required` field recursively filled; unknown
    or missing type falls back to STUB_TEXT.
    """
    t = schema.get("type")
    if t == "object":
        out: dict[str, Any] = {}
        props = schema.get("properties", {}) or {}
        for field in schema.get("required", []) or []:
            out[field] = _stub_from_schema(props.get(field, {}))
        return out
    if t == "array":
        return []
    if t == "integer" or t == "number":
        return 0
    if t == "boolean":
        return False
    return STUB_TEXT


class GatewayLLMBackend:
    """Stub backend: returns a schema-valid placeholder for every call."""

    def __init__(self, url: str = ""):
        self.url = url

    def call(self, prompt: str, step_name: str, schema_path: str | None = None) -> dict:
        if schema_path:
            try:
                with open(schema_path, encoding="utf-8") as f:
                    schema = json.load(f)
                stub = _stub_from_schema(schema)
                if isinstance(stub, dict) and "output" not in stub:
                    return {"output": stub}
                return {"output": stub}
            except (OSError, json.JSONDecodeError):
                pass
        return {"output": STUB_TEXT}
