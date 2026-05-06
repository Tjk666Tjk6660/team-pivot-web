"""Unified call spec for every AI codepath in the server (方案 B).

Before this module each AI entry-point baked its own timeout / retry / error
behaviour:

  * api/ai.py:chat_matter     — 写死 read=120s（后被 0dd4852 改成 180s）；前端
                                 没有 inactivity 判定，连接静默时用户只能盯着 ▌ 闪
  * ai/oneshot.py             — `asyncio.wait_for(timeout_seconds=90)`
  * scoring/worker.py         — `KEY_TIMEOUT_SECONDS` 默认 120s
  * daily_report/...          — 同 oneshot

This file ties them together: every call now picks an `AICallSpec` (by
"purpose") that carries one canonical set of knobs:

  * soft_timeout_s        → 上游连续静默达到此阈值，发一条 heartbeat 事件，
                             前端把 "AI 助手" loading 状态升级为 "AI 响应较慢"
  * hard_timeout_s        → 上游连续静默达到此阈值 → 抛 AIError(retryable=True)
                             并立刻 close 连接，前端给"重试"按钮
  * heartbeat_interval_s  → SSE 心跳事件发送间隔（也是 client 检查空闲时长的
                             粒度，soft / hard 都按此粒度推进）

"重试"在本方案中**不由后端自动执行**——retryable=True 只是给前端"重试按钮
是否可点"一个信号；用户主动点击才会重新发起。这是 think 文档 §5.4 的明确决策。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Purpose buckets. Adding a new one is cheap — drop a row in DEFAULT_SPECS.
Purpose = Literal["chat", "summary", "scoring", "daily_report"]


@dataclass(frozen=True)
class AICallSpec:
    """Knobs for one AI invocation. All values are seconds.

    `soft_timeout_s` < `hard_timeout_s` is invariant — soft hits first and
    just nudges the UI; hard fires only if the upstream really stays silent.
    """
    purpose: Purpose
    soft_timeout_s: float
    hard_timeout_s: float
    heartbeat_interval_s: float

    def __post_init__(self) -> None:  # pragma: no cover - sanity only
        if self.soft_timeout_s <= 0 or self.hard_timeout_s <= 0:
            raise ValueError("timeouts must be positive")
        if self.soft_timeout_s > self.hard_timeout_s:
            raise ValueError("soft_timeout_s must be <= hard_timeout_s")
        if self.heartbeat_interval_s <= 0:
            raise ValueError("heartbeat_interval_s must be positive")


# Canonical defaults (see think 007 §5.4). These are "what the user feels
# acceptable" tuned for the OpenRouter / Claude latency profile we see today.
# Settings overrides can shift them per-deployment without redeploying code.
DEFAULT_SPECS: dict[Purpose, AICallSpec] = {
    "chat": AICallSpec(
        purpose="chat",
        soft_timeout_s=60.0,
        hard_timeout_s=180.0,
        heartbeat_interval_s=10.0,
    ),
    "summary": AICallSpec(
        purpose="summary",
        soft_timeout_s=20.0,
        hard_timeout_s=60.0,
        heartbeat_interval_s=5.0,
    ),
    "scoring": AICallSpec(
        purpose="scoring",
        # scoring is a non-interactive batch job — heartbeats only matter for
        # log liveness; tighter timeouts would just mean more failed runs.
        soft_timeout_s=60.0,
        hard_timeout_s=180.0,
        heartbeat_interval_s=15.0,
    ),
    "daily_report": AICallSpec(
        purpose="daily_report",
        soft_timeout_s=60.0,
        hard_timeout_s=180.0,
        heartbeat_interval_s=15.0,
    ),
}


def spec_for(purpose: Purpose) -> AICallSpec:
    """Return the canonical spec for a purpose. Future override hook: read
    from settings (`ai.<purpose>.soft_timeout_s` etc) — left out of v1 to
    keep the wire-up minimal."""
    return DEFAULT_SPECS[purpose]


# Stable error-code constants surfaced to the frontend. The frontend uses
# `code` to decide whether to show a "重试" button (retryable=True) and
# what user-facing message to render.
ERROR_CODE_AUTH = "auth"                 # 401 / 403 — bad key, do not retry
ERROR_CODE_RATE_LIMITED = "rate_limited" # 429 — backoff before retry
ERROR_CODE_UPSTREAM_5XX = "upstream_5xx" # 5xx — transient, retryable
ERROR_CODE_UPSTREAM_TIMEOUT = "upstream_timeout"  # hard_timeout_s 触发
ERROR_CODE_NETWORK = "network"           # connect error / DNS / etc
ERROR_CODE_PARSE = "parse_error"         # 上游返回的 JSON / SSE 损坏
ERROR_CODE_UNKNOWN = "unknown"           # fallback


# Default human-facing messages per code (zh-CN). These get wrapped into the
# {"error": {...}} SSE event and shown verbatim by AIPane.
USER_MESSAGE_ZH = {
    ERROR_CODE_AUTH: "AI 服务认证失败，请联系管理员检查 API Key 配置",
    ERROR_CODE_RATE_LIMITED: "AI 服务繁忙，请稍后重试",
    ERROR_CODE_UPSTREAM_5XX: "AI 上游异常，请重试",
    ERROR_CODE_UPSTREAM_TIMEOUT: "AI 没有响应，请重试",
    ERROR_CODE_NETWORK: "网络异常，无法连接 AI 服务，请稍后重试",
    ERROR_CODE_PARSE: "AI 返回格式异常，请重试",
    ERROR_CODE_UNKNOWN: "AI 调用失败，请稍后重试",
}


def is_retryable(code: str) -> bool:
    """Whether a given error code is worth offering a retry button for.

    `auth` and `parse_error` are non-retryable: hitting them again with the
    same input will produce the same error, so retry is just user-frustrating
    noise. Everything else is treated as transient by default.
    """
    return code not in (ERROR_CODE_AUTH, ERROR_CODE_PARSE)
