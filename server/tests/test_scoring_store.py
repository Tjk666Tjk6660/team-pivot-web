from __future__ import annotations

import sqlite3
import time

import pytest

from server.db import Database
from server.pivot_users import PivotUserRepo
from server.scoring.store import (
    EvidenceWrite,
    ScoreWrite,
    ScoringJob,
    ScoringStore,
)


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.db")


@pytest.fixture
def store(db):
    return ScoringStore(db)


@pytest.fixture
def users(db):
    return PivotUserRepo(db)


@pytest.fixture
def owner(users):
    return users.create(
        display_name="张三", pinyin="zhangsan", email=None, avatar_url="",
    )


def _job(owner_id: str, *, matter_id: str = "eng/auth-redesign") -> ScoringJob:
    return ScoringJob(
        matter_id=matter_id,
        matter_category="eng",
        subject_user_id=owner_id,
        triggered_by="auto",
        triggered_actor_id=owner_id,
    )


# ── Runs ──────────────────────────────────────────────────────────────


def test_start_run_creates_queued(store, owner):
    run_id = store.start_run(_job(owner.id), timeline_hash="h1", model="m1")
    run = store.get_run(run_id)
    assert run is not None
    assert run.status == "queued"
    assert run.matter_id == "eng/auth-redesign"
    assert run.subject_user_id == owner.id
    assert run.triggered_by == "auto"
    assert run.timeline_hash == "h1"
    assert run.model == "m1"
    assert run.finished_at is None


def test_start_run_rejects_invalid_triggered_by(store, owner):
    bad = ScoringJob(
        matter_id="x", matter_category="x", subject_user_id=owner.id,
        triggered_by="bogus",  # type: ignore[arg-type]
    )
    with pytest.raises(ValueError, match="triggered_by"):
        store.start_run(bad, timeline_hash="h1", model="m1")


def test_transition_running_then_finish_success(store, owner):
    run_id = store.start_run(_job(owner.id), timeline_hash="h", model="m")
    store.transition_running(run_id)
    assert store.get_run(run_id).status == "running"
    store.finish_run(run_id, "success", prompt_tokens=100, completion_tokens=50)
    r = store.get_run(run_id)
    assert r.status == "success"
    assert r.prompt_tokens == 100
    assert r.completion_tokens == 50
    assert r.finished_at is not None


def test_finish_run_failed_records_error(store, owner):
    run_id = store.start_run(_job(owner.id), timeline_hash="h", model="m")
    store.finish_run(run_id, "failed", error="ai_timeout")
    r = store.get_run(run_id)
    assert r.status == "failed"
    assert r.error == "ai_timeout"


def test_finish_run_rejects_invalid_status(store, owner):
    run_id = store.start_run(_job(owner.id), timeline_hash="h", model="m")
    with pytest.raises(ValueError):
        store.finish_run(run_id, "skipped")  # type: ignore[arg-type]


def test_idempotency_blocks_duplicate_active_run(store, owner):
    """Two queued/running runs for the same (matter, timeline) violate the
    partial unique index."""
    store.start_run(_job(owner.id), timeline_hash="h-same", model="m")
    with pytest.raises(sqlite3.IntegrityError):
        store.start_run(_job(owner.id), timeline_hash="h-same", model="m")


def test_idempotency_allows_new_run_after_success(store, owner):
    """Multiple success rows for the same timeline_hash are allowed (audit
    trail for admin reruns / re-evaluations). The unique index only blocks
    queued/running collisions."""
    first = store.start_run(_job(owner.id), timeline_hash="h", model="m")
    store.finish_run(first, "success")
    # Admin rerun (or any caller bypassing has_success) should be able to
    # start a new queued run alongside the prior success.
    second = store.start_run(_job(owner.id), timeline_hash="h", model="m")
    assert second != first


def test_idempotency_allows_different_timeline_hash(store, owner):
    a = store.start_run(_job(owner.id), timeline_hash="h-a", model="m")
    b = store.start_run(_job(owner.id), timeline_hash="h-b", model="m")
    assert a != b


def test_idempotency_allows_rerun_after_failure(store, owner):
    """A failed run releases the idempotency slot — another run can take over."""
    first = store.start_run(_job(owner.id), timeline_hash="h", model="m")
    store.finish_run(first, "failed", error="boom")
    # Now another run for the same (matter, hash) should succeed
    second = store.start_run(_job(owner.id), timeline_hash="h", model="m")
    assert second != first


def test_has_success_false_when_no_run(store, owner):
    assert store.has_success("nope/none", "any-hash") is False


def test_has_success_true_after_success(store, owner):
    run_id = store.start_run(_job(owner.id), timeline_hash="h", model="m")
    store.finish_run(run_id, "success")
    assert store.has_success("eng/auth-redesign", "h") is True


def test_has_success_true_for_in_flight_run(store, owner):
    """A queued or running run also counts as 'occupying the slot' so the
    worker won't kick off a duplicate."""
    store.start_run(_job(owner.id), timeline_hash="h", model="m")
    assert store.has_success("eng/auth-redesign", "h") is True


def test_has_success_ignores_failed(store, owner):
    run_id = store.start_run(_job(owner.id), timeline_hash="h", model="m")
    store.finish_run(run_id, "failed", error="x")
    assert store.has_success("eng/auth-redesign", "h") is False


def test_mark_skipped_does_not_block_idempotency(store, owner):
    """Skipped rows are pure observability — should not occupy the unique slot."""
    store.mark_skipped(_job(owner.id), timeline_hash="h", reason="duplicate")
    store.mark_skipped(_job(owner.id), timeline_hash="h", reason="duplicate")
    # Now a real run should still be able to start
    run_id = store.start_run(_job(owner.id), timeline_hash="h", model="m")
    assert store.get_run(run_id).status == "queued"


def test_list_runs_filters_and_orders(store, owner):
    a = store.start_run(_job(owner.id, matter_id="m1"), timeline_hash="h1", model="m")
    store.finish_run(a, "success")
    time.sleep(0.01)
    b = store.start_run(_job(owner.id, matter_id="m2"), timeline_hash="h2", model="m")
    store.finish_run(b, "failed", error="x")

    items = store.list_runs()
    assert [r.run_id for r in items] == [b, a]  # most recent first

    successes = store.list_runs(status="success")
    assert [r.run_id for r in successes] == [a]

    only_m2 = store.list_runs(matter_id="m2")
    assert [r.run_id for r in only_m2] == [b]


def test_count_runs(store, owner):
    a = store.start_run(_job(owner.id, matter_id="m1"), timeline_hash="h1", model="m")
    store.finish_run(a, "success")
    b = store.start_run(_job(owner.id, matter_id="m2"), timeline_hash="h2", model="m")
    store.finish_run(b, "failed", error="x")

    assert store.count_runs() == 2
    assert store.count_runs(status="success") == 1
    assert store.count_runs(matter_id="m1") == 1


def test_list_runs_matter_query_substring(store, owner):
    """matter_query is a LIKE substring filter — useful when the admin
    knows part of a matter_id but not the exact slug."""
    a = store.start_run(
        _job(owner.id, matter_id="客户验收流程优化"),
        timeline_hash="h1", model="m",
    )
    b = store.start_run(
        _job(owner.id, matter_id="测试评分体系"),
        timeline_hash="h2", model="m",
    )
    store.start_run(
        _job(owner.id, matter_id="某个无关项"),
        timeline_hash="h3", model="m",
    )

    found = store.list_runs(matter_query="验收")
    assert [r.run_id for r in found] == [a]

    found = store.list_runs(matter_query="评分")
    assert [r.run_id for r in found] == [b]

    # Substring match in the middle of the slug
    found = store.list_runs(matter_query="流程")
    assert [r.run_id for r in found] == [a]

    assert store.count_runs(matter_query="评分") == 1
    assert store.count_runs(matter_query="不存在") == 0


def test_list_runs_matter_query_escapes_wildcards(store, owner):
    """LIKE wildcards (% and _) in user input must be treated literally,
    otherwise pasting "10%" would match every matter."""
    a = store.start_run(
        _job(owner.id, matter_id="ops/100-percent-done"),
        timeline_hash="h1", model="m",
    )
    store.start_run(
        _job(owner.id, matter_id="ops/100ABCdone"),
        timeline_hash="h2", model="m",
    )

    # Literal percent sign should match only entries that actually contain "%"
    # — neither matter_id has a literal '%', so this returns nothing.
    found = store.list_runs(matter_query="100%")
    assert found == []

    # The actual percent-containing slug
    a2 = store.start_run(
        _job(owner.id, matter_id="loaded-100%-bar"),
        timeline_hash="h3", model="m",
    )
    found = store.list_runs(matter_query="100%")
    assert [r.run_id for r in found] == [a2]
    # And the literal-substring search still hits everything with "100"
    found = store.list_runs(matter_query="100")
    assert {r.run_id for r in found} == {a, a2,
        store.list_runs(matter_query="100ABC")[0].run_id,
    }


def test_latest_success_for_matter(store, owner):
    a = store.start_run(_job(owner.id), timeline_hash="h-a", model="m")
    store.finish_run(a, "success")
    time.sleep(0.01)
    b = store.start_run(_job(owner.id), timeline_hash="h-b", model="m")
    store.finish_run(b, "success")

    latest = store.latest_success_for_matter("eng/auth-redesign")
    assert latest is not None
    assert latest.run_id == b


def test_latest_success_ignores_failed(store, owner):
    a = store.start_run(_job(owner.id), timeline_hash="h-a", model="m")
    store.finish_run(a, "success")
    time.sleep(0.01)
    b = store.start_run(_job(owner.id), timeline_hash="h-b", model="m")
    store.finish_run(b, "failed", error="x")
    latest = store.latest_success_for_matter("eng/auth-redesign")
    assert latest is not None
    assert latest.run_id == a


def test_sweep_orphans_marks_running_as_failed(store, owner):
    run_id = store.start_run(_job(owner.id), timeline_hash="h", model="m")
    store.transition_running(run_id)
    # Force started_at into the past
    with store._db.connect() as conn:
        conn.execute(
            "UPDATE matter_scoring_runs SET started_at=started_at-3600 WHERE run_id=?",
            (run_id,),
        )

    swept = store.sweep_orphans(timeout_seconds=60)
    assert swept == 1
    r = store.get_run(run_id)
    assert r.status == "failed"
    assert r.error == "orphan"
    assert r.finished_at is not None


def test_sweep_orphans_skips_recent_running(store, owner):
    run_id = store.start_run(_job(owner.id), timeline_hash="h", model="m")
    store.transition_running(run_id)
    swept = store.sweep_orphans(timeout_seconds=600)
    assert swept == 0
    assert store.get_run(run_id).status == "running"


# ── Scores + evidence ────────────────────────────────────────────────


def _evidence(**kwargs) -> EvidenceWrite:
    base: dict = {
        "dimension": "delivery",
        "polarity": "positive",
        "confidence": "high",
        "source_kind": "file",
        "source_filename": "003_lisi_verify_xx.md",
        "source_file_type": "verify",
        "quote": "verify 通过",
        "explanation": "李四在 verify 中确认",
    }
    base.update(kwargs)
    return EvidenceWrite(**base)


def _score(*, subject_user_id: str | None = None, **kwargs) -> ScoreWrite:
    """v2.1: subject_user_id required on ScoreWrite. Default test fixture
    leaves it as a placeholder; tests that need a specific resolvable id
    pass `subject_user_id=owner.id`."""
    base: dict = {
        "subject_user_id": subject_user_id or "_placeholder_user_id",
        "overall": 4.2,
        "confidence": "high",
        "rationale": "...",
        "delivery": 4.5,
        "accountability": 4.0,
        "collaboration": None,
        "judgment": None,
        "process": 4.0,
    }
    base.update(kwargs)
    return ScoreWrite(**base)


def test_write_results_inserts_score_and_evidence(store, owner):
    run_id = store.start_run(_job(owner.id), timeline_hash="h", model="m")
    store.transition_running(run_id)
    store.write_results(
        run_id,
        _score(),
        [
            _evidence(),
            _evidence(dimension="accountability", quote="按时收口", explanation="..."),
            _evidence(dimension="process", quote="文件齐全", explanation="..."),
        ],
    )

    got = store.get_score(run_id)
    assert got is not None
    score, evidence = got
    assert score.overall == 4.2
    assert score.delivery == 4.5
    assert score.collaboration is None
    assert len(evidence) == 3
    assert {e.dimension for e in evidence} == {
        "delivery", "accountability", "process",
    }


def test_write_results_rejects_invalid_dimension(store, owner):
    run_id = store.start_run(_job(owner.id), timeline_hash="h", model="m")
    with pytest.raises(ValueError, match="dimension"):
        store.write_results(run_id, _score(), [_evidence(dimension="bogus")])


def test_write_results_rejects_invalid_confidence(store, owner):
    run_id = store.start_run(_job(owner.id), timeline_hash="h", model="m")
    with pytest.raises(ValueError, match="confidence"):
        store.write_results(run_id, _score(confidence="bogus"), [_evidence()])


def test_write_results_rejects_comment_without_created_at(store, owner):
    run_id = store.start_run(_job(owner.id), timeline_hash="h", model="m")
    e = _evidence(
        source_kind="comment", source_comment_created_at=None,
    )
    with pytest.raises(ValueError, match="comment"):
        store.write_results(run_id, _score(), [e])


def test_write_results_rejects_unknown_run(store):
    with pytest.raises(ValueError, match="run not found"):
        store.write_results("nope", _score(), [_evidence()])


def test_write_results_rejects_finished_run(store, owner):
    run_id = store.start_run(_job(owner.id), timeline_hash="h", model="m")
    store.finish_run(run_id, "success")
    with pytest.raises(ValueError, match="cannot write"):
        store.write_results(run_id, _score(), [_evidence()])


def test_write_results_rejects_invalid_weight(store, owner):
    run_id = store.start_run(_job(owner.id), timeline_hash="h", model="m")
    with pytest.raises(ValueError, match="weight"):
        store.write_results(run_id, _score(), [_evidence(weight_applied=10.0)])


def test_write_results_persists_annotation_evidence(store, owner):
    """v2.1: source_kind=annotation evidence round-trips with author + created_at."""
    run_id = store.start_run(_job(owner.id), timeline_hash="h", model="m")
    store.transition_running(run_id)
    e = _evidence(
        source_kind="annotation",
        source_filename="002_liuyu_act_xx.md",
        source_file_type="act",
        source_annotation_created_at="2026-04-22T14:00:00+08:00",
        source_annotation_author_id=owner.id,
        attribution_basis="file_creator",
    )
    store.write_results(run_id, _score(), [e])

    got = store.get_score(run_id)
    assert got is not None
    _, evidence = got
    assert len(evidence) == 1
    row = evidence[0]
    assert row.source_kind == "annotation"
    assert row.source_annotation_created_at == "2026-04-22T14:00:00+08:00"
    assert row.source_annotation_author_id == owner.id
    assert row.attribution_basis == "file_creator"
    # Comment fields should remain NULL on annotation evidence
    assert row.source_comment_created_at is None
    assert row.source_comment_author_id is None


def test_write_results_rejects_annotation_without_created_at(store, owner):
    """v2.1: annotation evidence must carry created_at (analogous to comment)."""
    run_id = store.start_run(_job(owner.id), timeline_hash="h", model="m")
    e = _evidence(
        source_kind="annotation",
        source_annotation_created_at=None,
    )
    with pytest.raises(ValueError, match="annotation"):
        store.write_results(run_id, _score(), [e])


def test_write_results_persists_attribution_basis_for_all_kinds(store, owner):
    """All five attribution_basis enum values round-trip."""
    run_id = store.start_run(_job(owner.id), timeline_hash="h", model="m")
    store.transition_running(run_id)
    bases = [
        "file_creator",
        "explicit_mention",
        "at_target",
        "owner_change_reason",
        "verify_outcome",
    ]
    evidences = [
        _evidence(
            dimension="delivery" if i == 0 else "accountability" if i == 1 else "judgment" if i == 2 else "collaboration" if i == 3 else "process",
            attribution_basis=basis,
            quote=f"quote-{i}", explanation=f"exp-{i}",
        )
        for i, basis in enumerate(bases)
    ]
    store.write_results(run_id, _score(), evidences)
    got = store.get_score(run_id)
    assert got is not None
    _, rows = got
    assert {r.attribution_basis for r in rows} == set(bases)


def test_write_results_rejects_invalid_attribution_basis(store, owner):
    run_id = store.start_run(_job(owner.id), timeline_hash="h", model="m")
    with pytest.raises(ValueError, match="attribution_basis"):
        store.write_results(
            run_id, _score(),
            [_evidence(attribution_basis="made_up_value")],  # type: ignore[arg-type]
        )


def test_write_results_attribution_basis_optional(store, owner):
    """attribution_basis is nullable (back-compat with old runs)."""
    run_id = store.start_run(_job(owner.id), timeline_hash="h", model="m")
    store.transition_running(run_id)
    store.write_results(
        run_id, _score(),
        [_evidence(attribution_basis=None)],
    )
    got = store.get_score(run_id)
    assert got is not None
    _, rows = got
    assert rows[0].attribution_basis is None


def test_start_run_default_schema_version_is_phase_1(store, owner):
    """Phase 1 worker still produces v1 runs by default."""
    run_id = store.start_run(_job(owner.id), timeline_hash="h", model="m")
    run = store.get_run(run_id)
    assert run is not None
    assert run.schema_version == 1


def test_start_run_explicit_schema_version_2(store, owner):
    """Phase 2 worker (Task 2.4) will pass schema_version=2 explicitly."""
    run_id = store.start_run(
        _job(owner.id), timeline_hash="h", model="m", schema_version=2,
    )
    run = store.get_run(run_id)
    assert run is not None
    assert run.schema_version == 2


def test_set_skipped_subjects_round_trips(store, owner):
    """v2.2: AI's skipped_subjects list persists + reads back on the run row."""
    run_id = store.start_run(_job(owner.id), timeline_hash="h", model="m")
    # Default (never set) is empty tuple
    run = store.get_run(run_id)
    assert run.skipped_subjects == ()

    # Worker calls set_skipped_subjects after parse — store as JSON
    store.set_skipped_subjects(run_id, ["lishuai", "zhangsan"])
    run = store.get_run(run_id)
    assert run.skipped_subjects == ("lishuai", "zhangsan")


def test_set_skipped_subjects_empty_explicit(store, owner):
    """Empty list explicitly set distinguishes "AI scored everyone" from
    legacy / unwritten state."""
    run_id = store.start_run(_job(owner.id), timeline_hash="h", model="m")
    store.set_skipped_subjects(run_id, [])
    run = store.get_run(run_id)
    assert run.skipped_subjects == ()


def test_db_migration_adds_v2_1_columns_to_legacy_db(tmp_path):
    """Simulate a Phase 1 DB (no schema_version, no annotation cols on
    evidence) and verify Database.__init__ migrates it cleanly + the store
    operates against the migrated tables."""
    db_path = tmp_path / "legacy.db"
    legacy_conn = sqlite3.connect(db_path)
    # Mimic the pre-v2.1 SCHEMA shape — only the columns that existed before
    # the migration. PivotUserRepo / scoring tables both pre-existing.
    legacy_conn.executescript("""
        CREATE TABLE matter_scoring_runs (
            run_id TEXT PRIMARY KEY,
            matter_id TEXT NOT NULL,
            matter_category TEXT NOT NULL,
            subject_user_id TEXT NOT NULL,
            triggered_by TEXT NOT NULL,
            triggered_actor_id TEXT,
            status TEXT NOT NULL,
            error TEXT,
            model TEXT,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            started_at REAL NOT NULL,
            finished_at REAL,
            timeline_hash TEXT NOT NULL
        );
        CREATE TABLE matter_score_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            matter_id TEXT NOT NULL,
            subject_user_id TEXT NOT NULL,
            dimension TEXT NOT NULL,
            polarity TEXT NOT NULL,
            confidence TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            source_filename TEXT NOT NULL,
            source_file_type TEXT NOT NULL,
            source_comment_created_at TEXT,
            source_comment_author_id TEXT,
            weight_applied REAL NOT NULL DEFAULT 1.0,
            quote TEXT NOT NULL,
            explanation TEXT NOT NULL
        );
    """)
    legacy_conn.commit()
    legacy_conn.close()

    # Database constructor runs SCHEMA + _migrate; should ALTER missing cols
    db = Database(db_path)
    with db.connect() as conn:
        run_cols = {row[1] for row in conn.execute("PRAGMA table_info(matter_scoring_runs)")}
        ev_cols = {row[1] for row in conn.execute("PRAGMA table_info(matter_score_evidence)")}

    assert "schema_version" in run_cols, "schema_version not added by migration"
    assert "source_annotation_created_at" in ev_cols
    assert "source_annotation_author_id" in ev_cols
    assert "attribution_basis" in ev_cols

    # Migrated DB must be functional — write + read evidence with new fields
    users = PivotUserRepo(db)
    u = users.create(display_name="X", pinyin="x", email=None, avatar_url="")
    store = ScoringStore(db)
    run_id = store.start_run(
        ScoringJob(
            matter_id="m", matter_category="x", subject_user_id=u.id,
            triggered_by="auto",
        ),
        timeline_hash="h", model="m",
    )
    store.transition_running(run_id)
    store.write_results(
        run_id, _score(),
        [_evidence(
            source_kind="annotation",
            source_annotation_created_at="2026-04-22T14:00:00+08:00",
            source_annotation_author_id=u.id,
            attribution_basis="file_creator",
        )],
    )
    got = store.get_score(run_id)
    assert got is not None
    _, rows = got
    assert rows[0].attribution_basis == "file_creator"


def test_apply_human_override(store, owner):
    run_id = store.start_run(_job(owner.id), timeline_hash="h", model="m")
    # Override updates by (run_id, subject_user_id) — score must be written
    # under owner's id so the override targets the right row.
    store.write_results(run_id, _score(subject_user_id=owner.id), [_evidence()])
    store.apply_human_override(
        run_id, owner.id, overall=3.5, note="too generous", by_user_id=owner.id,
    )
    got = store.get_score(run_id)
    assert got is not None
    score, _ = got
    assert score.human_override_overall == 3.5
    assert score.human_override_note == "too generous"
    assert score.human_override_by == owner.id


# ── Commenter weights ────────────────────────────────────────────────


def test_upsert_weight_creates(store, users):
    ceo = users.create(
        display_name="CEO", pinyin="ceo", email=None, avatar_url="",
    )
    admin = users.create(
        display_name="Admin", pinyin="admin", email=None, avatar_url="",
    )
    w = store.upsert_weight(
        pivot_user_id=ceo.id, weight=2.0, label="CEO",
        note=None, updated_by=admin.id,
    )
    assert w.pivot_user_id == ceo.id
    assert w.weight == 2.0
    assert w.label == "CEO"
    assert w.updated_by == admin.id


def test_upsert_weight_overwrites(store, users):
    user = users.create(
        display_name="X", pinyin="x", email=None, avatar_url="",
    )
    admin = users.create(
        display_name="A", pinyin="a", email=None, avatar_url="",
    )
    store.upsert_weight(
        pivot_user_id=user.id, weight=1.5, label="CTO",
        note=None, updated_by=admin.id,
    )
    store.upsert_weight(
        pivot_user_id=user.id, weight=2.0, label="CEO",
        note="升职了", updated_by=admin.id,
    )
    got = store.get_weight(user.id)
    assert got is not None
    assert got.weight == 2.0
    assert got.label == "CEO"
    assert got.note == "升职了"


def test_upsert_weight_rejects_out_of_range(store, users):
    u = users.create(display_name="X", pinyin="x", email=None, avatar_url="")
    a = users.create(display_name="A", pinyin="a", email=None, avatar_url="")
    with pytest.raises(ValueError, match="weight"):
        store.upsert_weight(
            pivot_user_id=u.id, weight=10.0, label="CEO",
            note=None, updated_by=a.id,
        )
    with pytest.raises(ValueError, match="weight"):
        store.upsert_weight(
            pivot_user_id=u.id, weight=0.0, label="CEO",
            note=None, updated_by=a.id,
        )


def test_upsert_weight_rejects_blank_label(store, users):
    u = users.create(display_name="X", pinyin="x", email=None, avatar_url="")
    a = users.create(display_name="A", pinyin="a", email=None, avatar_url="")
    with pytest.raises(ValueError, match="label"):
        store.upsert_weight(
            pivot_user_id=u.id, weight=2.0, label="   ",
            note=None, updated_by=a.id,
        )


def test_list_weights_orders_by_weight_desc(store, users):
    ceo = users.create(display_name="CEO", pinyin="ceo", email=None, avatar_url="")
    cto = users.create(display_name="CTO", pinyin="cto", email=None, avatar_url="")
    a = users.create(display_name="A", pinyin="a", email=None, avatar_url="")
    store.upsert_weight(
        pivot_user_id=cto.id, weight=1.5, label="CTO",
        note=None, updated_by=a.id,
    )
    store.upsert_weight(
        pivot_user_id=ceo.id, weight=2.0, label="CEO",
        note=None, updated_by=a.id,
    )
    items = store.list_weights()
    assert [w.label for w in items] == ["CEO", "CTO"]


def test_delete_weight(store, users):
    u = users.create(display_name="X", pinyin="x", email=None, avatar_url="")
    a = users.create(display_name="A", pinyin="a", email=None, avatar_url="")
    store.upsert_weight(
        pivot_user_id=u.id, weight=2.0, label="CEO",
        note=None, updated_by=a.id,
    )
    assert store.delete_weight(u.id) is True
    assert store.get_weight(u.id) is None


def test_delete_weight_returns_false_when_missing(store):
    assert store.delete_weight("nonexistent") is False
