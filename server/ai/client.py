from __future__ import annotations

import json
import logging
from typing import AsyncIterator

import httpx

log = logging.getLogger("server.ai.client")

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "anthropic/claude-sonnet-4-5"


class AIError(Exception):
    pass


async def stream_chat(
    messages: list[dict],
    model: str,
    api_key: str,
) -> AsyncIterator[str]:
    """Yield text deltas from OpenRouter (OpenAI-compatible streaming)."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://team-pivot-web",
        "X-Title": "team-pivot-web",
    }
    payload = {"model": model, "messages": messages, "stream": True}

    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=120.0)) as client:
        async with client.stream(
            "POST",
            f"{OPENROUTER_BASE}/chat/completions",
            headers=headers,
            json=payload,
        ) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                raise AIError(f"OpenRouter {resp.status_code}: {body.decode()[:300]}")
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    return
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0]["delta"].get("content") or ""
                    if delta:
                        yield delta
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
