from __future__ import annotations

import json

import pytest

from server.db import Database
from server.pivot_users import PivotUserRepo
from server.scoring.ai_runner import AdaptError, build_score_writes, build_weight_map
from server.scoring.resolve import PinyinResolver
from server.scoring.schema import parse_and_validate
from server.scoring.store import CommenterWeight, ScoringStore


# ---------- fixtures ----------


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.db")


@pytest.fixture
def users(db):
    return PivotUserRepo(db)


@pytest.fixture
def resolver(db):
    return PinyinResolver(db)


@pytest.fixture
def store(db):
    return ScoringStore(db)


@pytest.fixture
def index_data():
    return {
        "matter": {"id": "m", "title": "t", "current_status": "finished", "owner": "zhangsan"},
        "timeline": [
            {"file": "discussions/x/m/001_zhangsan_act_xx.md", "type": "act"},
            {"file": "discussions/x/m/002_lisi_verify_xx.md", "type": "verify"},
        ],
    }


def _output(**overrides):
    base = {
        "scores": [{
            "subject_pinyin": "zhangsan",
            "overall": 4.2,
            "confidence": "high",
            "rationale": "...",
            "dimensions": {
                "delivery": 4.5,
                "accountability": 4.0,
                "collaboration": None,
                "judgment": None,
                "process": None,
            },
            "evidence": [
                {
                    "dimension": "delivery", "polarity": "positive", "confidence": "high",
                    "source_kind": "file",
                    "source_filename": "002_lisi_verify_xx.md",
                    "source_file_type": "verify",
                    "quote": "verify 通过",
                    "explanation": "lisi 验收",
                    "weight_applied": 1.0,
                },
                {
                    "dimension": "accountability", "polarity": "positive", "confidence": "high",
                    "source_kind": "comment",
                    "source_filename": "001_zhangsan_act_xx.md",
                    "source_file_type": "act",
                    "source_comment_created_at": "2026-04-21T16:00:00+08:00",
                    "source_comment_author": "wangwu",
                    "quote": "已经补救",
                    "explanation": "wangwu 评论佐证",
                    "weight_applied": 1.0,
                },
            ],
        }],
        "skipped_subjects": [],
    }
    base.update(overrides)
    return json.dumps(base, ensure_ascii=False)


# ---------- build_score_writes ----------


def test_build_score_writes_basic(resolver, index_data):
    parsed = parse_and_validate(_output(), index_data, expected_subject="zhangsan")
    result = build_score_writes(parsed, resolver=resolver, weight_map={})
    assert result is not None
    score, evidence = result
    assert score.overall == 4.2
    assert score.delivery == 4.5
    assert score.accountability == 4.0
    assert score.judgment is None
    assert len(evidence) == 2


def test_build_score_writes_returns_none_for_skipped(resolver, index_data):
    raw = json.dumps({"scores": [], "skipped_subjects": ["zhangsan"]})
    parsed = parse_and_validate(raw, index_data, expected_subject="zhangsan")
    result = build_score_writes(parsed, resolver=resolver, weight_map={})
    assert result is None


def test_build_score_writes_resolves_comment_author(resolver, users, index_data):
    """When a comment author pinyin maps to a real user, store author_id."""
    wangwu = users.create(
        display_name="王五", pinyin="wangwu", email=None, avatar_url="",
    )
    parsed = parse_and_validate(_output(), index_data, expected_subject="zhangsan")
    _, evidence = build_score_writes(parsed, resolver=resolver, weight_map={})
    # Find the comment-kind evidence
    comment_e = next(e for e in evidence if e.source_kind == "comment")
    assert comment_e.source_comment_author_id == wangwu.id


def test_build_score_writes_unresolvable_author_keeps_none(resolver, index_data):
    """Unresolvable comment author (deleted user / pinyin renamed) → None,
    NOT an error."""
    parsed = parse_and_validate(_output(), index_data, expected_subject="zhangsan")
    _, evidence = build_score_writes(parsed, resolver=resolver, weight_map={})
    comment_e = next(e for e in evidence if e.source_kind == "comment")
    assert comment_e.source_comment_author_id is None


def test_build_score_writes_applies_weight_for_high_weight_commenter(
    resolver, index_data,
):
    """When a comment author is in weight_map, weight_applied set to that weight."""
    weight_map = {"wangwu": (1.5, "技术负责人")}
    parsed = parse_and_validate(_output(), index_data, expected_subject="zhangsan")
    _, evidence = build_score_writes(
        parsed, resolver=resolver, weight_map=weight_map,
    )
    comment_e = next(e for e in evidence if e.source_kind == "comment")
    assert comment_e.weight_applied == 1.5


def test_build_score_writes_overrides_ai_supplied_weight(resolver, index_data):
    """Even if AI sets weight_applied=99, server-side authoritative value wins."""
    raw_dict = json.loads(_output())
    raw_dict["scores"][0]["evidence"][1]["weight_applied"] = 4.5  # AI lying
    raw = json.dumps(raw_dict)
    parsed = parse_and_validate(raw, index_data, expected_subject="zhangsan")
    # weight_map empty → must default to 1.0, ignoring AI's 4.5
    _, evidence = build_score_writes(parsed, resolver=resolver, weight_map={})
    comment_e = next(e for e in evidence if e.source_kind == "comment")
    assert comment_e.weight_applied == 1.0


def test_build_score_writes_file_evidence_weight_always_1(resolver, index_data):
    """File-kind evidence has no commenter; weight stays 1.0 regardless."""
    weight_map = {"lisi": (1.5, "CTO")}  # Even if lisi is weighted
    parsed = parse_and_validate(_output(), index_data, expected_subject="zhangsan")
    _, evidence = build_score_writes(
        parsed, resolver=resolver, weight_map=weight_map,
    )
    file_e = next(e for e in evidence if e.source_kind == "file")
    assert file_e.weight_applied == 1.0


def test_build_score_writes_strips_path_from_filename(resolver, index_data):
    """AI may return source_filename with full path; we store just basename."""
    raw_dict = json.loads(_output())
    raw_dict["scores"][0]["evidence"][0]["source_filename"] = (
        "discussions/x/m/002_lisi_verify_xx.md"
    )
    parsed = parse_and_validate(json.dumps(raw_dict), index_data, expected_subject="zhangsan")
    _, evidence = build_score_writes(parsed, resolver=resolver, weight_map={})
    assert evidence[0].source_filename == "002_lisi_verify_xx.md"


# ---------- build_weight_map ----------


def test_build_weight_map_translates_to_pinyin(resolver, users, store):
    ceo = users.create(display_name="CEO", pinyin="ceo", email=None, avatar_url="")
    cto = users.create(display_name="CTO", pinyin="cto", email=None, avatar_url="")
    admin = users.create(display_name="Adm", pinyin="adm", email=None, avatar_url="")
    store.upsert_weight(
        pivot_user_id=ceo.id, weight=2.0, label="CEO", note=None, updated_by=admin.id,
    )
    store.upsert_weight(
        pivot_user_id=cto.id, weight=1.5, label="CTO", note=None, updated_by=admin.id,
    )

    weights = store.list_weights()
    weight_map = build_weight_map(weights, resolver)

    assert weight_map["ceo"] == (2.0, "CEO")
    assert weight_map["cto"] == (1.5, "CTO")
    assert "adm" not in weight_map  # admin isn't a weighted commenter


def test_build_weight_map_skips_users_without_pinyin(resolver, users, store):
    """User with no pinyin (didn't finish profile setup) — skip them."""
    no_pinyin = users.create(
        display_name="X", pinyin=None, email="x@example.com", avatar_url="",
    )
    admin = users.create(display_name="A", pinyin="a", email=None, avatar_url="")
    store.upsert_weight(
        pivot_user_id=no_pinyin.id, weight=2.0, label="?",
        note=None, updated_by=admin.id,
    )

    weights = store.list_weights()
    weight_map = build_weight_map(weights, resolver)
    assert weight_map == {}


def test_build_weight_map_skips_dangling_user_id(resolver, store):
    """Weight row referring to a deleted-from-DB user_id (shouldn't happen,
    but defend against it)."""
    weights = [
        CommenterWeight(
            pivot_user_id="not_a_real_id",
            weight=2.0, label="ghost", note=None,
            updated_at=0.0, updated_by="x",
        ),
    ]
    weight_map = build_weight_map(weights, resolver)
    assert weight_map == {}


def test_build_score_writes_invariant_max_one_score(resolver, index_data):
    """Defense in depth — even though pydantic enforces it, AdaptError raises
    when scores has unexpected length. We can't easily test this through
    parse_and_validate (it would reject first), so we synthesize a parsed
    object directly."""
    from server.scoring.schema import EvidenceItem, ScoringOutput, SubjectScore
    s1 = SubjectScore(
        subject_pinyin="x", overall=4.0, confidence="high",
        rationale="...", dimensions={"delivery": 4.0},
        evidence=[EvidenceItem(
            dimension="delivery", polarity="positive", confidence="high",
            source_kind="file", source_filename="a.md", source_file_type="verify",
            quote="...", explanation="...",
        )],
    )
    # Bypass pydantic max_length=1 by directly constructing
    out = ScoringOutput.model_construct(scores=[s1, s1], skipped_subjects=[])
    with pytest.raises(AdaptError, match="length"):
        build_score_writes(out, resolver=resolver, weight_map={})
