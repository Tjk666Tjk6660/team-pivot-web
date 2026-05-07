"""Scoring AI 输出的 pydantic 校验 + 反伪造检查.

AI 输出严格 JSON（详见 design §6 system prompt）。校验顺序：
  1. strip 可能的 markdown 代码块
  2. pydantic v2 model_validate_json — 类型 / 枚举 / 范围
  3. 业务规则：subject 必须落在 candidate_subjects 集合内、source_filename
     必须真实存在、每个非 null 维度至少 1 条 evidence、comment / annotation
     kind evidence 必须有 created_at + author、自我评价拒收（comment / file
     正向 / annotation 三路径）

校验失败抛 `SchemaError`；调用方（worker）将 raw output 一起记到 run.error 字段
里供 admin 排错。

Phase 2（v2.1）演进：
  - `ScoringOutput.scores` 不再硬限 ≤1，AI 可以一次输出多个 candidate 评分行
  - `parse_and_validate(candidate_subjects=...)` 取代 `expected_subject=...`，
    Phase 1 的 owner-only 模式只是"集合大小为 1 的特例"
  - `EvidenceItem.source_kind` 加 `"annotation"` 枚举值（v2.1 新来源类型，
    强语义评价证据）
  - 新增 `attribution_basis` 字段标注归因依据（005 决策链 + verify_outcome）

注意：weight_applied 字段在这里允许为任意 [0.1, 5.0] 浮点；真正的"该评论是否
属于高权重发言人"由 ai_runner.build_score_writes 服务端 override（避免 AI 篡改
权重值欺骗评分）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

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


class SelfEvaluationError(SchemaError):
    """Evidence violates the self-evaluation rule (matter 005 §6 决策链).

    Subclass so the worker can distinguish "AI tried to score self-eval" from
    other schema failures — for tuning prompt vs. tuning rules.
    """


# ---------- pydantic models ----------


class EvidenceItem(BaseModel):
    """One piece of evidence supporting a dimension score.

    The fields split into two layers (matter 003 §4 / 007 §1.3):

    **User original input** (immutable, pulled from timeline / annotation):
      `source_filename`, `source_file_type`, `source_file_creator`,
      `source_comment_*`, `source_annotation_*`, `quote`

    **AI-derived interpretation** (computed by AI per evidence):
      `dimension`, `polarity`, `confidence`, `attribution_basis`,
      `weight_applied`, `explanation`

    Downstream consumers must not mix these layers — admin override / audit
    trails should never present an AI-derived field as if the user typed it.
    """
    dimension: Literal["delivery", "accountability", "collaboration", "judgment", "process"]
    polarity: Literal["positive", "negative", "neutral"]
    confidence: Literal["low", "medium", "high"]
    # `annotation` (v2.1) is a separate kind from comment — different attribution
    # rules and a strong semantic-evidence signal. When source is missing, the
    # before-validator infers from metadata presence (annotation > comment > file).
    source_kind: Literal["file", "comment", "annotation"]
    source_filename: str = Field(min_length=1, max_length=500)
    source_file_type: str = Field(min_length=1, max_length=20)
    # Optional for backward compat — older AI runs predate this field. When
    # present, used to enforce "owner can't cite their own file as positive
    # evidence for themselves" (matter 005 决策链 §6 自我评价不入链).
    source_file_creator: str | None = Field(default=None, max_length=80)
    source_comment_created_at: str | None = Field(default=None, max_length=64)
    source_comment_author: str | None = Field(default=None, max_length=80)
    # v2.1 annotation evidence metadata — same shape as comment, separate
    # fields so source_kind can be unambiguously inferred even if the AI
    # omits it. Both must be present when source_kind=="annotation".
    source_annotation_created_at: str | None = Field(default=None, max_length=64)
    source_annotation_author: str | None = Field(default=None, max_length=80)
    # Why this evidence attaches to the subject. Optional for back-compat
    # with existing runs / older AI outputs that predate the field. When
    # present, populates `matter_score_evidence.attribution_basis` for the
    # admin EvidenceDialog "归因依据" column.
    #
    #   file_creator         默认归被评论文件作者（005 决策链兜底）
    #   explicit_mention     文本明确点名某人 → 归被点名者
    #   at_target            comment 的 mentions/targets 数组里 @ 了某人
    #   owner_change_reason  从 owner_change.reason 解析出对原 owner 的评价
    #   verify_outcome       005 §4 表里 "verify failed → 被验文件作者交付质量"
    attribution_basis: Literal[
        "file_creator",
        "explicit_mention",
        "at_target",
        "owner_change_reason",
        "verify_outcome",
    ] | None = Field(default=None)
    weight_applied: float = Field(default=1.0, ge=0.1, le=5.0)
    quote: str = Field(min_length=1, max_length=400)
    explanation: str = Field(min_length=1, max_length=400)

    @model_validator(mode="before")
    @classmethod
    def _infer_source_kind(cls, data: object) -> object:
        """Defensive: infer source_kind when AI omits it.

        Inference precedence: annotation > comment > file. Explicit
        source_kind from AI always wins. Reasoning:
          - annotation metadata present → it's an annotation
          - else if comment metadata present → it's a comment
          - else → it's a file
        Models occasionally drop source_kind on later evidence items even
        though the prompt schema lists it as mandatory. Rather than rejecting
        an otherwise valid response, we recover via this heuristic.
        """
        if not isinstance(data, dict):
            return data
        if data.get("source_kind"):
            return data
        has_annotation_meta = bool(
            str(data.get("source_annotation_created_at") or "").strip()
            or str(data.get("source_annotation_author") or "").strip()
        )
        if has_annotation_meta:
            return {**data, "source_kind": "annotation"}
        has_comment_meta = bool(
            str(data.get("source_comment_created_at") or "").strip()
            or str(data.get("source_comment_author") or "").strip()
        )
        return {
            **data,
            "source_kind": "comment" if has_comment_meta else "file",
        }


class SubjectScore(BaseModel):
    """One subject's full score with dimensions + evidence."""
    subject_pinyin: str = Field(min_length=1, max_length=80)
    overall: float = Field(ge=1.0, le=5.0)
    confidence: Literal["low", "medium", "high"]
    rationale: str = Field(min_length=1, max_length=600)
    dimensions: dict[str, float | None]
    evidence: list[EvidenceItem] = Field(min_length=1, max_length=50)


class ScoringOutput(BaseModel):
    """Top-level AI output shape.

    Phase 1 (v0.3) enforced `max_length=1` — decision A locked subject to
    matter.owner. Phase 2 (v2.1) drops that limit so the multi-subject
    candidate-set model can return one score per think/act creator.
    Per-subject identity is then validated against `candidate_subjects`
    (see `parse_and_validate`).
    """
    scores: list[SubjectScore] = Field(default_factory=list, max_length=20)
    skipped_subjects: list[str] = Field(default_factory=list)


# ---------- public entry ----------


def parse_and_validate(
    raw: str,
    index_data: dict,
    *,
    candidate_subjects: set[str],
) -> ScoringOutput:
    """Parse AI raw text → ScoringOutput, with business-rule validation.

    Raises SchemaError on any validation failure. The exception message is
    safe to put into matter_scoring_runs.error (no PII; no raw output).

    Args:
        raw: AI text output (may be wrapped in markdown ```json``` fences)
        index_data: matter index dict (used to validate source_filename)
        candidate_subjects: the set of pinyin allowed as `subject_pinyin` in
            scores. Phase 1 owner-only mode passes a 1-element set
            ({matter.owner}); Phase 2 multi-subject mode passes the set of
            think/act creators in the timeline. AI-output rows whose subject
            is outside this set are rejected as `subject_not_in_candidates`.
    """
    if not candidate_subjects:
        raise SchemaError("candidate_subjects cannot be empty")

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
    _validate_business_rules(parsed, candidate_subjects, valid_filenames)
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
    candidate_subjects: set[str],
    valid_filenames: set[str],
) -> None:
    """Apply rules that pydantic alone can't enforce.

    See design §1.1 (subject in candidates), §3.4 (evidence purity),
    §6 (硬约束), matter 005 §6 决策链 (no self-evaluation),
    v2.1 (annotation source_kind + self-eval extension).
    """
    seen: set[str] = set()
    for s in parsed.scores:
        if s.subject_pinyin not in candidate_subjects:
            raise SchemaError(
                f"subject_not_in_candidates: AI scored {s.subject_pinyin!r}, "
                f"expected one of {sorted(candidate_subjects)!r}"
            )
        if s.subject_pinyin in seen:
            raise SchemaError(
                f"duplicate_subject: {s.subject_pinyin!r} appears in scores "
                f"more than once — collapse evidence into a single row"
            )
        seen.add(s.subject_pinyin)
        _validate_dimensions_have_evidence(s)
        for e in s.evidence:
            _validate_evidence_source(e, valid_filenames)
            _validate_comment_evidence_completeness(e)
            _validate_annotation_evidence_completeness(e)
            _validate_no_self_evaluation(e, s.subject_pinyin)


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


def _validate_annotation_evidence_completeness(e: EvidenceItem) -> None:
    """Annotation-kind evidence must carry created_at + author (v2.1).

    annotation 写入端约定 author 由 server 注入，不允许 client 传，所以
    任何缺 author 的 annotation 必然是 AI 编造或客户端伪造，拒收。
    """
    if e.source_kind != "annotation":
        return
    if not e.source_annotation_created_at:
        raise SchemaError(
            f"annotation evidence missing source_annotation_created_at "
            f"({e.source_filename})"
        )
    if not e.source_annotation_author:
        raise SchemaError(
            f"annotation evidence missing source_annotation_author "
            f"({e.source_filename})"
        )


def _validate_no_self_evaluation(e: EvidenceItem, subject: str) -> None:
    """Reject evidence that is self-evaluation by the subject.

    Two paths per matter 005 §6 决策链 + v2.1 annotation extension:
      1. Comment authored by subject → reject (regardless of polarity)
      2. Annotation authored by subject → reject (regardless of polarity)

    File-level evidence is **never** rejected as self-eval, even when the
    file's creator is the subject. 005 §6 "评价者 == 文件作者 → 跳过" refers
    to a *commenter/evaluator* matching the file author, not the file itself.
    A subject's own think/act is a legitimate work product — AI may cite it
    as evidence (positive or negative) the same way it cites others'. Earlier
    revisions of this validator over-extended the rule to file-level positive
    evidence and frequently failed real runs (`run.error: self-evaluation
    rejected: positive evidence on file '...' authored by '...'`); the
    decision was reverted in v2.2 to match the source-of-truth design intent.
    """
    if e.source_kind == "comment" and e.source_comment_author == subject:
        raise SelfEvaluationError(
            f"self-evaluation rejected: comment by {subject!r} on "
            f"{e.source_filename!r} cannot be evidence for {subject!r}"
        )
    if e.source_kind == "annotation" and e.source_annotation_author == subject:
        raise SelfEvaluationError(
            f"self-evaluation rejected: annotation by {subject!r} on "
            f"{e.source_filename!r} cannot be evidence for {subject!r}"
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
