"""End-to-end test for the user scoring (员工评价体系) feature.

Drives a finished matter all the way through the scoring pipeline:

    matter index YAML on disk
            │
            ▼
    [trigger] subscribes TOPIC_RESULT_CREATED → enqueues ScoringJob
            │
            ▼
    [worker] run_scoring_once → AI call (stubbed) → schema validate → store
            │
            ▼
    matter_scoring_runs / matter_scores / matter_score_evidence rows in DB

Stubs the AI (no real OpenRouter calls); everything else — DB, settings,
PivotUserRepo, ScoringStore, schema validation, file body loader — is real.

Specifically verifies the Phase 1 attribution rules from matter 005:
  - happy path: AI output with proper attribution lands in DB
  - self-evaluation rejection: AI output where owner cites their own comment
    or own file (positive) is rejected by schema → run marked failed
  - self-eval negative file evidence is still allowed (Phase 1 carve-out)

Treats this as the gate for "did Phase 1 actually deliver" — if this passes
end-to-end, the prompt + schema + store wiring works on a real workflow.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from server.db import Database
from server.events import TOPIC_RESULT_CREATED, clear_subscribers, emit
from server.pivot_users import PivotUserRepo
from server.scoring import trigger as scoring_trigger
from server.scoring.store import ScoringJob, ScoringStore
from server.scoring.trigger import KEY_ENABLED, install
from server.scoring.worker import run_scoring_once
from server.settings import SettingsRepo


# ---------- fixtures ----------


class _StubWorkspace:
    """Minimal Workspace surface area used by trigger + worker."""

    def __init__(self, root: Path) -> None:
        self.path = root
        (root / "index").mkdir(parents=True, exist_ok=True)
        (root / "discussions").mkdir(parents=True, exist_ok=True)

    @property
    def index_dir(self) -> Path:
        return self.path / "index"


@pytest.fixture
def workspace(tmp_path):
    return _StubWorkspace(tmp_path)


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "scoring_e2e.db")


@pytest.fixture
def pivot_users(db):
    return PivotUserRepo(db)


@pytest.fixture
def store(db):
    return ScoringStore(db)


@pytest.fixture
def settings(db):
    s = SettingsRepo(db)
    # Enable scoring + provide an AI endpoint so worker doesn't skip
    s.set(KEY_ENABLED, "1")
    s.set("ai.openrouter_api_key", "test-key")
    s.set("ai.base_url", "https://api.test")
    s.set("ai.model", "test-model")
    return s


@pytest.fixture
def owner(pivot_users):
    return pivot_users.create(
        display_name="张三", pinyin="zhangsan", email=None, avatar_url="",
    )


@pytest.fixture
def lisi(pivot_users):
    """A second user — verifies zhangsan's act in the seeded matter."""
    return pivot_users.create(
        display_name="李四", pinyin="lisi", email=None, avatar_url="",
    )


@pytest.fixture(autouse=True)
def _reset_event_bus():
    """Each test gets a clean subscriber list (events.py has module-level state)."""
    clear_subscribers()
    yield
    clear_subscribers()


# ---------- helpers ----------


def _seed_matter(workspace: _StubWorkspace, *, matter_id: str = "client-acceptance") -> str:
    """Write a finished matter index YAML.

    Timeline:
      001 act    by zhangsan (owner)
      002 verify by lisi  (verifies act)
      003 result by zhangsan (outcome=finished)

    Returns the matter_id (so callers can pass it into ScoringJob).
    """
    category = "Pivot"
    rel_dir = f"discussions/{category}/{matter_id}"
    data = {
        "matter": {
            "id": matter_id,
            "title": "客户验收流程优化",
            "current_status": "finished",
            "owner": "zhangsan",
            "created_at": "2026-04-20T10:00:00+08:00",
            "updated_at": "2026-04-29T18:30:00+08:00",
        },
        "timeline": [
            {
                "file": f"{rel_dir}/001_zhangsan_act_xx.md",
                "type": "act", "creator": "zhangsan", "owner": "zhangsan",
                "created_at": "2026-04-20T10:00:00+08:00",
                "summary": "完成接口对接",
                "verifications_received": [
                    {
                        "verify_file": f"{rel_dir}/002_lisi_verify_xx.md",
                        "judgement": "passed", "verified_by": "lisi",
                    },
                ],
            },
            {
                "file": f"{rel_dir}/002_lisi_verify_xx.md",
                "type": "verify", "creator": "lisi", "owner": "lisi",
                "created_at": "2026-04-22T14:00:00+08:00",
                "summary": "验收通过",
                "verifications": [
                    {
                        "target": f"{rel_dir}/001_zhangsan_act_xx.md",
                        "judgement": "passed", "comment": "客户当天验收",
                    },
                ],
            },
            {
                "file": f"{rel_dir}/003_zhangsan_result_xx.md",
                "type": "result", "creator": "zhangsan", "owner": "zhangsan",
                "created_at": "2026-04-29T18:30:00+08:00",
                "summary": "客户已接受",
                "outcome": "finished",
                "status_change": {"from": "executing", "to": "finished"},
            },
        ],
    }
    index_path = workspace.index_dir / f"{matter_id}.index.yaml"
    index_path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return matter_id


def _job(matter_id: str, owner_id: str, *, triggered_by="auto") -> ScoringJob:
    return ScoringJob(
        matter_id=matter_id,
        matter_category="Pivot",
        subject_user_id=owner_id,
        triggered_by=triggered_by,
        triggered_actor_id=owner_id,
    )


def _ai_output(
    *,
    subject: str = "zhangsan",
    evidence: list[dict] | None = None,
    dimensions: dict | None = None,
) -> str:
    """Build a valid-shape AI response with given evidence/dimensions.

    Defaults to a happy-path output: lisi's verify file as positive delivery
    evidence + result file as positive accountability/process evidence.
    """
    if evidence is None:
        evidence = [
            {
                "dimension": "delivery", "polarity": "positive", "confidence": "high",
                "source_kind": "file",
                "source_filename": "002_lisi_verify_xx.md",
                "source_file_type": "verify",
                "source_file_creator": "lisi",
                "quote": "客户当天验收", "explanation": "lisi 验收通过",
                "weight_applied": 1.0,
            },
            {
                "dimension": "accountability", "polarity": "positive", "confidence": "high",
                "source_kind": "file",
                "source_filename": "003_zhangsan_result_xx.md",
                "source_file_type": "result",
                "source_file_creator": "zhangsan",
                "quote": "客户已接受", "explanation": "result 收口",
                "weight_applied": 1.0,
                # NOTE: result is owner's own file but polarity=negative would
                # be allowed; positive is rejected by self-eval rule. Replace
                # this entry with negative or use lisi's file in self-eval tests.
                # For happy-path we'll mutate this in tests where needed.
            },
        ]
    if dimensions is None:
        dimensions = {
            "delivery": 4.5,
            "accountability": 4.0,
            "collaboration": None,
            "judgment": None,
            "process": None,
        }
    return json.dumps({
        "scores": [{
            "subject_pinyin": subject,
            "overall": 4.2,
            "confidence": "high",
            "rationale": "owner 推动验收并完成收口",
            "dimensions": dimensions,
            "evidence": evidence,
        }],
        "skipped_subjects": [],
    })


def _run_to_completion(
    matter_id: str,
    owner_id: str,
    *,
    ai_output: str,
    store: ScoringStore,
    workspace: _StubWorkspace,
    settings: SettingsRepo,
    pivot_users: PivotUserRepo,
) -> str:
    """Drive run_scoring_once with a stub ai_call returning given output.

    Returns the run_id (always one new run is created, regardless of outcome).
    """
    captured: dict = {}

    def fake_ai(messages, model, api_key, base_url, timeout_seconds):
        captured["messages"] = messages
        return ai_output

    run_scoring_once(
        _job(matter_id, owner_id),
        store=store, workspace=workspace, settings=settings,
        pivot_users=pivot_users, ai_call=fake_ai,
    )
    runs = store.list_runs(matter_id=matter_id)
    assert runs, "expected exactly one run row"
    return runs[0].run_id


# ---------- happy path ----------


def test_e2e_happy_path_produces_score(
    workspace, store, settings, pivot_users, owner, lisi,
):
    """End-to-end: finished matter → AI output → score + evidence in DB."""
    matter_id = _seed_matter(workspace)

    # Build evidence that's all attributed to legitimate sources (no self-eval):
    # delivery: lisi's verify (positive — lisi attests to zhangsan's work)
    # accountability: lisi's verify too (still owner's accountability via verify)
    # process: zhangsan's result NEGATIVE (allowed: structural mismatch evidence)
    evidence = [
        {
            "dimension": "delivery", "polarity": "positive", "confidence": "high",
            "source_kind": "file",
            "source_filename": "002_lisi_verify_xx.md",
            "source_file_type": "verify",
            "source_file_creator": "lisi",
            "quote": "客户当天验收", "explanation": "lisi 验收通过",
            "weight_applied": 1.0,
        },
        {
            "dimension": "accountability", "polarity": "positive", "confidence": "medium",
            "source_kind": "file",
            "source_filename": "002_lisi_verify_xx.md",
            "source_file_type": "verify",
            "source_file_creator": "lisi",
            "quote": "judgement passed", "explanation": "act 一次通过",
            "weight_applied": 1.0,
        },
    ]
    out = _ai_output(
        evidence=evidence,
        dimensions={
            "delivery": 4.5, "accountability": 4.0,
            "collaboration": None, "judgment": None, "process": None,
        },
    )

    run_id = _run_to_completion(
        matter_id, owner.id,
        ai_output=out, store=store, workspace=workspace,
        settings=settings, pivot_users=pivot_users,
    )

    runs = store.list_runs(matter_id=matter_id)
    assert len(runs) == 1
    assert runs[0].status == "success"
    assert runs[0].error is None
    assert runs[0].subject_user_id == owner.id

    got = store.get_score(run_id)
    assert got is not None, "score row should exist for successful run"
    score, evidence_rows = got
    assert score.subject_user_id == owner.id
    assert score.overall == 4.2
    assert score.delivery == 4.5
    assert score.accountability == 4.0
    assert score.process is None  # null dimension preserved
    assert len(evidence_rows) == 2
    # Evidence linked back to actual timeline files (anti-fabrication held)
    filenames = {e.source_filename for e in evidence_rows}
    assert "002_lisi_verify_xx.md" in filenames


# ---------- self-evaluation rejection (matter 005 §6) ----------


def test_e2e_rejects_self_comment_evidence(
    workspace, store, settings, pivot_users, owner, lisi,
):
    """AI tries to use owner's OWN comment as evidence → schema rejects →
    run marked failed with self-evaluation error in run.error."""
    matter_id = _seed_matter(workspace)

    # delivery dim still scored, but its only evidence is a self-comment
    evidence = [
        {
            "dimension": "delivery", "polarity": "positive", "confidence": "high",
            "source_kind": "comment",
            "source_filename": "001_zhangsan_act_xx.md",
            "source_file_type": "act",
            "source_comment_created_at": "2026-04-21T15:00:00+08:00",
            "source_comment_author": "zhangsan",  # ← owner 自己评自己
            "quote": "我做得不错", "explanation": "self-praise",
            "weight_applied": 1.0,
        },
    ]
    out = _ai_output(
        evidence=evidence,
        dimensions={
            "delivery": 5.0, "accountability": None, "collaboration": None,
            "judgment": None, "process": None,
        },
    )

    run_id = _run_to_completion(
        matter_id, owner.id,
        ai_output=out, store=store, workspace=workspace,
        settings=settings, pivot_users=pivot_users,
    )

    run = store.list_runs(matter_id=matter_id)[0]
    assert run.status == "failed"
    assert run.error is not None and "self-evaluation" in run.error
    # No score / evidence rows on failed run
    assert store.get_score(run_id) is None


def test_e2e_accepts_self_authored_file_evidence_positive(
    workspace, store, settings, pivot_users, owner, lisi,
):
    """v2.2: AI cites owner's own file as POSITIVE evidence — allowed.

    The file is a work product, not a self-comment. Earlier revision
    rejected this and broke real scoring runs (AI consistently uses the
    work-product file as the natural evidence pointer; rejecting it would
    require AI to always re-route to verify files even when the act is the
    cleaner anchor)."""
    matter_id = _seed_matter(workspace)

    evidence = [
        {
            "dimension": "delivery", "polarity": "positive", "confidence": "high",
            "source_kind": "file",
            "source_filename": "001_zhangsan_act_xx.md",
            "source_file_type": "act",
            "source_file_creator": "zhangsan",
            "quote": "完成接口对接",
            "explanation": "owner's act delivered the interface",
            "weight_applied": 1.0,
        },
    ]
    out = _ai_output(
        evidence=evidence,
        dimensions={
            "delivery": 4.5, "accountability": None, "collaboration": None,
            "judgment": None, "process": None,
        },
    )

    run_id = _run_to_completion(
        matter_id, owner.id,
        ai_output=out, store=store, workspace=workspace,
        settings=settings, pivot_users=pivot_users,
    )

    run = store.list_runs(matter_id=matter_id)[0]
    assert run.status == "success", run.error
    score, _ = store.get_score(run_id)
    assert score.delivery == 4.5


def test_e2e_allows_self_negative_file_evidence(
    workspace, store, settings, pivot_users, owner, lisi,
):
    """Owner's own file as NEGATIVE evidence is allowed (Phase 1 carve-out:
    signal comes from structural mismatch, not from self-praise)."""
    matter_id = _seed_matter(workspace)

    evidence = [
        {
            "dimension": "judgment", "polarity": "negative", "confidence": "medium",
            "source_kind": "file",
            "source_filename": "001_zhangsan_act_xx.md",
            "source_file_type": "act",
            "source_file_creator": "zhangsan",
            "quote": "前期字段没确认", "explanation": "owner 的 act 显示判断不充分",
            "weight_applied": 1.0,
        },
    ]
    out = _ai_output(
        evidence=evidence,
        dimensions={
            "delivery": None, "accountability": None, "collaboration": None,
            "judgment": 2.5, "process": None,
        },
    )

    run_id = _run_to_completion(
        matter_id, owner.id,
        ai_output=out, store=store, workspace=workspace,
        settings=settings, pivot_users=pivot_users,
    )

    run = store.list_runs(matter_id=matter_id)[0]
    assert run.status == "success", run.error
    score, _ = store.get_score(run_id)
    assert score.judgment == 2.5


# ---------- idempotency ----------


def test_e2e_idempotent_skips_second_run_for_same_timeline(
    workspace, store, settings, pivot_users, owner, lisi,
):
    """Same matter + same timeline_hash → second auto-trigger is skipped."""
    matter_id = _seed_matter(workspace)
    out = _ai_output(evidence=[
        {
            "dimension": "delivery", "polarity": "positive", "confidence": "high",
            "source_kind": "file",
            "source_filename": "002_lisi_verify_xx.md",
            "source_file_type": "verify",
            "source_file_creator": "lisi",
            "quote": "passed", "explanation": "...",
            "weight_applied": 1.0,
        },
    ], dimensions={
        "delivery": 4.0, "accountability": None, "collaboration": None,
        "judgment": None, "process": None,
    })

    # First run — succeeds
    _run_to_completion(
        matter_id, owner.id,
        ai_output=out, store=store, workspace=workspace,
        settings=settings, pivot_users=pivot_users,
    )
    # Second run with same timeline — must be skipped
    _run_to_completion(
        matter_id, owner.id,
        ai_output=out, store=store, workspace=workspace,
        settings=settings, pivot_users=pivot_users,
    )

    runs = store.list_runs(matter_id=matter_id)
    assert len(runs) == 2
    statuses = sorted(r.status for r in runs)
    assert statuses == ["skipped", "success"]
    skipped = next(r for r in runs if r.status == "skipped")
    assert skipped.error == "duplicate_timeline"


# ---------- prompt integration: attribution rules reach the model ----------


def test_e2e_prompt_carries_phase1_attribution_rules(
    workspace, store, settings, pivot_users, owner, lisi,
):
    """Capture the actual messages sent to the AI and assert the new
    Phase 1 sections (matter 005) made it through prompt building."""
    matter_id = _seed_matter(workspace)
    out = _ai_output(evidence=[
        {
            "dimension": "delivery", "polarity": "positive", "confidence": "high",
            "source_kind": "file",
            "source_filename": "002_lisi_verify_xx.md",
            "source_file_type": "verify",
            "source_file_creator": "lisi",
            "quote": "passed", "explanation": "...",
            "weight_applied": 1.0,
        },
    ], dimensions={
        "delivery": 4.0, "accountability": None, "collaboration": None,
        "judgment": None, "process": None,
    })

    captured: dict = {}

    def fake_ai(messages, model, api_key, base_url, timeout_seconds):
        captured["system"] = messages[0]["content"]
        captured["user"] = messages[1]["content"]
        return out

    run_scoring_once(
        _job(matter_id, owner.id),
        store=store, workspace=workspace, settings=settings,
        pivot_users=pivot_users, ai_call=fake_ai,
    )

    sys_prompt = captured["system"]
    # The three new Phase 1 sections from matter 005
    assert "评价对象识别规则" in sys_prompt
    assert "评价范围限制" in sys_prompt
    assert "owner_change.reason 解析" in sys_prompt
    # Subject baked in
    assert "zhangsan" in sys_prompt
    # File role hint reaches the user prompt (think/act = 核心, verify = 终点)
    user_prompt = captured["user"]
    assert "type=act（核心" in user_prompt
    assert "type=verify（终点" in user_prompt


# ---------- trigger flow: emit TOPIC_RESULT_CREATED → ScoringJob enqueued ----------


class _CapturingQueue:
    """Stand-in for the async ScoringQueue that just records what's enqueued."""

    def __init__(self):
        self.jobs: list[ScoringJob] = []

    def enqueue(self, job: ScoringJob) -> None:
        self.jobs.append(job)


def test_e2e_trigger_enqueues_job_on_finished_result(
    workspace, settings, pivot_users, owner,
):
    """emit TOPIC_RESULT_CREATED with outcome=finished → trigger should
    enqueue a ScoringJob with subject_user_id pointing at the resolved owner.

    Verifies the live event-bus path that production uses, distinct from the
    unit tests that call _handle directly."""
    matter_id = _seed_matter(workspace)
    queue = _CapturingQueue()

    unsubscribe = install(
        workspace=workspace, settings=settings,
        pivot_users=pivot_users, queue=queue,
    )
    try:
        emit(
            TOPIC_RESULT_CREATED,
            matter_id=matter_id, actor="zhangsan",
            payload={"outcome": "finished"},
        )
    finally:
        unsubscribe()

    assert len(queue.jobs) == 1
    job = queue.jobs[0]
    assert job.matter_id == matter_id
    assert job.subject_user_id == owner.id
    assert job.matter_category == "Pivot"
    assert job.triggered_by == "auto"


def test_e2e_trigger_skips_when_outcome_cancelled(
    workspace, settings, pivot_users, owner,
):
    """Decision C: only outcome=finished triggers; cancelled is ignored."""
    matter_id = _seed_matter(workspace)
    queue = _CapturingQueue()

    unsubscribe = install(
        workspace=workspace, settings=settings,
        pivot_users=pivot_users, queue=queue,
    )
    try:
        emit(
            TOPIC_RESULT_CREATED,
            matter_id=matter_id, actor="zhangsan",
            payload={"outcome": "cancelled"},
        )
    finally:
        unsubscribe()

    assert queue.jobs == []


def test_e2e_trigger_skips_when_disabled(
    workspace, settings, pivot_users, owner,
):
    """scoring.enabled=0 → trigger no-ops even on finished result."""
    settings.set(KEY_ENABLED, "0")
    matter_id = _seed_matter(workspace)
    queue = _CapturingQueue()

    unsubscribe = install(
        workspace=workspace, settings=settings,
        pivot_users=pivot_users, queue=queue,
    )
    try:
        emit(
            TOPIC_RESULT_CREATED,
            matter_id=matter_id, actor="zhangsan",
            payload={"outcome": "finished"},
        )
    finally:
        unsubscribe()

    assert queue.jobs == []


# ---------- v2.1: multi-subject end-to-end (Task 2.4) ----------


def _seed_multi_subject_matter(
    workspace: _StubWorkspace, *, matter_id: str = "multi-eval",
) -> str:
    """Write a matter with think+act files from three authors so the
    candidate set has > 1 person."""
    category = "Pivot"
    rel_dir = f"discussions/{category}/{matter_id}"
    data = {
        "matter": {
            "id": matter_id,
            "title": "多人协作 matter",
            "current_status": "finished",
            "owner": "zhangsan",
            "created_at": "2026-04-20T10:00:00+08:00",
            "updated_at": "2026-04-29T18:30:00+08:00",
        },
        "timeline": [
            {
                "file": f"{rel_dir}/001_zhangsan_think_x.md",
                "type": "think", "creator": "zhangsan", "owner": "zhangsan",
                "summary": "framing", "created_at": "2026-04-20T10:00:00+08:00",
            },
            {
                "file": f"{rel_dir}/002_lisi_act_x.md",
                "type": "act", "creator": "lisi", "owner": "lisi",
                "summary": "implement", "created_at": "2026-04-22T11:00:00+08:00",
            },
            {
                "file": f"{rel_dir}/003_zhangsan_result_x.md",
                "type": "result", "creator": "zhangsan", "owner": "zhangsan",
                "summary": "done", "outcome": "finished",
                "created_at": "2026-04-29T18:30:00+08:00",
                "status_change": {"from": "executing", "to": "finished"},
            },
        ],
    }
    index_path = workspace.index_dir / f"{matter_id}.index.yaml"
    index_path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return matter_id


def test_e2e_multi_subject_score_lands_in_db(
    workspace, store, settings, pivot_users, owner, lisi,
):
    """v2.1: trigger resolves think/act creators (zhangsan + lisi); worker
    passes both pinyins to AI; AI returns 2 scores; both land in DB with
    schema_version=2 + each score's subject_user_id matching the right user."""
    matter_id = _seed_multi_subject_matter(workspace)
    queue = _CapturingQueue()
    unsub = install(
        workspace=workspace, settings=settings,
        pivot_users=pivot_users, queue=queue,
    )
    try:
        emit(
            TOPIC_RESULT_CREATED,
            matter_id=matter_id, actor="zhangsan",
            payload={"outcome": "finished"},
        )
    finally:
        unsub()
    assert len(queue.jobs) == 1
    job = queue.jobs[0]
    # Candidate set = {zhangsan, lisi}
    assert set(job.candidate_user_ids) == {owner.id, lisi.id}

    captured: dict = {}

    def fake_ai(messages, model, api_key, base_url, timeout_seconds):
        captured["system"] = messages[0]["content"]
        captured["user"] = messages[1]["content"]
        # Return one score per candidate
        return json.dumps({
            "scores": [
                {
                    "subject_pinyin": "zhangsan",
                    "overall": 4.2, "confidence": "high",
                    "rationale": "owner 推动闭环",
                    "dimensions": {"delivery": 4.5},
                    "evidence": [{
                        "dimension": "delivery", "polarity": "positive",
                        "confidence": "high", "source_kind": "file",
                        "source_filename": "002_lisi_act_x.md",
                        "source_file_type": "act",
                        "source_file_creator": "lisi",
                        "attribution_basis": "file_creator",
                        "quote": "implement", "explanation": "lisi delivered for owner",
                        "weight_applied": 1.0,
                    }],
                },
                {
                    "subject_pinyin": "lisi",
                    "overall": 3.8, "confidence": "medium",
                    "rationale": "执行人交付了 act",
                    "dimensions": {"delivery": 4.0},
                    # Use zhangsan's result file as positive evidence (outcome
                    # finished implies lisi's act delivered correctly). lisi's
                    # own act file as POSITIVE would trigger self-eval rejection.
                    "evidence": [{
                        "dimension": "delivery", "polarity": "positive",
                        "confidence": "medium", "source_kind": "file",
                        "source_filename": "003_zhangsan_result_x.md",
                        "source_file_type": "result",
                        "source_file_creator": "zhangsan",
                        "attribution_basis": "file_creator",
                        "quote": "done",
                        "explanation": "result outcome=finished 隐含 lisi 实现达标",
                        "weight_applied": 1.0,
                    }],
                },
            ],
            "skipped_subjects": [],
        })

    run_scoring_once(
        job,
        store=store, workspace=workspace, settings=settings,
        pivot_users=pivot_users, ai_call=fake_ai,
    )

    runs = store.list_runs(matter_id=matter_id)
    assert len(runs) == 1
    run = runs[0]
    assert run.status == "success", run.error
    # v2.1: worker stamps schema_version=2 so frontend knows to expect multi-row
    assert run.schema_version == 2

    # Both candidate scores landed
    all_scores = store.get_scores(run.run_id)
    assert len(all_scores) == 2
    by_subj = {score.subject_user_id: (score, ev) for score, ev in all_scores}
    assert owner.id in by_subj
    assert lisi.id in by_subj
    # Each subject has its own evidence row
    z_score, z_ev = by_subj[owner.id]
    l_score, l_ev = by_subj[lisi.id]
    assert z_score.delivery == 4.5
    assert l_score.delivery == 4.0
    assert len(z_ev) == 1 and len(l_ev) == 1
    # Evidence rows correctly partitioned by subject_user_id
    assert z_ev[0].subject_user_id == owner.id
    assert l_ev[0].subject_user_id == lisi.id

    # Prompt told AI about both candidates
    assert "zhangsan" in captured["user"]
    assert "lisi" in captured["user"]


def test_e2e_multi_subject_get_score_falls_back_to_first_when_owner_not_scored(
    workspace, store, settings, pivot_users, owner, lisi,
):
    """v2.1: owner has no think/act file in this matter, only lisi does.
    AI scores lisi only. get_score(run_id) returns lisi's score (fallback
    when primary subject has no row), so admin UI doesn't show a blank."""
    # Seed a matter where the only think/act creator is lisi (zhangsan
    # only has the result file, which is not a candidate-producing type)
    matter_id = "lisi-only"
    category = "Pivot"
    rel_dir = f"discussions/{category}/{matter_id}"
    data = {
        "matter": {
            "id": matter_id, "title": "lisi only",
            "current_status": "finished",
            "owner": "zhangsan",
            "created_at": "2026-04-20T10:00:00+08:00",
            "updated_at": "2026-04-29T18:30:00+08:00",
        },
        "timeline": [
            {
                "file": f"{rel_dir}/001_lisi_act_x.md",
                "type": "act", "creator": "lisi", "owner": "lisi",
                "summary": "do work",
                "created_at": "2026-04-22T11:00:00+08:00",
            },
            # zhangsan verifies lisi's act — provides legitimate positive
            # evidence for lisi without tripping self-eval rejection.
            {
                "file": f"{rel_dir}/002_zhangsan_verify_x.md",
                "type": "verify", "creator": "zhangsan", "owner": "zhangsan",
                "summary": "passed",
                "created_at": "2026-04-26T09:00:00+08:00",
                "verifications": [{
                    "target": f"{rel_dir}/001_lisi_act_x.md",
                    "judgement": "passed", "comment": "ok",
                }],
            },
            {
                "file": f"{rel_dir}/003_zhangsan_result_x.md",
                "type": "result", "creator": "zhangsan", "owner": "zhangsan",
                "summary": "done", "outcome": "finished",
                "created_at": "2026-04-29T18:30:00+08:00",
                "status_change": {"from": "executing", "to": "finished"},
            },
        ],
    }
    (workspace.index_dir / f"{matter_id}.index.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True), encoding="utf-8",
    )

    queue = _CapturingQueue()
    unsub = install(
        workspace=workspace, settings=settings,
        pivot_users=pivot_users, queue=queue,
    )
    try:
        emit(
            TOPIC_RESULT_CREATED,
            matter_id=matter_id, actor="zhangsan",
            payload={"outcome": "finished"},
        )
    finally:
        unsub()
    job = queue.jobs[0]
    # zhangsan is owner but has no think/act; only lisi is a candidate.
    assert set(job.candidate_user_ids) == {lisi.id}

    def fake_ai(messages, model, api_key, base_url, timeout_seconds):
        return json.dumps({
            "scores": [{
                "subject_pinyin": "lisi",
                "overall": 4.0, "confidence": "high",
                "rationale": "...",
                "dimensions": {"delivery": 4.0},
                # zhangsan's verify (passed) is legitimate positive evidence
                # for lisi's delivery — attribution_basis=verify_outcome.
                "evidence": [{
                    "dimension": "delivery", "polarity": "positive",
                    "confidence": "high", "source_kind": "file",
                    "source_filename": "002_zhangsan_verify_x.md",
                    "source_file_type": "verify",
                    "source_file_creator": "zhangsan",
                    "attribution_basis": "verify_outcome",
                    "quote": "passed", "explanation": "verify 通过",
                    "weight_applied": 1.0,
                }],
            }],
            "skipped_subjects": [],
        })

    run_scoring_once(
        job,
        store=store, workspace=workspace, settings=settings,
        pivot_users=pivot_users, ai_call=fake_ai,
    )
    runs = store.list_runs(matter_id=matter_id)
    assert runs[0].status == "success"

    # get_score falls back to lisi's score (run.subject_user_id was owner.id
    # but no row exists for owner; first available row is lisi's)
    got = store.get_score(runs[0].run_id)
    assert got is not None
    score, _ = got
    assert score.subject_user_id == lisi.id
    assert score.delivery == 4.0
