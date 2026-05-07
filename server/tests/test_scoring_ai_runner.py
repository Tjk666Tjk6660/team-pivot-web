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


@pytest.fixture(autouse=True)
def zhangsan(users):
    """v2.1: build_score_writes resolves subject pinyin → user_id, so all
    happy-path tests need a registered zhangsan in the pivot_users table.
    autouse so individual tests don't need to declare the fixture."""
    return users.create(
        display_name="张三", pinyin="zhangsan", email=None, avatar_url="",
    )


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
    parsed = parse_and_validate(_output(), index_data, candidate_subjects={"zhangsan"})
    result = build_score_writes(parsed, resolver=resolver, weight_map={})
    assert result is not None
    assert len(result) == 1
    score, evidence = result[0]
    assert score.overall == 4.2
    assert score.delivery == 4.5
    assert score.accountability == 4.0
    assert score.judgment is None
    assert len(evidence) == 2


def test_build_score_writes_returns_none_for_skipped(resolver, index_data):
    raw = json.dumps({"scores": [], "skipped_subjects": ["zhangsan"]})
    parsed = parse_and_validate(raw, index_data, candidate_subjects={"zhangsan"})
    result = build_score_writes(parsed, resolver=resolver, weight_map={})
    assert result is None


def test_build_score_writes_resolves_comment_author(resolver, users, index_data):
    """When a comment author pinyin maps to a real user, store author_id."""
    wangwu = users.create(
        display_name="王五", pinyin="wangwu", email=None, avatar_url="",
    )
    parsed = parse_and_validate(_output(), index_data, candidate_subjects={"zhangsan"})
    [(_, evidence)] = build_score_writes(parsed, resolver=resolver, weight_map={})
    # Find the comment-kind evidence
    comment_e = next(e for e in evidence if e.source_kind == "comment")
    assert comment_e.source_comment_author_id == wangwu.id


def test_build_score_writes_unresolvable_author_keeps_none(resolver, index_data):
    """Unresolvable comment author (deleted user / pinyin renamed) → None,
    NOT an error."""
    parsed = parse_and_validate(_output(), index_data, candidate_subjects={"zhangsan"})
    [(_, evidence)] = build_score_writes(parsed, resolver=resolver, weight_map={})
    comment_e = next(e for e in evidence if e.source_kind == "comment")
    assert comment_e.source_comment_author_id is None


def test_build_score_writes_applies_weight_for_high_weight_commenter(
    resolver, index_data,
):
    """When a comment author is in weight_map, weight_applied set to that weight."""
    weight_map = {"wangwu": (1.5, "技术负责人")}
    parsed = parse_and_validate(_output(), index_data, candidate_subjects={"zhangsan"})
    [(_, evidence)] = build_score_writes(
        parsed, resolver=resolver, weight_map=weight_map,
    )
    comment_e = next(e for e in evidence if e.source_kind == "comment")
    assert comment_e.weight_applied == 1.5


def test_build_score_writes_overrides_ai_supplied_weight(resolver, index_data):
    """Even if AI sets weight_applied=99, server-side authoritative value wins."""
    raw_dict = json.loads(_output())
    raw_dict["scores"][0]["evidence"][1]["weight_applied"] = 4.5  # AI lying
    raw = json.dumps(raw_dict)
    parsed = parse_and_validate(raw, index_data, candidate_subjects={"zhangsan"})
    # weight_map empty → must default to 1.0, ignoring AI's 4.5
    [(_, evidence)] = build_score_writes(parsed, resolver=resolver, weight_map={})
    comment_e = next(e for e in evidence if e.source_kind == "comment")
    assert comment_e.weight_applied == 1.0


def test_build_score_writes_file_evidence_weight_always_1(resolver, index_data):
    """File-kind evidence has no commenter; weight stays 1.0 regardless."""
    weight_map = {"lisi": (1.5, "CTO")}  # Even if lisi is weighted
    parsed = parse_and_validate(_output(), index_data, candidate_subjects={"zhangsan"})
    [(_, evidence)] = build_score_writes(
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
    parsed = parse_and_validate(json.dumps(raw_dict), index_data, candidate_subjects={"zhangsan"})
    [(_, evidence)] = build_score_writes(parsed, resolver=resolver, weight_map={})
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


def test_build_score_writes_resolves_annotation_author(resolver, users, index_data):
    """v2.1: annotation author pinyin is resolved to user_id, mirroring comments."""
    dengke = users.create(
        display_name="邓柯", pinyin="dengke", email=None, avatar_url="",
    )
    raw = json.dumps({
        "scores": [{
            "subject_pinyin": "zhangsan",
            "overall": 4.0,
            "confidence": "high",
            "rationale": "...",
            "dimensions": {"delivery": 4.0},
            "evidence": [{
                "dimension": "delivery", "polarity": "positive", "confidence": "high",
                "source_kind": "annotation",
                "source_filename": "001_zhangsan_act_xx.md",
                "source_file_type": "act",
                "source_annotation_created_at": "2026-04-22T14:00:00+08:00",
                "source_annotation_author": "dengke",
                "attribution_basis": "file_creator",
                "quote": "判断很准",
                "explanation": "annotation 评价",
                "weight_applied": 1.0,
            }],
        }],
        "skipped_subjects": [],
    })
    parsed = parse_and_validate(raw, index_data, candidate_subjects={"zhangsan"})
    result = build_score_writes(parsed, resolver=resolver, weight_map={})
    assert result is not None
    [(_, evidence)] = result
    e = evidence[0]
    assert e.source_kind == "annotation"
    assert e.source_annotation_author_id == dengke.id
    assert e.source_annotation_created_at == "2026-04-22T14:00:00+08:00"
    assert e.attribution_basis == "file_creator"
    assert e.source_comment_author_id is None  # comment fields stay NULL


def test_build_score_writes_applies_weight_to_annotation_author(
    resolver, users, store, index_data,
):
    """v2.1: high-weight commenters carry the same multiplier on annotations
    as on comments. The weight_map is keyed by author pinyin regardless of
    source_kind."""
    ceo = users.create(display_name="CEO", pinyin="ceo", email=None, avatar_url="")
    admin = users.create(display_name="A", pinyin="a", email=None, avatar_url="")
    store.upsert_weight(
        pivot_user_id=ceo.id, weight=2.0, label="CEO",
        note=None, updated_by=admin.id,
    )
    weight_map = build_weight_map(store.list_weights(), resolver)

    raw = json.dumps({
        "scores": [{
            "subject_pinyin": "zhangsan",
            "overall": 4.5,
            "confidence": "high",
            "rationale": "...",
            "dimensions": {"delivery": 4.5},
            "evidence": [{
                "dimension": "delivery", "polarity": "positive", "confidence": "high",
                "source_kind": "annotation",
                "source_filename": "001_zhangsan_act_xx.md",
                "source_file_type": "act",
                "source_annotation_created_at": "2026-04-22T14:00:00+08:00",
                "source_annotation_author": "ceo",
                "attribution_basis": "file_creator",
                "quote": "case 很好",
                "explanation": "ceo annotation",
                "weight_applied": 1.0,
            }],
        }],
        "skipped_subjects": [],
    })
    parsed = parse_and_validate(raw, index_data, candidate_subjects={"zhangsan"})
    result = build_score_writes(parsed, resolver=resolver, weight_map=weight_map)
    assert result is not None
    [(_, evidence)] = result
    # CEO weight 2.0x applied to annotation evidence (server-authoritative)
    assert evidence[0].weight_applied == 2.0


def test_build_score_writes_passes_through_attribution_basis(resolver, index_data):
    """attribution_basis from EvidenceItem reaches EvidenceWrite verbatim."""
    raw = json.dumps({
        "scores": [{
            "subject_pinyin": "zhangsan",
            "overall": 3.0,
            "confidence": "medium",
            "rationale": "...",
            "dimensions": {"delivery": 3.0},
            "evidence": [{
                "dimension": "delivery", "polarity": "negative", "confidence": "medium",
                "source_kind": "file",
                "source_filename": "002_lisi_verify_xx.md",
                "source_file_type": "verify",
                "attribution_basis": "verify_outcome",
                "quote": "verify failed",
                "explanation": "...",
                "weight_applied": 1.0,
            }],
        }],
        "skipped_subjects": [],
    })
    parsed = parse_and_validate(raw, index_data, candidate_subjects={"zhangsan"})
    result = build_score_writes(parsed, resolver=resolver, weight_map={})
    assert result is not None
    [(_, evidence)] = result
    assert evidence[0].attribution_basis == "verify_outcome"


def test_build_score_writes_rejects_unresolvable_subject(resolver, index_data):
    """v2.1: build_score_writes proactively resolves each subject pinyin.
    An unknown pinyin (not in pivot_users) is a hard failure — orphan
    subject would land bad data; admin should re-trigger after the user
    is provisioned."""
    from server.scoring.schema import EvidenceItem, ScoringOutput, SubjectScore
    s = SubjectScore(
        subject_pinyin="ghost_user", overall=4.0, confidence="high",
        rationale="...", dimensions={"delivery": 4.0},
        evidence=[EvidenceItem(
            dimension="delivery", polarity="positive", confidence="high",
            source_kind="file", source_filename="a.md", source_file_type="verify",
            quote="...", explanation="...",
        )],
    )
    out = ScoringOutput.model_construct(scores=[s], skipped_subjects=[])
    with pytest.raises(AdaptError, match="ghost_user.*could not be resolved"):
        build_score_writes(out, resolver=resolver, weight_map={})


def test_build_score_writes_handles_multi_subject(resolver, users, index_data):
    """v2.1 (Task 2.4): adapter handles N-subject AI output, returns N pairs."""
    lisi = users.create(display_name="李四", pinyin="lisi", email=None, avatar_url="")
    raw = json.dumps({
        "scores": [
            {
                "subject_pinyin": "zhangsan",
                "overall": 4.2, "confidence": "high",
                "rationale": "owner perspective",
                "dimensions": {"delivery": 4.5},
                "evidence": [{
                    "dimension": "delivery", "polarity": "positive",
                    "confidence": "high", "source_kind": "file",
                    "source_filename": "002_lisi_verify_xx.md",
                    "source_file_type": "verify",
                    "quote": "verify pass", "explanation": "..",
                    "weight_applied": 1.0,
                }],
            },
            {
                "subject_pinyin": "lisi",
                "overall": 3.8, "confidence": "medium",
                "rationale": "verifier perspective",
                "dimensions": {"collaboration": 4.0},
                "evidence": [{
                    "dimension": "collaboration", "polarity": "positive",
                    "confidence": "medium", "source_kind": "file",
                    "source_filename": "002_lisi_verify_xx.md",
                    "source_file_type": "verify",
                    "quote": "lisi verified", "explanation": "..",
                    "weight_applied": 1.0,
                }],
            },
        ],
        "skipped_subjects": [],
    })
    parsed = parse_and_validate(
        raw, index_data, candidate_subjects={"zhangsan", "lisi"},
    )
    result = build_score_writes(parsed, resolver=resolver, weight_map={})
    assert result is not None
    assert len(result) == 2
    # Each pair carries its subject_user_id resolved from pinyin
    by_subject = {s.subject_user_id: (s, ev) for s, ev in result}
    # zhangsan fixture provides zhangsan's id; lisi created above
    assert lisi.id in by_subject
    lisi_score, _ = by_subject[lisi.id]
    assert lisi_score.collaboration == 4.0
