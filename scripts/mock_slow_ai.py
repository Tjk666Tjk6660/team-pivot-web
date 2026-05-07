"""Mock OpenAI-compatible AI endpoint for validating 方案 B's heartbeat /
hard-timeout / error-detail SSE behaviour without paying real OpenRouter
calls or depending on its weather.

Run:
    python scripts/mock_slow_ai.py --port 9100 --mode <mode>

Modes:
    fast        — token every 50ms, finish in ~1s (control case)
    slow        — silent for 12s after a single greeting token, then finish
                  (validates server-side heartbeat fires + frontend slow banner)
    stalled     — silent forever (server-side hard_timeout_s should fire,
                  yielding a structured error event and retryable=true UI)
    auth        — return 401 immediately (validates retryable=false UI)
    server_5xx  — return 503 on first request (validates retryable=true UI
                  with code='upstream_5xx')

Wire it in via the workspace Admin → AI settings:
    Base URL: http://localhost:9100/v1
    API Key:  any-non-empty-string
    Model:    test/mock
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

log = logging.getLogger("mock_slow_ai")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


def make_app(mode: str) -> FastAPI:
    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        log.info("incoming chat request mode=%s", mode)

        if mode == "auth":
            return JSONResponse(
                status_code=401,
                content={"error": {"message": "Invalid API key (mock)", "type": "auth"}},
            )

        if mode == "server_5xx":
            return JSONResponse(
                status_code=503,
                content={"error": {"message": "Upstream unavailable (mock)"}},
            )

        async def generate() -> AsyncIterator[str]:
            async for chunk in _stream(mode):
                yield chunk

        return StreamingResponse(generate(), media_type="text/event-stream")

    return app


async def _stream(mode: str) -> AsyncIterator[str]:
    """Build SSE chunks in the OpenAI streaming wire format."""

    def chunk(content: str | None, finish: str | None = None) -> str:
        delta: dict = {}
        if content is not None:
            delta["content"] = content
        choice: dict = {"index": 0, "delta": delta}
        if finish:
            choice["finish_reason"] = finish
        payload = {
            "id": f"mock-{int(time.time() * 1000)}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": "test/mock",
            "choices": [choice],
        }
        return f"data: {json.dumps(payload)}\n\n"

    if mode == "fast":
        for word in ["你好", "，", "我", "正", "在", "正常", "回复", "。"]:
            yield chunk(word)
            await asyncio.sleep(0.05)
        yield chunk(None, finish="stop")
        yield "data: [DONE]\n\n"
        return

    if mode == "slow":
        # One greeting token, then a 12s gap (server heartbeat_interval_s
        # default for chat = 10s, so frontend should see ≥1 heartbeat),
        # then resume.
        yield chunk("（")
        await asyncio.sleep(12.0)
        yield chunk("我醒了！")
        await asyncio.sleep(0.1)
        yield chunk("）")
        yield chunk(None, finish="stop")
        yield "data: [DONE]\n\n"
        return

    if mode == "stalled":
        # No tokens, ever. Server-side hard_timeout_s should fire and
        # close the upstream from our side. We just sleep until the client
        # disconnects (httpx.ReadTimeout on their end → AIError on ours).
        try:
            while True:
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            return
        return

    raise ValueError(f"unknown mode: {mode}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=9100)
    p.add_argument(
        "--mode",
        choices=["fast", "slow", "stalled", "auth", "server_5xx"],
        default="fast",
    )
    args = p.parse_args()
    log.info("mock AI listening :%d mode=%s", args.port, args.mode)

    import uvicorn
    uvicorn.run(make_app(args.mode), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
