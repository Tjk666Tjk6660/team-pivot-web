"""Scoring AI 输出的 pydantic 校验 + 反伪造检查.

AI 输出严格 JSON（详见 design §6 system prompt）。校验顺序：
  1. strip 可能的 markdown 代码块
  2. pydantic v2 model_validate_json — 类型 / 枚举 / 范围
  3. 业务规则：subject 必须 = owner、source_filename 必须真实存在、
     每个非 null 维度至少 1 条 evidence、comment-kind evidence 必须有
     created_at + author

校验失败抛 `SchemaError`；调用方（worker）将 raw output 一起记到 run.error 字段
里供 admin 排错。

注意：weight_applied 字段在这里允许为任意 [0.1, 5.0] 浮点；真正的"该评论是否
属于高权重发言人"由 ai_runner.build_score_writes 服务端 override（避免 AI 篡改
权重值欺骗评分）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

# Re-export commonly used dimension list for prompt + tests
DIMENSIONS = ("delivery", "accountability", "collaboration", "judgment", "process")

# §3.2 weights (used for overall computation by AI; we don't recompute server-side
# in v1 — design P2 says language layer can adjust ±0.5, so server-side recompute
# would diverge from AI's intent; we trust AI's overall and only reject extremes)
DIMENSION_WEIGHTS: dict[str, float] = {
    "delivery": 0.30,
    "accountability": 0.25,
    "judgment": 0.20,
    "collaboration": 0.15,
    "process": 0.10,
}


class SchemaError(Exception):
    """AI output failed pydantic or business-rule validation."""


# ---------- pydantic models ----------


class EvidenceItem(BaseModel):
    """One piece of evidence supporting a dimension score."""
    dimension: Literal["delivery", "accountability", "collaboration", "judgment", "process"]
    polarity: Literal["positive", "negative", "neutral"]
    confidence: Literal["low", "medium", "high"]
    source_kind: Literal["file", "comment"]
    source_filename: str = Field(min_length=1, max_length=500)
    source_file_type: str = Field(min_length=1, max_length=20)
    source_comment_created_at: str | None = Field(default=None, max_length=64)
    source_comment_author: str | None = Field(default=None, max_length=80)
    weight_applied: float = Field(default=1.0, ge=0.1, le=5.0)
    quote: str = Field(min_length=1, max_length=400)
    explanation: str = Field(min_length=1, max_length=400)


class SubjectScore(BaseModel):
    """One subject's full score with dimensions + evidence."""
    subject_pinyin: str = Field(min_length=1, max_length=80)
    overall: float = Field(ge=1.0, le=5.0)
    confidence: Literal["low", "medium", "high"]
    rationale: str = Field(min_length=1, max_length=600)
    dimensions: dict[str, float | None]
    evidence: list[EvidenceItem] = Field(min_length=1, max_length=50)


class ScoringOutput(BaseModel):
    """Top-level AI output shape. v0.3 enforces ≤1 score (decision A)."""
    scores: list[SubjectScore] = Field(default_factory=list, max_length=1)
    skipped_subjects: list[str] = Field(default_factory=list)


# ---------- public entry ----------


def parse_and_validate(
    raw: str,
    index_data: dict,
    *,
    expected_subject: str,
) -> ScoringOutput:
    """Parse AI raw text → ScoringOutput, with business-rule validation.

    Raises SchemaError on any validation failure. The exception message is
    safe to put into matter_scoring_runs.error (no PII; no raw output).

    Args:
        raw: AI text output (may be wrapped in markdown ```json``` fences)
        index_data: matter index dict (used to validate source_filename)
        expected_subject: the subject_pinyin that must appear if scores is
                          non-empty (= matter.owner pinyin per decision A)
    """
    text = _strip_code_fences(raw or "").strip()
    if not text:
        raise SchemaError("empty AI response")

    try:
        parsed = ScoringOutput.model_validate_json(text)
    except ValidationError as e:
        # Compact summary — full error blob would dwarf run.error
        raise SchemaError(f"pydantic_invalid: {_summarize_validation_error(e)}") from e
    except json.JSONDecodeError as e:
        raise SchemaError(f"json_invalid: {e.msg}") from e

    valid_filenames = _collect_filenames(index_data)
    _validate_business_rules(parsed, expected_subject, valid_filenames)
    return parsed


# ---------- internals ----------


_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _strip_code_fences(s: str) -> str:
    """Remove a ```json ... ``` (or plain ``` ... ```) wrapper if present."""
    m = _CODE_FENCE_RE.search(s)
    if m:
        return m.group(1)
    return s


def _collect_filenames(index_data: dict) -> set[str]:
    """Return basenames of all files appearing in timeline."""
    out: set[str] = set()
    for item in (index_data.get("timeline") or []):
        f = item.get("file") or ""
        if not f:
            continue
        out.add(Path(f).name)
    return out


def _validate_business_rules(
    parsed: ScoringOutput,
    expected_subject: str,
    valid_filenames: set[str],
) -> None:
    """Apply rules that pydantic alone can't enforce.

    See design §1.1 (subject = owner), §3.4 (evidence purity), §6 (硬约束).
    """
    for s in parsed.scores:
        if s.subject_pinyin != expected_subject:
            raise SchemaError(
                f"subject_not_owner: AI scored {s.subject_pinyin!r}, "
                f"expected matter.owner = {expected_subject!r}"
            )
        _validate_dimensions_have_evidence(s)
        for e in s.evidence:
            _validate_evidence_source(e, valid_filenames)
            _validate_comment_evidence_completeness(e)


def _validate_dimensions_have_evidence(s: SubjectScore) -> None:
    """Each non-null dimension score requires ≥1 evidence pointing to it."""
    for dim in DIMENSIONS:
        score = s.dimensions.get(dim)
        if score is None:
            continue
        if not (1.0 <= score <= 5.0):
            raise SchemaError(
                f"{s.subject_pinyin}.dimensions.{dim}={score} out of [1.0, 5.0]"
            )
        has = any(e.dimension == dim for e in s.evidence)
        if not has:
            raise SchemaError(
                f"{s.subject_pinyin}.{dim} scored {score} but no evidence "
                f"references this dimension"
            )
    # Reject unknown dimension keys that aren't in DIMENSIONS — defends against
    # AI inventing new categories.
    extra = set(s.dimensions.keys()) - set(DIMENSIONS)
    if extra:
        raise SchemaError(
            f"{s.subject_pinyin}: unknown dimension keys {sorted(extra)}"
        )


def _validate_evidence_source(e: EvidenceItem, valid_filenames: set[str]) -> None:
    """source_filename must reference a real timeline file (反伪造)."""
    # Accept both basename and full path forms; normalize to basename
    name = Path(e.source_filename).name
    if name not in valid_filenames:
        raise SchemaError(
            f"fabricated_source_filename: {e.source_filename!r} "
            f"is not in matter timeline"
        )


def _validate_comment_evidence_completeness(e: EvidenceItem) -> None:
    """Comment-kind evidence must carry created_at + author (for回链)."""
    if e.source_kind != "comment":
        return
    if not e.source_comment_created_at:
        raise SchemaError(
            f"comment evidence missing source_comment_created_at "
            f"({e.source_filename})"
        )
    if not e.source_comment_author:
        raise SchemaError(
            f"comment evidence missing source_comment_author "
            f"({e.source_filename})"
        )


def _summarize_validation_error(e: ValidationError) -> str:
    """One-line summary of a pydantic ValidationError suitable for run.error."""
    errors = e.errors()
    if not errors:
        return str(e)[:200]
    head = errors[0]
    loc = ".".join(str(p) for p in head.get("loc", ()))
    msg = head.get("msg", "")
    extra = "" if len(errors) <= 1 else f" (+{len(errors) - 1} more)"
    return f"{loc}: {msg}{extra}"[:300]
