from __future__ import annotations

import asyncio
import json
import logging
import time
from urllib.parse import urlparse
from typing import AsyncIterator

import httpx

from server.ai.runner import (
    AICallSpec,
    ERROR_CODE_AUTH,
    ERROR_CODE_NETWORK,
    ERROR_CODE_PARSE,
    ERROR_CODE_RATE_LIMITED,
    ERROR_CODE_UNKNOWN,
    ERROR_CODE_UPSTREAM_5XX,
    ERROR_CODE_UPSTREAM_TIMEOUT,
    USER_MESSAGE_ZH,
    is_retryable,
    spec_for,
)

log = logging.getLogger("server.ai.client")

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "anthropic/claude-sonnet-4-5"


class AIError(Exception):
    """Unified AI failure.

    Backward-compatible: legacy callers `raise AIError("msg")` still work,
    `str(e)` still returns the message, isinstance checks still match. New
    callers add metadata via kwargs:

        raise AIError("upstream 502", code="upstream_5xx", retryable=True, status=502)

    Frontend-visible fields:
        code         — stable identifier for branching UI (see runner.py)
        retryable    — whether to offer a "重试" button
        user_message_zh — Chinese message to display (defaults from code lookup)
        status       — original HTTP status if applicable, for diagnostics
    """

    def __init__(
        self,
        message: str = "",
        *,
        code: str = ERROR_CODE_UNKNOWN,
        retryable: bool | None = None,
        user_message_zh: str | None = None,
        status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable if retryable is not None else is_retryable(code)
        self.user_message_zh = user_message_zh or USER_MESSAGE_ZH.get(
            code, USER_MESSAGE_ZH[ERROR_CODE_UNKNOWN]
        )
        self.status = status

    def to_event_payload(self) -> dict:
        """Shape used by the SSE `error` event the frontend listens to."""
        return {
            "code": self.code,
            "retryable": self.retryable,
            "message": self.user_message_zh,
            "status": self.status,
        }


# Sentinel: connect timeout stays small (we want to fail fast on bad networks),
# but read timeout is governed by AICallSpec.hard_timeout_s instead of a
# single hard cap. The httpx Timeout(read=...) is set generously and the real
# enforcement happens via asyncio.wait_for inside the read loop.
_CONNECT_TIMEOUT_S = 10.0


async def stream_chat(
    messages: list[dict],
    model: str,
    api_key: str,
    base_url: str,
    tools: list[dict] | None = None,
    *,
    spec: AICallSpec | None = None,
    timeout_read_seconds: float | None = None,
) -> AsyncIterator[dict]:
    """
    Stream a single turn from an OpenAI-compatible endpoint.

    Yields structured events so the caller can drive the tool-use loop:

        {"type": "text", "delta": "..."}              # visible token
        {"type": "tool_call", "id": "...",
         "name": "...", "arguments": "<json-string>"} # complete tool call
        {"type": "heartbeat",                         # NEW (方案 B)
         "since_last_token_ms": int}                  # upstream silent N ms
        {"type": "finish", "reason": "stop|tool_calls|length|..."}

    On `hard_timeout_s` (or unrecoverable upstream errors) raises AIError —
    callers should `try/except AIError` and surface `e.to_event_payload()`
    to the frontend as the SSE `error` event.

    Parameters:
        spec:                  AICallSpec to use (purpose-bucketed timeouts).
                               Default: spec_for("chat").
        timeout_read_seconds:  LEGACY. If given, overrides spec.hard_timeout_s.
                               Kept so existing callers (scoring) don't break.

    The caller is responsible for:
      - Streaming text deltas to the frontend.
      - Forwarding heartbeat events to the frontend (so it can show "AI 响应较慢").
      - Dispatching tool_calls, appending assistant+tool messages, and
        invoking stream_chat again for the next turn.
    """
    spec = spec or spec_for("chat")
    hard_timeout = (
        timeout_read_seconds if timeout_read_seconds is not None
        else spec.hard_timeout_s
    )
    heartbeat_interval = min(spec.heartbeat_interval_s, hard_timeout)

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

    # httpx read timeout is set well above hard_timeout so it never preempts
    # our own asyncio.wait_for-based control. Connect timeout stays small.
    httpx_read_buffer_s = hard_timeout + 30.0

    # Skip system / env proxies when the upstream is on the loopback interface
    # (dev mocks, sidecars). Local proxy clients (Clash / v2ray / etc) on
    # Windows commonly intercept `http://localhost:*` traffic and 404 it,
    # which surfaced as a parse_error during real-flow validation. Hitting
    # a real OpenRouter endpoint over the public internet still respects
    # the user's proxy because that's where it usually lives.
    is_loopback_upstream = hostname in ("localhost", "127.0.0.1", "::1")

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(_CONNECT_TIMEOUT_S, read=httpx_read_buffer_s),
            trust_env=not is_loopback_upstream,
        ) as client:
            async with client.stream(
                "POST",
                f"{base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    raise _classify_http_error(resp.status_code, body)

                async for ev in _iter_with_heartbeat(
                    resp, heartbeat_interval, hard_timeout, pending,
                ):
                    if ev is _SENTINEL_FINISHED:
                        break
                    if isinstance(ev, _FinishMarker):
                        finish_reason = ev.reason
                        continue
                    yield ev
    except AIError:
        raise
    except (asyncio.TimeoutError, httpx.ReadTimeout, httpx.WriteTimeout) as e:
        raise AIError(
            f"upstream timeout: {e!s}",
            code=ERROR_CODE_UPSTREAM_TIMEOUT,
        ) from e
    except (httpx.ConnectError, httpx.ConnectTimeout) as e:
        raise AIError(
            f"connect failure: {e!s}",
            code=ERROR_CODE_NETWORK,
        ) from e
    except httpx.HTTPError as e:
        raise AIError(
            f"transport error: {e!s}",
            code=ERROR_CODE_NETWORK,
        ) from e

    # Tool calls fully assembled: emit them once the stream is drained.
    for slot in pending.values():
        if slot.get("name"):
            yield {
                "type": "tool_call",
                "id": slot.get("id") or "",
                "name": slot["name"],
                "arguments": slot.get("arguments") or "",
            }

    yield {"type": "finish", "reason": finish_reason or "stop"}


# ---------- internals ----------------------------------------------------


_SENTINEL_FINISHED = object()


class _FinishMarker:
    __slots__ = ("reason",)

    def __init__(self, reason: str | None) -> None:
        self.reason = reason


async def _iter_with_heartbeat(
    resp: httpx.Response,
    heartbeat_interval_s: float,
    hard_timeout_s: float,
    pending_tool_calls: dict[int, dict],
) -> AsyncIterator[object]:
    """Consume `resp.aiter_lines()` with two timers:

      * if no line arrives within `heartbeat_interval_s`, emit a heartbeat
        event and keep waiting;
      * if total silence reaches `hard_timeout_s`, raise AIError.

    Forwards parsed events to the caller. Yields a `_FinishMarker` when the
    upstream sends a finish_reason (caller stores it for the final yield)
    and a `_SENTINEL_FINISHED` when we receive `data: [DONE]`.

    Implementation note (the trap we hit during 方案 B real-flow validation):
        `asyncio.wait_for(line_iter.__anext__(), timeout=...)` does NOT play
        well with async generators — on timeout it CANCELS the inner
        coroutine, which destroys the generator's frame, and the next call
        to `__anext__()` raises StopAsyncIteration immediately. That made
        the very first heartbeat event silently terminate the upstream
        stream. We instead launch `__anext__()` as a Task and use
        `asyncio.wait(..., timeout=...)` to peek at it without cancelling
        on timeout — when timeout fires the Task stays alive and we
        re-await it on the next iteration.
    """
    line_iter = resp.aiter_lines()
    last_event_at = time.monotonic()
    next_line_task: asyncio.Task | None = None

    try:
        while True:
            if next_line_task is None:
                next_line_task = asyncio.ensure_future(line_iter.__anext__())

            done, _ = await asyncio.wait(
                {next_line_task},
                timeout=heartbeat_interval_s,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                # Heartbeat path: leave next_line_task running, fire a
                # heartbeat event, and loop back to wait again.
                elapsed = time.monotonic() - last_event_at
                if elapsed >= hard_timeout_s:
                    raise AIError(
                        f"upstream silent for {elapsed:.0f}s (hard_timeout={hard_timeout_s:.0f}s)",
                        code=ERROR_CODE_UPSTREAM_TIMEOUT,
                    )
                yield {
                    "type": "heartbeat",
                    "since_last_token_ms": int(elapsed * 1000),
                }
                continue

            # next_line_task completed — pick up its result and reset the slot.
            try:
                line = next_line_task.result()
            except StopAsyncIteration:
                next_line_task = None
                return
            finally:
                # Whether success or StopAsyncIteration, the task is consumed;
                # null the slot so the next iteration creates a fresh one.
                next_line_task = None

            # We received a line — reset the silence timer regardless of whether
            # the line is meaningful (could be an SSE keep-alive blank).
            last_event_at = time.monotonic()

            if not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                yield _SENTINEL_FINISHED
                return
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
                yield _FinishMarker(fr)

            text = delta.get("content")
            if text:
                yield {"type": "text", "delta": text}

            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index", 0)
                slot = pending_tool_calls.setdefault(
                    idx, {"id": "", "name": "", "arguments": ""}
                )
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["name"] = fn["name"]
                if fn.get("arguments"):
                    slot["arguments"] += fn["arguments"]
    finally:
        # Crucial cleanup: if we exit the loop early (AIError raised, generator
        # closed by caller, etc.), the in-flight __anext__ task is still
        # pending. Cancel it so the underlying httpx response stream is
        # released — without this, leftover tasks accumulate and httpx logs
        # warnings about un-awaited coroutines.
        if next_line_task is not None and not next_line_task.done():
            next_line_task.cancel()
            try:
                await next_line_task
            except (asyncio.CancelledError, StopAsyncIteration, Exception):
                pass


def _classify_http_error(status_code: int, body: bytes) -> AIError:
    """Map an HTTP error response to a typed AIError. Body is included in
    the message for diagnostics but the user-facing message comes from the
    canonical code → text table in runner.py.
    """
    body_preview = ""
    try:
        body_preview = body.decode()[:300]
    except Exception:  # pragma: no cover
        body_preview = repr(body[:300])

    if status_code in (401, 403):
        code = ERROR_CODE_AUTH
    elif status_code == 429:
        code = ERROR_CODE_RATE_LIMITED
    elif 500 <= status_code < 600:
        code = ERROR_CODE_UPSTREAM_5XX
    elif 400 <= status_code < 500:
        # Other 4xx — treat as parse/contract issue (model not found, bad
        # request, etc). Not retryable from the user's side.
        code = ERROR_CODE_PARSE
    else:
        code = ERROR_CODE_UNKNOWN

    return AIError(
        f"AI endpoint {status_code}: {body_preview}",
        code=code,
        status=status_code,
    )
