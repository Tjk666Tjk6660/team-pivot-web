from __future__ import annotations

import json

import pytest

from server.scoring.schema import (
    DIMENSIONS,
    SchemaError,
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
    out = parse_and_validate(_good_output(), index_data, expected_subject="zhangsan")
    assert len(out.scores) == 1
    s = out.scores[0]
    assert s.subject_pinyin == "zhangsan"
    assert s.overall == 4.2
    assert s.dimensions["delivery"] == 4.5
    assert s.dimensions["judgment"] is None
    assert len(s.evidence) == 3


def test_parse_strips_markdown_fence(index_data):
    raw = "```json\n" + _good_output() + "\n```"
    out = parse_and_validate(raw, index_data, expected_subject="zhangsan")
    assert len(out.scores) == 1


def test_parse_strips_plain_fence(index_data):
    raw = "```\n" + _good_output() + "\n```"
    out = parse_and_validate(raw, index_data, expected_subject="zhangsan")
    assert len(out.scores) == 1


def test_parse_empty_scores_with_skipped(index_data):
    """All-null skipped path is valid."""
    out = parse_and_validate(
        json.dumps({"scores": [], "skipped_subjects": ["zhangsan"]}),
        index_data,
        expected_subject="zhangsan",
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
        json.dumps(parsed_dict), index_data, expected_subject="zhangsan",
    )
    assert out.scores[0].evidence[0].source_filename.endswith("002_lisi_verify_xx.md")


# ---------- empty / malformed ----------


def test_parse_empty_string(index_data):
    with pytest.raises(SchemaError, match="empty"):
        parse_and_validate("", index_data, expected_subject="zhangsan")


def test_parse_invalid_json(index_data):
    with pytest.raises(SchemaError, match="json_invalid|pydantic_invalid"):
        parse_and_validate("not json at all", index_data, expected_subject="zhangsan")


def test_parse_missing_subject_pinyin_field(index_data):
    bad = json.dumps({
        "scores": [{
            "overall": 4.0, "confidence": "high",
            "rationale": "...", "dimensions": {}, "evidence": [_good_evidence()],
        }],
    })
    with pytest.raises(SchemaError, match="pydantic_invalid"):
        parse_and_validate(bad, index_data, expected_subject="zhangsan")


# ---------- subject must == owner ----------


def test_parse_rejects_wrong_subject(index_data):
    """AI scoring lisi instead of zhangsan → reject."""
    bad = _good_output()
    bad_dict = json.loads(bad)
    bad_dict["scores"][0]["subject_pinyin"] = "lisi"
    with pytest.raises(SchemaError, match="subject_not_owner"):
        parse_and_validate(
            json.dumps(bad_dict), index_data, expected_subject="zhangsan",
        )


# ---------- evidence anti-fabrication ----------


def test_parse_rejects_fabricated_filename(index_data):
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["evidence"][0]["source_filename"] = "999_fake.md"
    with pytest.raises(SchemaError, match="fabricated_source_filename"):
        parse_and_validate(
            json.dumps(bad_dict), index_data, expected_subject="zhangsan",
        )


# ---------- dimension/evidence consistency ----------


def test_parse_rejects_dimension_without_evidence(index_data):
    """dimensions.judgment=4 but no evidence with dimension=judgment → reject."""
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["dimensions"]["judgment"] = 4.0
    # evidence list still doesn't contain a judgment entry
    with pytest.raises(SchemaError, match="judgment.*no evidence"):
        parse_and_validate(
            json.dumps(bad_dict), index_data, expected_subject="zhangsan",
        )


def test_parse_rejects_dimension_score_out_of_range(index_data):
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["dimensions"]["delivery"] = 6.0
    with pytest.raises(SchemaError, match="out of"):
        parse_and_validate(
            json.dumps(bad_dict), index_data, expected_subject="zhangsan",
        )


def test_parse_rejects_unknown_dimension_key(index_data):
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["dimensions"]["bogus_dim"] = 3.0
    with pytest.raises(SchemaError, match="unknown dimension"):
        parse_and_validate(
            json.dumps(bad_dict), index_data, expected_subject="zhangsan",
        )


def test_parse_accepts_all_null_dimensions_with_evidence(index_data):
    """Edge: AI gave overall but all dimensions null. Schema still requires
    at least 1 evidence (pydantic), but no dimension-evidence linkage check
    fires when all dimensions are null."""
    bad_dict = json.loads(_good_output())
    for k in DIMENSIONS:
        bad_dict["scores"][0]["dimensions"][k] = None
    out = parse_and_validate(
        json.dumps(bad_dict), index_data, expected_subject="zhangsan",
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
            json.dumps(bad_dict), index_data, expected_subject="zhangsan",
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
            json.dumps(bad_dict), index_data, expected_subject="zhangsan",
        )


def test_parse_accepts_complete_comment_evidence(index_data):
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["evidence"][0].update({
        "source_kind": "comment",
        "source_comment_created_at": "2026-04-22T14:00:00+08:00",
        "source_comment_author": "lisi",
    })
    out = parse_and_validate(
        json.dumps(bad_dict), index_data, expected_subject="zhangsan",
    )
    assert out.scores[0].evidence[0].source_kind == "comment"


# ---------- enum + range guards (pydantic level) ----------


def test_parse_rejects_invalid_polarity(index_data):
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["evidence"][0]["polarity"] = "ambivalent"
    with pytest.raises(SchemaError, match="pydantic_invalid"):
        parse_and_validate(
            json.dumps(bad_dict), index_data, expected_subject="zhangsan",
        )


def test_parse_rejects_overall_out_of_range(index_data):
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["overall"] = 7.5
    with pytest.raises(SchemaError, match="pydantic_invalid"):
        parse_and_validate(
            json.dumps(bad_dict), index_data, expected_subject="zhangsan",
        )


def test_parse_rejects_more_than_one_score(index_data):
    """Decision A: scores list must have at most 1 entry."""
    two = json.dumps({
        "scores": [_good_score(), _good_score()],
        "skipped_subjects": [],
    })
    with pytest.raises(SchemaError, match="pydantic_invalid"):
        parse_and_validate(two, index_data, expected_subject="zhangsan")


def test_parse_rejects_evidence_without_quote(index_data):
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["evidence"][0]["quote"] = ""
    with pytest.raises(SchemaError, match="pydantic_invalid"):
        parse_and_validate(
            json.dumps(bad_dict), index_data, expected_subject="zhangsan",
        )


def test_parse_rejects_weight_out_of_range(index_data):
    bad_dict = json.loads(_good_output())
    bad_dict["scores"][0]["evidence"][0]["weight_applied"] = 99.0
    with pytest.raises(SchemaError, match="pydantic_invalid"):
        parse_and_validate(
            json.dumps(bad_dict), index_data, expected_subject="zhangsan",
        )
