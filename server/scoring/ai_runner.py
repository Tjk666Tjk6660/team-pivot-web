"""ScoringOutput → ScoreWrite/EvidenceWrite 适配器.

PR2 中只做"AI 输出 → store 写入"这一段适配；真正的端到端 orchestrator
（read index → build prompt → call AI → write store）放在 PR3 worker.py。

核心职责：
1. 把 AI 用的 pinyin 字段（subject_pinyin / source_comment_author）翻译成
   pivot_user.id（subject_user_id / source_comment_author_id）。
2. **服务端 override evidence.weight_applied** — AI 提示里有权重元信息，
   AI 应该会在 confidence/分数中体现，但 weight_applied 数值由我们用
   commenter weights 表权威生成，不信任 AI 自己填的。
3. 兜底失败：解析时 pinyin 解析不出 → 该证据 source_comment_author_id
   留 None（已离职 / pinyin 改名场景），不抛错。
"""
from __future__ import annotations

import logging

from server.scoring.prompt import WeightMap
from server.scoring.resolve import PinyinResolver
from server.scoring.schema import EvidenceItem, ScoringOutput, SubjectScore
from server.scoring.store import EvidenceWrite, ScoreWrite

log = logging.getLogger(__name__)


class AdaptError(Exception):
    """Raised when AI output cannot be adapted to store types — e.g. subject
    pinyin can't be resolved to a pivot_user.id (the matter.owner deleted
    between trigger and AI response, or pinyin rename collision)."""


def build_score_writes(
    parsed: ScoringOutput,
    *,
    resolver: PinyinResolver,
    weight_map: WeightMap,
) -> list[tuple[ScoreWrite, list[EvidenceWrite]]] | None:
    """Adapt ScoringOutput → list of (ScoreWrite, [EvidenceWrite]) per subject.

    v2.1 (Phase 2): returns a list (one entry per scored candidate). Phase 1
    callers that score a single subject get a 1-element list. Caller iterates
    and writes each to the store.

    Returns None if scores is empty (skipped_subjects path — caller marks
    run as success with 0 score rows).

    Raises AdaptError if any subject_pinyin can't be resolved to a user_id —
    treat as hard error (orphan subject) and fail the run; partial-write
    semantics aren't worth the complexity in v1.

    Notes:
    - weight_applied is server-authoritative: AI's value is ignored, we look
      up commenter weight by source_comment_author / source_annotation_author
      pinyin in weight_map.
    - source_*_author_id is None when pinyin can't be resolved
      (already-soft-deleted user / changed pinyin) — evidence still inserted.
    """
    if not parsed.scores:
        return None

    out: list[tuple[ScoreWrite, list[EvidenceWrite]]] = []
    for subj in parsed.scores:
        subject_user_id = resolver.resolve_id(subj.subject_pinyin)
        if subject_user_id is None:
            raise AdaptError(
                f"subject pinyin {subj.subject_pinyin!r} could not be resolved "
                "to pivot_user.id (deleted or never registered)"
            )
        score = _build_score(subj, subject_user_id=subject_user_id)
        evidence = [
            _build_evidence(e, resolver=resolver, weight_map=weight_map)
            for e in subj.evidence
        ]
        out.append((score, evidence))
    return out


def _build_score(subj: SubjectScore, *, subject_user_id: str) -> ScoreWrite:
    return ScoreWrite(
        subject_user_id=subject_user_id,
        overall=subj.overall,
        confidence=subj.confidence,
        rationale=subj.rationale,
        delivery=subj.dimensions.get("delivery"),
        accountability=subj.dimensions.get("accountability"),
        collaboration=subj.dimensions.get("collaboration"),
        judgment=subj.dimensions.get("judgment"),
        process=subj.dimensions.get("process"),
    )


def _build_evidence(
    e: EvidenceItem,
    *,
    resolver: PinyinResolver,
    weight_map: WeightMap,
) -> EvidenceWrite:
    # Resolve comment / annotation author pinyin → user_id (None if not
    # resolvable). v2.1: annotation joins comment as a kind that carries an
    # author pinyin; resolution + weight rules apply to both.
    comment_author_id: str | None = None
    annotation_author_id: str | None = None
    if e.source_kind == "comment" and e.source_comment_author:
        comment_author_id = resolver.resolve_id(e.source_comment_author)
        if comment_author_id is None:
            log.info(
                "evidence.source_comment_author %r could not be resolved "
                "(historical pinyin / soft-deleted) — keeping author_id=None",
                e.source_comment_author,
            )
    if e.source_kind == "annotation" and e.source_annotation_author:
        annotation_author_id = resolver.resolve_id(e.source_annotation_author)
        if annotation_author_id is None:
            log.info(
                "evidence.source_annotation_author %r could not be resolved "
                "(historical pinyin / soft-deleted) — keeping author_id=None",
                e.source_annotation_author,
            )

    # Server-authoritative weight: look up by author pinyin. comment AND
    # annotation share the commenter_weights table — high-weight contributors
    # carry the same multiplier whether they leave a comment or an annotation.
    # File-kind evidence is always 1.0 (no author-derived weight applies).
    weight = 1.0
    author_pinyin: str | None = None
    if e.source_kind == "comment":
        author_pinyin = e.source_comment_author
    elif e.source_kind == "annotation":
        author_pinyin = e.source_annotation_author
    if author_pinyin:
        info = weight_map.get(author_pinyin)
        if info is not None:
            weight = info[0]

    # Strip any path prefix the AI may have left in source_filename — the
    # store column wants the basename so it matches the timeline file name.
    filename = e.source_filename
    if "/" in filename:
        filename = filename.rsplit("/", 1)[-1]

    return EvidenceWrite(
        dimension=e.dimension,
        polarity=e.polarity,
        confidence=e.confidence,
        source_kind=e.source_kind,
        source_filename=filename,
        source_file_type=e.source_file_type,
        source_comment_created_at=e.source_comment_created_at,
        source_comment_author_id=comment_author_id,
        source_annotation_created_at=e.source_annotation_created_at,
        source_annotation_author_id=annotation_author_id,
        attribution_basis=e.attribution_basis,
        weight_applied=weight,
        quote=e.quote,
        explanation=e.explanation,
    )


def build_weight_map(
    weights: list,  # list[CommenterWeight]
    resolver: PinyinResolver,
) -> WeightMap:
    """Translate commenter_weights table rows (keyed by pivot_user.id) into
    the prompt's WeightMap (keyed by current pinyin).

    Users without a current pinyin (rare — needs_setup) are skipped:
    they can't be matched against git timeline pinyins anyway.
    """
    out: WeightMap = {}
    for w in weights:
        u = resolver.get_by_id(w.pivot_user_id)
        if u is None or not u.pinyin:
            log.info(
                "weight skipped: pivot_user %r not resolvable (deleted?)",
                w.pivot_user_id,
            )
            continue
        out[u.pinyin] = (w.weight, w.label)
    return out
