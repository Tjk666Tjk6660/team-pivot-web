"""Synchronous one-shot wrapper around `stream_chat` for non-conversational
callers — daily-report scoring, future jobs that need a single prompt → text
without driving a tool-use loop.

The streaming SSE pipeline in `client.py` is the right tool for the chat UI
(token-by-token display + tool calls); for batch / cron use cases we just
want a single `str` and don't care about deltas. This module bridges that gap
without duplicating client.py."""
from __future__ import annotations

import asyncio
import logging

from server.ai.client import AIError, stream_chat

__all__ = ["generate_text", "AIError"]

log = logging.getLogger("server.ai.oneshot")


def generate_text(
    *,
    messages: list[dict],
    model: str,
    api_key: str,
    base_url: str,
    timeout_seconds: float = 90.0,
) -> str:
    """Run a single chat turn end-to-end and return the model's text reply.

    Aggregates every `{"type": "text", "delta": ...}` event from `stream_chat`
    into one string. Tool calls are ignored — callers that need tools should
    drive `stream_chat` directly.

    Raises:
        AIError: non-200 from the AI endpoint (e.g., bad key, model not found)
        TimeoutError: streaming did not finish within `timeout_seconds`
                      (asyncio.TimeoutError on Python < 3.11; aliased to
                      builtins.TimeoutError on 3.11+)

    **Caller from inside an existing asyncio loop**: don't. This uses
    `asyncio.run` and will raise `RuntimeError: cannot be called from a
    running event loop`. Daily-report runner is sync so this is fine.
    """
    async def _collect() -> str:
        parts: list[str] = []
        async for ev in stream_chat(
            messages, model, api_key, base_url, tools=None,
        ):
            if ev.get("type") == "text":
                parts.append(ev.get("delta") or "")
            # tool_call / finish events are intentionally ignored — caller
            # expects flat text output, not a structured turn.
        return "".join(parts)

    return asyncio.run(asyncio.wait_for(_collect(), timeout=timeout_seconds))
