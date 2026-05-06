from __future__ import annotations

import json
import logging
from urllib.parse import urlparse
from typing import AsyncIterator

import httpx

log = logging.getLogger("server.ai.client")

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "anthropic/claude-sonnet-4-5"


class AIError(Exception):
    pass


async def stream_chat(
    messages: list[dict],
    model: str,
    api_key: str,
    base_url: str,
    tools: list[dict] | None = None,
    timeout_read_seconds: float = 180.0,
) -> AsyncIterator[dict]:
    """
    Stream a single turn from an OpenAI-compatible endpoint.

    Yields structured events so the caller can drive the tool-use loop:

        {"type": "text", "delta": "..."}              # visible token
        {"type": "tool_call", "id": "...",
         "name": "...", "arguments": "<json-string>"} # complete tool call
        {"type": "finish", "reason": "stop|tool_calls|length|..."}

    The caller is responsible for:
      - Streaming text deltas to the frontend.
      - Dispatching tool_calls, appending assistant+tool messages, and
        invoking stream_chat again for the next turn.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    hostname = (urlparse(base_url).hostname or "").lower()
    if hostname.endswith("openrouter.ai"):
        headers["HTTP-Referer"] = "https://team-pivot-web"
        headers["X-Title"] = "team-pivot-web"

    payload: dict = {"model": model, "messages": messages, "stream": True}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    # Accumulate tool call fragments by their `index` in the OpenAI delta schema.
    pending: dict[int, dict] = {}
    finish_reason: str | None = None

    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=timeout_read_seconds)) as client:
        async with client.stream(
            "POST",
            f"{base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
        ) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                raise AIError(f"AI endpoint {resp.status_code}: {body.decode()[:300]}")
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                try:
                    choice = chunk["choices"][0]
                except (KeyError, IndexError):
                    continue

                delta = choice.get("delta") or {}
                fr = choice.get("finish_reason")
                if fr:
                    finish_reason = fr

                text = delta.get("content")
                if text:
                    yield {"type": "text", "delta": text}

                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    slot = pending.setdefault(
                        idx, {"id": "", "name": "", "arguments": ""}
                    )
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] = fn["name"]
                    if fn.get("arguments"):
                        slot["arguments"] += fn["arguments"]

    for slot in pending.values():
        if slot.get("name"):
            yield {
                "type": "tool_call",
                "id": slot.get("id") or "",
                "name": slot["name"],
                "arguments": slot.get("arguments") or "",
            }

    yield {"type": "finish", "reason": finish_reason or "stop"}
