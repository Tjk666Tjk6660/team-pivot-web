from __future__ import annotations

import json

import pytest

from server.scoring.schema import (
    DIMENSIONS,
    SchemaError,
    SelfEvaluationError,
    parse_and_validate,
)


# ---------- fixtures ----------


@pytest.fixture
def index_data():
    """Minimal matter index with three timeline files."""
    return {
        "matter": {
            "id": "eng/auth-redesign",
            "title": "客户验收流程优化",
            "current_status": "finished",
            "owner": "zhangsan",
        },
        "timeline": [
            {"file": "discussions/eng/auth-redesign/001_zhangsan_act_xx.md", "type": "act"},
            {"file": "discussions/eng/auth-redesign/002_lisi_verify_xx.md", "type": "verify"},
            {"file": "discussions/eng/auth-redesign/003_zhangsan_result_xx.md", "type": "result"},
        ],
    }


def _good_evidence(**overrides):
    base = {
        "dimension": "delivery",
        "polarity": "positive",
        "confidence": "high",
        "source_kind": "file",
        "source_filename": "002_lisi_verify_xx.md",
        "source_file_type": "verify",
        "quote": "verify 通过：交付质量符合预期",
        "explanation": "lisi 在 verify 中确认交付质量",
    }
    base.update(overrides)
    return base


def _good_score(**overrides):
    base = {
        "subject_pinyin": "zhangsan",
        "overall": 4.2,
        "confidence": "high",
        "rationale": "负责的行动项按期完成",
        "dimensions": {
            "delivery": 4.5,
            "accountability": 4.0,
            "collaboration": None,
            "judgment": None,
            "process": 4.0,
        },
        "evidence": [
            _good_evidence(),
            _good_evidence(dimension="accountability", quote="按期完成", explanation="..."),
            _good_evidence(
                dimension="process",
                source_filename="003_zhangsan_result_xx.md",
                source_file_type="result",
                quote="result 文件齐全",
                explanation="...",
            ),
        ],
    }
    base.update(overrides)
    return base


def _good_output(**overrides):
    base = {"scores": [_good_score()], "skipped_subjects": []}
    base.update(overrides)
    return json.dumps(base, ensure_ascii=False)


# ---------- happy path ----------


def test_parse_valid_output(index_data):
    out = parse_and_validate(_good_output(), index_data, candidate_subjects={"zhangsan"})
    assert len(out.scores) == 1
    s = out.scores[0]
    assert s.subject_pinyin == "zhangsan"
    assert s.overall == 4.2
    assert s.dimensions["delivery"] == 4.5
    assert s.dimensions["judgment"] is None
    assert len(s.evidence) == 3


def test_parse_strips_markdown_fence(index_data):
    raw = "```json\n" + _good_output() + "\n```"
    out = parse_and_validate(raw, index_data, candidate_subjects={"zhangsan"})
    assert len(out.scores) == 1


def test_parse_strips_plain_fence(index_data):
    raw = "```\n" + _good_output() + "\n```"
    out = parse_and_validate(raw, index_data, candidate_subjects={"zhangsan"})
    assert len(out.scores) == 1


def test_parse_empty_scores_with_skipped(index_data):
    """All-null skipped path is valid."""
    out = parse_and_validate(
        json.dumps({"scores": [], "skipped_subjects": ["zhangsan"]}),
        index_data,
        candidate_subjects={"zhangsan"},
    )
    assert out.scores == []
    assert out.skipped_subjects == ["zhangsan"]


def test_parse_accepts_full_path_filename(index_data):
    """AI may return source_filename with discussions/ prefix; we accept it
    by matching basenames."""
    output = _good_output()
    parsed_dict = json.loads(output)
    parsed_dict["scores"][0]["evidence"][0]["source_filename"] = (
        "discussions/eng/auth-redesign/002_lisi_verify_xx.md"
    )
    out = parse_and_validate(
        json.dumps(parsed_dict), index_data, candidate_subjects={"zhangsan"},
    )
    assert out.scores[0].evidence[0].source_filename.endswith("002_lisi_verify_xx.md")


# ---------- empty / malformed ----------


def test_parse_empty_string(index_data):
    with pytest.raises(SchemaError, match="empty"):
        parse_and_validate("", index_data, candidate_subjects={"zhangsan"})


def test_parse_invalid_json(index_data):
    with pytest.raises(SchemaError, match="json_invalid|pydantic_invalid"):
        parse_and_validate("not json at all", index_data, candidate_subjects={"zhangsan"})


def test_parse_missing_subject_pinyin_field(index_data):
    bad = json.dumps({
        "scores": [{
            "overall": 4.0, "confidence": "high",
            "rationale": "...", "dimensions": {}, "evidence": [_good_evidence()],
        }],
    })
    with pytest.raises(SchemaError, match="pydantic_invalid"):
        parse_and_validate(bad, index_data, candidate_subjects={"zhangsan"})


# ---------- subject must == owner ----------


def test_parse_rejects_subject_not_in_candidates(index_data):
    """AI scores lisi but only zhangsan is a candidate → reject."""
    bad = _good_output()
    bad_dict = json.loads(bad)
    bad_dict["scores"][0]["subject_pinyin"] = "lisi"
    with pytest.raises(SchemaError, match="subject_not_in_candidates"):
        parse_and_validate(
            json.dumps(bad_dict), index_data, candidate_subjects={"zhangsan"},
        )


def test_parse_accepts_subject_in_multi_candidate_set(index_data):
    """Phase 2: AI scores lisi when both zhangsan and lisi are candidates → ok."""
    bad = _good_output()
    bad_dict = json.loads(bad)
    bad_dict["scores"][0]["subject_pinyin"] = "lisi"
    out = parse_and_validate(
        json.dumps(bad_dict),
        index_data,
        candidate_subjects={"zhangsan", "lisi"},
    )
    assert out.scores[0].subject_pinyin == "lisi"


def test_parse_rejects_empty_candidate_set(index_data):
    """Empty candidate set is a programmer error — refuse to validate."""
    with pytest.raises(SchemaError, match="candidate_subjects cannot be empty"):
        parse_and_validate(_good_output(), index_data, candidate_subjects=set())


# ---------- evidence anti-fabrication ----------


def test_parse_rejects_fabricated_filename(index_data):
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["evidence"][0]["source_filename"] = "999_fake.md"
    with pytest.raises(SchemaError, match="fabricated_source_filename"):
        parse_and_validate(
            json.dumps(bad_dict), index_data, candidate_subjects={"zhangsan"},
        )


# ---------- dimension/evidence consistency ----------


def test_parse_rejects_dimension_without_evidence(index_data):
    """dimensions.judgment=4 but no evidence with dimension=judgment → reject."""
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["dimensions"]["judgment"] = 4.0
    # evidence list still doesn't contain a judgment entry
    with pytest.raises(SchemaError, match="judgment.*no evidence"):
        parse_and_validate(
            json.dumps(bad_dict), index_data, candidate_subjects={"zhangsan"},
        )


def test_parse_rejects_dimension_score_out_of_range(index_data):
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["dimensions"]["delivery"] = 6.0
    with pytest.raises(SchemaError, match="out of"):
        parse_and_validate(
            json.dumps(bad_dict), index_data, candidate_subjects={"zhangsan"},
        )


def test_parse_rejects_unknown_dimension_key(index_data):
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["dimensions"]["bogus_dim"] = 3.0
    with pytest.raises(SchemaError, match="unknown dimension"):
        parse_and_validate(
            json.dumps(bad_dict), index_data, candidate_subjects={"zhangsan"},
        )


def test_parse_accepts_all_null_dimensions_with_evidence(index_data):
    """Edge: AI gave overall but all dimensions null. Schema still requires
    at least 1 evidence (pydantic), but no dimension-evidence linkage check
    fires when all dimensions are null."""
    bad_dict = json.loads(_good_output())
    for k in DIMENSIONS:
        bad_dict["scores"][0]["dimensions"][k] = None
    out = parse_and_validate(
        json.dumps(bad_dict), index_data, candidate_subjects={"zhangsan"},
    )
    assert all(out.scores[0].dimensions[k] is None for k in DIMENSIONS)


# ---------- comment evidence completeness ----------


def test_parse_rejects_comment_without_created_at(index_data):
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["evidence"][0].update({
        "source_kind": "comment",
        "source_comment_created_at": None,
        "source_comment_author": "lisi",
    })
    with pytest.raises(SchemaError, match="created_at"):
        parse_and_validate(
            json.dumps(bad_dict), index_data, candidate_subjects={"zhangsan"},
        )


def test_parse_rejects_comment_without_author(index_data):
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["evidence"][0].update({
        "source_kind": "comment",
        "source_comment_created_at": "2026-04-22T14:00:00+08:00",
        "source_comment_author": None,
    })
    with pytest.raises(SchemaError, match="author"):
        parse_and_validate(
            json.dumps(bad_dict), index_data, candidate_subjects={"zhangsan"},
        )


def test_parse_accepts_complete_comment_evidence(index_data):
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["evidence"][0].update({
        "source_kind": "comment",
        "source_comment_created_at": "2026-04-22T14:00:00+08:00",
        "source_comment_author": "lisi",
    })
    out = parse_and_validate(
        json.dumps(bad_dict), index_data, candidate_subjects={"zhangsan"},
    )
    assert out.scores[0].evidence[0].source_kind == "comment"


# ---------- source_kind inference (defensive against AI omissions) ----------


def test_parse_infers_file_when_source_kind_missing(index_data):
    """AI sometimes drops source_kind on later items — infer from absence
    of comment metadata."""
    bad_dict = json.loads(_good_output())
    del bad_dict["scores"][0]["evidence"][0]["source_kind"]
    out = parse_and_validate(
        json.dumps(bad_dict), index_data, candidate_subjects={"zhangsan"},
    )
    assert out.scores[0].evidence[0].source_kind == "file"


def test_parse_infers_comment_when_comment_meta_present(index_data):
    """source_kind missing + comment fields present → infer 'comment'."""
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["evidence"][0].update({
        "source_comment_created_at": "2026-04-22T14:00:00+08:00",
        "source_comment_author": "lisi",
    })
    bad_dict["scores"][0]["evidence"][0].pop("source_kind", None)
    out = parse_and_validate(
        json.dumps(bad_dict), index_data, candidate_subjects={"zhangsan"},
    )
    assert out.scores[0].evidence[0].source_kind == "comment"


def test_parse_explicit_source_kind_overrides_inference(index_data):
    """If AI explicitly sets source_kind, trust it even if heuristic disagrees.

    (Edge case: AI sets source_kind='file' but also fills comment fields —
    we trust AI's explicit declaration. The downstream completeness check
    will still catch genuinely malformed records.)"""
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["evidence"][0]["source_kind"] = "file"
    out = parse_and_validate(
        json.dumps(bad_dict), index_data, candidate_subjects={"zhangsan"},
    )
    assert out.scores[0].evidence[0].source_kind == "file"


def test_parse_inferred_comment_still_validates_completeness(index_data):
    """If we infer 'comment' from one comment field but the other is missing,
    the comment-completeness check should still reject it."""
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["evidence"][0].update({
        # Only set author, not created_at — incomplete
        "source_comment_author": "lisi",
    })
    bad_dict["scores"][0]["evidence"][0].pop("source_kind", None)
    # Inferred source_kind=comment (because author is set), then
    # _validate_comment_evidence_completeness should reject due to missing
    # created_at.
    with pytest.raises(SchemaError, match="created_at"):
        parse_and_validate(
            json.dumps(bad_dict), index_data, candidate_subjects={"zhangsan"},
        )


# ---------- enum + range guards (pydantic level) ----------


def test_parse_rejects_invalid_polarity(index_data):
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["evidence"][0]["polarity"] = "ambivalent"
    with pytest.raises(SchemaError, match="pydantic_invalid"):
        parse_and_validate(
            json.dumps(bad_dict), index_data, candidate_subjects={"zhangsan"},
        )


def test_parse_rejects_overall_out_of_range(index_data):
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["overall"] = 7.5
    with pytest.raises(SchemaError, match="pydantic_invalid"):
        parse_and_validate(
            json.dumps(bad_dict), index_data, candidate_subjects={"zhangsan"},
        )


def test_parse_accepts_multiple_scores_for_distinct_subjects(index_data):
    """Phase 2 (v2.1): scores list can have N entries when N candidates."""
    second = _good_score(subject_pinyin="lisi")
    two = json.dumps({
        "scores": [_good_score(), second],
        "skipped_subjects": [],
    })
    out = parse_and_validate(
        two, index_data, candidate_subjects={"zhangsan", "lisi"},
    )
    assert len(out.scores) == 2
    assert {s.subject_pinyin for s in out.scores} == {"zhangsan", "lisi"}


def test_parse_rejects_duplicate_subject_in_scores(index_data):
    """Same subject must not appear twice — AI should collapse evidence."""
    two = json.dumps({
        "scores": [_good_score(), _good_score()],  # both zhangsan
        "skipped_subjects": [],
    })
    with pytest.raises(SchemaError, match="duplicate_subject"):
        parse_and_validate(two, index_data, candidate_subjects={"zhangsan"})


def test_parse_rejects_evidence_without_quote(index_data):
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["evidence"][0]["quote"] = ""
    with pytest.raises(SchemaError, match="pydantic_invalid"):
        parse_and_validate(
            json.dumps(bad_dict), index_data, candidate_subjects={"zhangsan"},
        )


def test_parse_rejects_weight_out_of_range(index_data):
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["evidence"][0]["weight_applied"] = 99.0
    with pytest.raises(SchemaError, match="pydantic_invalid"):
        parse_and_validate(
            json.dumps(bad_dict), index_data, candidate_subjects={"zhangsan"},
        )


# ---------- self-evaluation rejection (matter 005 §6 决策链) ----------


def test_self_evaluation_error_is_schema_error_subclass():
    """Worker code catches SchemaError; SelfEvaluationError must inherit so
    the broader except still works while letting callers narrow when needed."""
    assert issubclass(SelfEvaluationError, SchemaError)


def test_parse_rejects_self_comment_evidence(index_data):
    """Comment authored by subject on any file → cannot be subject's evidence."""
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["evidence"][0].update({
        "source_kind": "comment",
        "source_filename": "001_zhangsan_act_xx.md",
        "source_file_type": "act",
        "source_comment_created_at": "2026-04-22T14:00:00+08:00",
        "source_comment_author": "zhangsan",  # ← subject 自己写的评论
    })
    with pytest.raises(SelfEvaluationError, match="self-evaluation"):
        parse_and_validate(
            json.dumps(bad_dict), index_data, candidate_subjects={"zhangsan"},
        )


def test_parse_accepts_self_authored_file_evidence_positive(index_data):
    """v2.2: subject's own think / act file as POSITIVE evidence is allowed.

    The file is a work product, not a self-comment. AI may legitimately cite
    a subject's act as positive delivery evidence (especially when paired
    with a verify pass). Earlier revisions over-extended 005's "评价者 ==
    文件作者 → 跳过" rule to the file itself; reverted because real runs
    consistently failed with `self-evaluation rejected: positive evidence on
    file '...' authored by '...'` even though the AI's reasoning was sound.
    """
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["evidence"][0].update({
        "source_kind": "file",
        "source_filename": "001_zhangsan_act_xx.md",
        "source_file_type": "act",
        "source_file_creator": "zhangsan",  # ← subject's own act
        "polarity": "positive",
    })
    out = parse_and_validate(
        json.dumps(bad_dict), index_data, candidate_subjects={"zhangsan"},
    )
    assert out.scores[0].evidence[0].source_file_creator == "zhangsan"
    assert out.scores[0].evidence[0].polarity == "positive"


def test_parse_accepts_self_authored_file_evidence_negative(index_data):
    """Negative evidence on subject's own file also allowed (always was)."""
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["evidence"] = [
        _good_evidence(
            source_kind="file",
            source_filename="001_zhangsan_act_xx.md",
            source_file_type="act",
            source_file_creator="zhangsan",
            polarity="negative",
            dimension="judgment",
        ),
    ]
    bad_dict["scores"][0]["dimensions"] = {
        "delivery": None,
        "accountability": None,
        "collaboration": None,
        "judgment": 2.0,
        "process": None,
    }
    out = parse_and_validate(
        json.dumps(bad_dict), index_data, candidate_subjects={"zhangsan"},
    )
    assert out.scores[0].dimensions["judgment"] == 2.0


def test_parse_accepts_evidence_without_source_file_creator(index_data):
    """Backward compat: source_file_creator is optional. Older AI runs that
    don't emit this field must still parse cleanly."""
    bad_dict = json.loads(_good_output())
    # _good_output already omits source_file_creator — verify the happy path
    assert "source_file_creator" not in bad_dict["scores"][0]["evidence"][0]
    out = parse_and_validate(
        json.dumps(bad_dict), index_data, candidate_subjects={"zhangsan"},
    )
    assert len(out.scores) == 1
    # Field defaulted to None
    assert out.scores[0].evidence[0].source_file_creator is None


def test_parse_accepts_other_authored_file_evidence(index_data):
    """Positive evidence on a file authored by someone OTHER than subject is fine."""
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["evidence"][0].update({
        "source_kind": "file",
        "source_filename": "002_lisi_verify_xx.md",
        "source_file_type": "verify",
        "source_file_creator": "lisi",  # ← lisi 验收 zhangsan 的 act
        "polarity": "positive",
    })
    out = parse_and_validate(
        json.dumps(bad_dict), index_data, candidate_subjects={"zhangsan"},
    )
    assert out.scores[0].evidence[0].source_file_creator == "lisi"


def test_parse_accepts_other_authored_comment_evidence(index_data):
    """Comment by someone OTHER than subject is fine."""
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["evidence"][0].update({
        "source_kind": "comment",
        "source_filename": "001_zhangsan_act_xx.md",
        "source_file_type": "act",
        "source_comment_created_at": "2026-04-22T14:00:00+08:00",
        "source_comment_author": "lisi",  # ← lisi 评 zhangsan 的工作
    })
    out = parse_and_validate(
        json.dumps(bad_dict), index_data, candidate_subjects={"zhangsan"},
    )
    assert out.scores[0].evidence[0].source_comment_author == "lisi"


# ---------- v2.1: annotation source_kind ----------


def test_parse_accepts_annotation_evidence(index_data):
    """v2.1: source_kind=annotation with full metadata is a valid path."""
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["evidence"][0].update({
        "source_kind": "annotation",
        "source_filename": "001_zhangsan_act_xx.md",
        "source_file_type": "act",
        "source_annotation_created_at": "2026-04-22T14:00:00+08:00",
        "source_annotation_author": "dengke",
        "attribution_basis": "file_creator",
    })
    out = parse_and_validate(
        json.dumps(bad_dict), index_data, candidate_subjects={"zhangsan"},
    )
    e = out.scores[0].evidence[0]
    assert e.source_kind == "annotation"
    assert e.source_annotation_author == "dengke"
    assert e.attribution_basis == "file_creator"


def test_parse_rejects_annotation_without_created_at(index_data):
    """v2.1: annotation evidence must carry created_at (analogous to comment)."""
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["evidence"][0].update({
        "source_kind": "annotation",
        "source_annotation_created_at": None,
        "source_annotation_author": "dengke",
    })
    with pytest.raises(SchemaError, match="annotation.*created_at"):
        parse_and_validate(
            json.dumps(bad_dict), index_data, candidate_subjects={"zhangsan"},
        )


def test_parse_rejects_annotation_without_author(index_data):
    """v2.1: annotation evidence must carry author."""
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["evidence"][0].update({
        "source_kind": "annotation",
        "source_annotation_created_at": "2026-04-22T14:00:00+08:00",
        "source_annotation_author": None,
    })
    with pytest.raises(SchemaError, match="annotation.*author"):
        parse_and_validate(
            json.dumps(bad_dict), index_data, candidate_subjects={"zhangsan"},
        )


def test_parse_rejects_self_annotation(index_data):
    """v2.1: annotation by subject on any file → rejected (any polarity).

    Mirror of the comment self-eval rule. Even subject's *negative*
    annotation on their own file is rejected — this is by design, since
    annotation is a conscious evaluative statement (unlike negative file
    evidence that derives from structural mismatch)."""
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["evidence"][0].update({
        "source_kind": "annotation",
        "source_filename": "001_zhangsan_act_xx.md",
        "source_file_type": "act",
        "source_annotation_created_at": "2026-04-22T14:00:00+08:00",
        "source_annotation_author": "zhangsan",  # ← subject 自己写的 annotation
    })
    with pytest.raises(SelfEvaluationError, match="self-evaluation.*annotation"):
        parse_and_validate(
            json.dumps(bad_dict), index_data, candidate_subjects={"zhangsan"},
        )


def test_parse_rejects_self_annotation_negative(index_data):
    """Self-annotation rejection is polarity-agnostic (unlike file-evidence)."""
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["evidence"][0].update({
        "source_kind": "annotation",
        "polarity": "negative",
        "source_annotation_created_at": "2026-04-22T14:00:00+08:00",
        "source_annotation_author": "zhangsan",
    })
    with pytest.raises(SelfEvaluationError, match="annotation.*zhangsan"):
        parse_and_validate(
            json.dumps(bad_dict), index_data, candidate_subjects={"zhangsan"},
        )


def test_parse_infers_annotation_from_metadata(index_data):
    """source_kind missing + annotation fields present → infer 'annotation'."""
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["evidence"][0].update({
        "source_annotation_created_at": "2026-04-22T14:00:00+08:00",
        "source_annotation_author": "dengke",
    })
    bad_dict["scores"][0]["evidence"][0].pop("source_kind", None)
    out = parse_and_validate(
        json.dumps(bad_dict), index_data, candidate_subjects={"zhangsan"},
    )
    assert out.scores[0].evidence[0].source_kind == "annotation"


# ---------- v2.1: attribution_basis ----------


def test_parse_accepts_attribution_basis_values(index_data):
    """All five attribution_basis enum values pass."""
    for basis in (
        "file_creator",
        "explicit_mention",
        "at_target",
        "owner_change_reason",
        "verify_outcome",
    ):
        bad_dict = json.loads(_good_output())
        bad_dict["scores"][0]["evidence"][0]["attribution_basis"] = basis
        out = parse_and_validate(
            json.dumps(bad_dict), index_data, candidate_subjects={"zhangsan"},
        )
        assert out.scores[0].evidence[0].attribution_basis == basis


def test_parse_accepts_evidence_without_attribution_basis(index_data):
    """Backward compat: attribution_basis is optional. Older runs / models
    without it must still parse. Phase 2 prompt encourages but does not
    schema-require it (yet — store layer will eventually enforce)."""
    bad_dict = json.loads(_good_output())
    assert "attribution_basis" not in bad_dict["scores"][0]["evidence"][0]
    out = parse_and_validate(
        json.dumps(bad_dict), index_data, candidate_subjects={"zhangsan"},
    )
    assert out.scores[0].evidence[0].attribution_basis is None


def test_parse_rejects_unknown_attribution_basis(index_data):
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["evidence"][0]["attribution_basis"] = "made_up"
    with pytest.raises(SchemaError, match="pydantic_invalid"):
        parse_and_validate(
            json.dumps(bad_dict), index_data, candidate_subjects={"zhangsan"},
        )
