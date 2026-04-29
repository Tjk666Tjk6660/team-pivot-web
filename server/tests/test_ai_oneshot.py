"""Tests for `server.ai.oneshot.generate_text` — sync wrapper over stream_chat."""
from __future__ import annotations

import asyncio

import pytest

from server.ai import oneshot
from server.ai.client import AIError


# --------------------------------------------------------------------------- #
# helpers: build fake stream_chat coroutines / async generators               #
# --------------------------------------------------------------------------- #


def _make_fake_stream(events: list[dict]):
    """Build an async-generator-compatible fake `stream_chat` that yields
    the given events in order."""
    async def fake(*args, **kwargs):
        for ev in events:
            yield ev
    return fake


# --------------------------------------------------------------------------- #
# happy paths                                                                 #
# --------------------------------------------------------------------------- #


def test_aggregates_text_deltas(monkeypatch):
    """Multiple text deltas → concatenated into a single string."""
    monkeypatch.setattr(oneshot, "stream_chat", _make_fake_stream([
        {"type": "text", "delta": "hello "},
        {"type": "text", "delta": "world"},
        {"type": "finish", "reason": "stop"},
    ]))

    out = oneshot.generate_text(
        messages=[{"role": "user", "content": "hi"}],
        model="x", api_key="k", base_url="https://example.com/v1",
    )
    assert out == "hello world"


def test_ignores_tool_call_events(monkeypatch):
    """tool_call events are dropped — caller wanted a one-shot text response."""
    monkeypatch.setattr(oneshot, "stream_chat", _make_fake_stream([
        {"type": "text", "delta": "before"},
        {"type": "tool_call", "id": "t1", "name": "search", "arguments": "{}"},
        {"type": "text", "delta": " after"},
        {"type": "finish", "reason": "stop"},
    ]))

    out = oneshot.generate_text(
        messages=[], model="x", api_key="k", base_url="https://x",
    )
    assert out == "before after"


def test_empty_stream_returns_empty_string(monkeypatch):
    """No text deltas → empty string, not None / not error."""
    monkeypatch.setattr(oneshot, "stream_chat", _make_fake_stream([
        {"type": "finish", "reason": "stop"},
    ]))

    out = oneshot.generate_text(
        messages=[], model="x", api_key="k", base_url="https://x",
    )
    assert out == ""


def test_handles_none_or_missing_delta(monkeypatch):
    """Defensive: text events with empty/missing delta don't crash."""
    monkeypatch.setattr(oneshot, "stream_chat", _make_fake_stream([
        {"type": "text"},                # missing delta
        {"type": "text", "delta": None}, # null delta
        {"type": "text", "delta": "ok"},
        {"type": "finish", "reason": "stop"},
    ]))

    out = oneshot.generate_text(
        messages=[], model="x", api_key="k", base_url="https://x",
    )
    assert out == "ok"


# --------------------------------------------------------------------------- #
# error paths                                                                 #
# --------------------------------------------------------------------------- #


def test_propagates_aierror(monkeypatch):
    """AIError from the streaming layer (bad key / network) bubbles up.
    Caller (e.g., daily-report scorer) catches and decides how to degrade."""
    async def raising(*args, **kwargs):
        raise AIError("simulated upstream failure")
        yield  # never reached; makes this an async generator

    monkeypatch.setattr(oneshot, "stream_chat", raising)
    with pytest.raises(AIError, match="simulated"):
        oneshot.generate_text(
            messages=[], model="x", api_key="k", base_url="https://x",
        )


def test_timeout_raises(monkeypatch):
    """Stream that doesn't finish in time → TimeoutError. Caller can fall
    back to a stat-only report."""
    async def slow(*args, **kwargs):
        await asyncio.sleep(10)
        yield {"type": "text", "delta": "too late"}

    monkeypatch.setattr(oneshot, "stream_chat", slow)
    with pytest.raises((asyncio.TimeoutError, TimeoutError)):
        oneshot.generate_text(
            messages=[], model="x", api_key="k", base_url="https://x",
            timeout_seconds=0.05,
        )
