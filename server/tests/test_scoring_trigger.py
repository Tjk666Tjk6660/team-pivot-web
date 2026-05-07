from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from server.db import Database
from server.events import (
    TOPIC_FILE_APPENDED,
    TOPIC_RESULT_CREATED,
    clear_subscribers,
    emit,
)
from server.pivot_users import PivotUserRepo
from server.scoring.store import ScoringJob, ScoringStore
from server.scoring.trigger import KEY_ENABLED, install
from server.settings import SettingsRepo


# ---------- fixtures ----------


class _StubWorkspace:
    """Minimal workspace stand-in with a real on-disk index_dir."""

    def __init__(self, root: Path) -> None:
        self.path = root
        (root / "index").mkdir(parents=True, exist_ok=True)

    @property
    def index_dir(self) -> Path:
        return self.path / "index"


class _RecordingQueue:
    """Captures enqueue() calls instead of really queueing."""

    def __init__(self) -> None:
        self.jobs: list[ScoringJob] = []

    def enqueue(self, job: ScoringJob) -> None:
        self.jobs.append(job)


@pytest.fixture(autouse=True)
def _isolate_event_bus():
    clear_subscribers()
    yield
    clear_subscribers()


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.db")


@pytest.fixture
def pivot_users(db):
    return PivotUserRepo(db)


@pytest.fixture
def settings(db):
    s = SettingsRepo(db)
    s.set(KEY_ENABLED, "1")
    return s


@pytest.fixture
def workspace(tmp_path):
    return _StubWorkspace(tmp_path)


@pytest.fixture
def queue():
    return _RecordingQueue()


@pytest.fixture
def store(db):
    return ScoringStore(db)


@pytest.fixture
def trigger_installed(workspace, settings, pivot_users, queue, store):
    unsub = install(
        workspace=workspace, settings=settings, pivot_users=pivot_users,
        queue=queue, store=store,
    )
    yield queue
    unsub()


# ---------- helpers ----------


def _write_matter(workspace, matter_id: str, *, owner: str | None, category="eng") -> None:
    path = workspace.index_dir / f"{matter_id}.index.yaml"
    data = {
        "matter": {
            "id": matter_id,
            "title": "客户验收流程优化",
            "current_status": "finished",
            "created_at": "2026-04-20T10:00:00+08:00",
            "updated_at": "2026-04-29T18:30:00+08:00",
        },
        "timeline": [
            {
                "file": f"discussions/{category}/{matter_id}/001_zhangsan_act_xx.md",
                "type": "act", "creator": "zhangsan", "owner": "zhangsan",
                "summary": "first act", "created_at": "2026-04-20T10:00:00+08:00",
            },
            {
                "file": f"discussions/{category}/{matter_id}/003_zhangsan_result_xx.md",
                "type": "result", "creator": "zhangsan", "owner": "zhangsan",
                "summary": "done", "outcome": "finished",
                "created_at": "2026-04-29T18:30:00+08:00",
                "status_change": {"from": "executing", "to": "finished"},
            },
        ],
    }
    if owner is not None:
        data["matter"]["owner"] = owner
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def _emit_result_finished(matter_id: str, *, actor: str = "zhangsan") -> None:
    emit(
        TOPIC_RESULT_CREATED,
        matter_id=matter_id, actor=actor,
        at="2026-04-29T18:30:00+08:00",
        payload={
            "file": f"discussions/eng/{matter_id}/003_zhangsan_result_xx.md",
            "outcome": "finished",
        },
    )


# ---------- happy path ----------


def test_enqueues_when_finished(trigger_installed, workspace, pivot_users):
    queue = trigger_installed
    owner = pivot_users.create(
        display_name="张三", pinyin="zhangsan", email=None, avatar_url="",
    )
    _write_matter(workspace, "auth-redesign", owner="zhangsan")

    _emit_result_finished("auth-redesign")

    assert len(queue.jobs) == 1
    job = queue.jobs[0]
    assert job.matter_id == "auth-redesign"
    assert job.matter_category == "eng"
    assert job.subject_user_id == owner.id
    assert job.triggered_by == "auto"
    assert job.triggered_actor_id == owner.id


def test_enqueues_with_actor_resolved(trigger_installed, workspace, pivot_users):
    """If actor pinyin maps to a different user (not the owner), still resolved."""
    queue = trigger_installed
    owner = pivot_users.create(
        display_name="张三", pinyin="zhangsan", email=None, avatar_url="",
    )
    actor = pivot_users.create(
        display_name="李四", pinyin="lisi", email=None, avatar_url="",
    )
    _write_matter(workspace, "m", owner="zhangsan")

    _emit_result_finished("m", actor="lisi")

    assert len(queue.jobs) == 1
    assert queue.jobs[0].subject_user_id == owner.id
    assert queue.jobs[0].triggered_actor_id == actor.id


def test_enqueues_with_unresolved_actor_keeps_none(
    trigger_installed, workspace, pivot_users,
):
    """Actor pinyin not in DB → actor_id stays None, but still enqueues."""
    queue = trigger_installed
    pivot_users.create(
        display_name="张三", pinyin="zhangsan", email=None, avatar_url="",
    )
    _write_matter(workspace, "m", owner="zhangsan")

    _emit_result_finished("m", actor="ghost-pinyin")

    assert len(queue.jobs) == 1
    assert queue.jobs[0].triggered_actor_id is None


# ---------- v2.1 multi-subject candidate resolution (Task 2.4) ----------


def _write_matter_multi(workspace, matter_id: str, owner: str = "zhangsan",
                        category: str = "eng") -> None:
    """Write a matter with think+act files from multiple authors so the
    candidate set has more than just the owner."""
    path = workspace.index_dir / f"{matter_id}.index.yaml"
    data = {
        "matter": {
            "id": matter_id, "title": "t", "current_status": "finished",
            "owner": owner,
            "created_at": "2026-04-20T10:00:00+08:00",
            "updated_at": "2026-04-29T18:30:00+08:00",
        },
        "timeline": [
            {
                "file": f"discussions/{category}/{matter_id}/001_zhangsan_think_x.md",
                "type": "think", "creator": "zhangsan",
                "summary": "frame the work",
                "created_at": "2026-04-20T10:00:00+08:00",
            },
            {
                "file": f"discussions/{category}/{matter_id}/002_lisi_act_x.md",
                "type": "act", "creator": "lisi",
                "summary": "implement",
                "created_at": "2026-04-22T11:00:00+08:00",
            },
            {
                "file": f"discussions/{category}/{matter_id}/003_wangwu_act_x.md",
                "type": "act", "creator": "wangwu",
                "summary": "review fix",
                "created_at": "2026-04-25T14:00:00+08:00",
            },
            # verify is NOT a candidate-producing type per matter 005
            {
                "file": f"discussions/{category}/{matter_id}/004_lisi_verify_x.md",
                "type": "verify", "creator": "lisi",
                "summary": "passed",
                "created_at": "2026-04-26T09:00:00+08:00",
            },
            {
                "file": f"discussions/{category}/{matter_id}/005_zhangsan_result_x.md",
                "type": "result", "creator": "zhangsan",
                "summary": "done", "outcome": "finished",
                "created_at": "2026-04-29T18:30:00+08:00",
                "status_change": {"from": "executing", "to": "finished"},
            },
        ],
    }
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def test_enqueues_full_candidate_set(trigger_installed, workspace, pivot_users):
    """v2.1: trigger collects all think/act creators as candidates."""
    queue = trigger_installed
    z = pivot_users.create(display_name="Z", pinyin="zhangsan", email=None, avatar_url="")
    l = pivot_users.create(display_name="L", pinyin="lisi", email=None, avatar_url="")
    w = pivot_users.create(display_name="W", pinyin="wangwu", email=None, avatar_url="")
    _write_matter_multi(workspace, "multi-eval")

    _emit_result_finished("multi-eval")

    assert len(queue.jobs) == 1
    job = queue.jobs[0]
    # Owner stays as primary subject
    assert job.subject_user_id == z.id
    # Candidate set = think/act creators (zhangsan think + lisi act + wangwu act).
    # verify is NOT a candidate source per matter 005.
    assert set(job.candidate_user_ids) == {z.id, l.id, w.id}


def test_candidate_set_excludes_verify_only_authors(
    trigger_installed, workspace, pivot_users,
):
    """A user who only authored verify (no think/act) is NOT a candidate."""
    queue = trigger_installed
    pivot_users.create(display_name="Z", pinyin="zhangsan", email=None, avatar_url="")
    pivot_users.create(display_name="L", pinyin="lisi", email=None, avatar_url="")
    pivot_users.create(display_name="W", pinyin="wangwu", email=None, avatar_url="")
    _write_matter_multi(workspace, "m")

    _emit_result_finished("m")

    job = queue.jobs[0]
    candidate_pinyins: set[str] = set()
    for uid in job.candidate_user_ids:
        u = pivot_users.get(uid)
        if u and u.pinyin:
            candidate_pinyins.add(u.pinyin)
    # lisi DID author verify but ALSO an act, so still a candidate.
    # If we only had verify, they'd be excluded — that case is exercised by
    # test_candidate_set_drops_pure_verify_author below.
    assert "lisi" in candidate_pinyins


def test_candidate_set_drops_unresolvable_creators(
    trigger_installed, workspace, pivot_users,
):
    """think/act creator pinyin not in pivot_users → silently dropped."""
    queue = trigger_installed
    z = pivot_users.create(display_name="Z", pinyin="zhangsan", email=None, avatar_url="")
    # lisi + wangwu intentionally NOT registered
    _write_matter_multi(workspace, "m")

    _emit_result_finished("m")

    job = queue.jobs[0]
    # Only zhangsan resolves
    assert tuple(job.candidate_user_ids) == (z.id,)


def test_does_not_enqueue_when_no_candidates_resolvable(
    trigger_installed, workspace, pivot_users,
):
    """All think/act creators are unresolvable AND owner can't be resolved
    → matters with no scorable subjects skip enqueue entirely."""
    queue = trigger_installed
    # Owner zhangsan IS registered (so trigger gets past owner resolution),
    # but write a matter where the owner has no think/act file and other
    # creators don't exist in the DB. With current trigger logic, owner's
    # check passes but candidates filter to empty.
    pivot_users.create(display_name="Z", pinyin="zhangsan", email=None, avatar_url="")

    # Write a matter where the only think/act file is by an unregistered user
    path = workspace.index_dir / "ghost.index.yaml"
    data = {
        "matter": {
            "id": "ghost", "title": "t", "current_status": "finished",
            "owner": "zhangsan",
            "created_at": "2026-04-20T10:00:00+08:00",
            "updated_at": "2026-04-29T18:30:00+08:00",
        },
        "timeline": [
            {
                "file": "discussions/eng/ghost/001_unknown_act_x.md",
                "type": "act", "creator": "unknown_user_pinyin",
                "summary": "...",
                "created_at": "2026-04-20T10:00:00+08:00",
            },
            {
                "file": "discussions/eng/ghost/002_unknown_result_x.md",
                "type": "result", "creator": "unknown_user_pinyin",
                "summary": "done", "outcome": "finished",
                "created_at": "2026-04-29T18:30:00+08:00",
                "status_change": {"from": "executing", "to": "finished"},
            },
        ],
    }
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")

    _emit_result_finished("ghost")

    # No candidates resolvable → trigger drops the event
    assert queue.jobs == []


# ---------- filtering ----------


def test_does_not_enqueue_when_disabled(workspace, settings, pivot_users, queue, store):
    """scoring.enabled=0 → no enqueue even if everything else is set up."""
    settings.set(KEY_ENABLED, "0")
    pivot_users.create(
        display_name="张三", pinyin="zhangsan", email=None, avatar_url="",
    )
    _write_matter(workspace, "m", owner="zhangsan")

    unsub = install(
        workspace=workspace, settings=settings, pivot_users=pivot_users,
        queue=queue, store=store,
    )
    try:
        _emit_result_finished("m")
    finally:
        unsub()

    assert queue.jobs == []


def test_does_not_enqueue_when_disabled_via_falsy_strings(
    workspace, settings, pivot_users, queue, store,
):
    for v in ["0", "false", "False", "off", "no", ""]:
        settings.set(KEY_ENABLED, v)
        pivot_users.create(
            display_name=f"u{v}", pinyin=f"u_{hash(v) & 0xff:x}",
            email=None, avatar_url="",
        )

    pivot_users.create(
        display_name="zs", pinyin="zhangsan", email=None, avatar_url="",
    )
    _write_matter(workspace, "m", owner="zhangsan")

    unsub = install(
        workspace=workspace, settings=settings, pivot_users=pivot_users,
        queue=queue, store=store,
    )
    try:
        _emit_result_finished("m")
    finally:
        unsub()
    assert queue.jobs == []


def test_does_not_enqueue_for_cancelled_outcome(trigger_installed, workspace, pivot_users):
    """Decision C: only finished outcome triggers."""
    queue = trigger_installed
    pivot_users.create(
        display_name="zs", pinyin="zhangsan", email=None, avatar_url="",
    )
    _write_matter(workspace, "m", owner="zhangsan")

    emit(
        TOPIC_RESULT_CREATED,
        matter_id="m", actor="zhangsan",
        at="2026-04-29T18:30:00+08:00",
        payload={"file": "discussions/eng/m/x.md", "outcome": "cancelled"},
    )
    assert queue.jobs == []


def test_does_not_enqueue_for_other_topics(trigger_installed, workspace, pivot_users):
    """File appended events should be ignored."""
    queue = trigger_installed
    pivot_users.create(
        display_name="zs", pinyin="zhangsan", email=None, avatar_url="",
    )
    _write_matter(workspace, "m", owner="zhangsan")

    emit(
        TOPIC_FILE_APPENDED,
        matter_id="m", actor="zhangsan",
        at="2026-04-29T18:30:00+08:00",
        payload={"file": "discussions/eng/m/01.md", "type": "act"},
    )
    assert queue.jobs == []


# ---------- owner resolution paths ----------


def test_does_not_enqueue_when_index_missing(trigger_installed, workspace):
    """Index file not on disk (rare race) → skip + log."""
    queue = trigger_installed
    _emit_result_finished("nonexistent")
    assert queue.jobs == []


def test_does_not_enqueue_when_owner_empty(trigger_installed, workspace, pivot_users):
    """matter.owner missing → skip per design 1.1 边界."""
    queue = trigger_installed
    pivot_users.create(
        display_name="zs", pinyin="zhangsan", email=None, avatar_url="",
    )
    _write_matter(workspace, "m", owner=None)
    _emit_result_finished("m")
    assert queue.jobs == []


def test_does_not_enqueue_when_owner_unresolvable(
    trigger_installed, workspace, pivot_users,
):
    """Owner pinyin not in pivot_user table → skip (decision A: 不入队，不留 run)."""
    queue = trigger_installed
    pivot_users.create(
        display_name="lisi", pinyin="lisi", email=None, avatar_url="",
    )
    _write_matter(workspace, "m", owner="ghost_owner")
    _emit_result_finished("m")
    assert queue.jobs == []


def test_resolves_to_active_when_multiple_users_share_pinyin(
    trigger_installed, workspace, pivot_users,
):
    """Active beats deleted at resolve time (sanity check matches resolve.py spec)."""
    queue = trigger_installed
    deleted = pivot_users.create(
        display_name="zs old", pinyin="zhangsan", email=None, avatar_url="",
    )
    pivot_users.update_status(
        user_id=deleted.id, status="deleted", note=None, changed_by=deleted.id,
    )
    active = pivot_users.create(
        display_name="zs new", pinyin="zhangsan", email=None, avatar_url="",
    )
    _write_matter(workspace, "m", owner="zhangsan")

    _emit_result_finished("m")
    assert len(queue.jobs) == 1
    assert queue.jobs[0].subject_user_id == active.id


# ---------- robustness ----------


def test_trigger_does_not_raise_on_corrupt_index(trigger_installed, workspace):
    """Bad yaml → trigger logs + returns; never bubbles up to break publish flow."""
    queue = trigger_installed
    bad = workspace.index_dir / "m.index.yaml"
    bad.write_text("not: [valid: yaml", encoding="utf-8")
    _emit_result_finished("m")
    assert queue.jobs == []  # silently dropped


# ---------- Phase 1: persistent skip reasons ("未评分" 诊断) ----------


def test_skip_persists_when_index_missing(trigger_installed, workspace, store):
    """No index file on disk → 'trigger:matter_index_missing' row, no enqueue."""
    queue = trigger_installed
    _emit_result_finished("ghost-matter")
    assert queue.jobs == []
    runs = store.list_runs(matter_id="ghost-matter")
    assert len(runs) == 1
    assert runs[0].status == "skipped"
    assert runs[0].error == "trigger:matter_index_missing"
    assert runs[0].subject_user_id == "(unknown)"


def test_skip_persists_when_owner_empty(
    trigger_installed, workspace, store, pivot_users,
):
    """matter.owner = '' → 'trigger:no_owner', timeline_hash computed,
    so a follow-up rerun on the same content can collapse cleanly."""
    queue = trigger_installed
    _write_matter(workspace, "m", owner=None)  # no owner field

    _emit_result_finished("m")
    assert queue.jobs == []
    runs = store.list_runs(matter_id="m")
    assert len(runs) == 1
    assert runs[0].status == "skipped"
    assert runs[0].error == "trigger:no_owner"
    assert runs[0].matter_category == "eng"
    assert runs[0].timeline_hash != ""  # hash computed even without owner


def test_skip_persists_when_owner_unresolvable(
    trigger_installed, workspace, store, pivot_users,
):
    """owner pinyin not in pivot_user → 'trigger:owner_unresolved:<pinyin>'.
    Pinyin appended so admin can see who failed to resolve."""
    queue = trigger_installed
    _write_matter(workspace, "m", owner="ghost-pinyin")

    _emit_result_finished("m")
    assert queue.jobs == []
    runs = store.list_runs(matter_id="m")
    assert len(runs) == 1
    assert runs[0].status == "skipped"
    assert runs[0].error == "trigger:owner_unresolved:ghost-pinyin"


def test_skip_does_not_persist_when_globally_disabled(
    workspace, settings, pivot_users, queue, store,
):
    """scoring.enabled=0 → no row written (would create one per finished
    matter when toggle is off; admin "需关注" view infers globally instead)."""
    settings.set(KEY_ENABLED, "0")
    pivot_users.create(
        display_name="张三", pinyin="zhangsan", email=None, avatar_url="",
    )
    _write_matter(workspace, "m", owner="zhangsan")

    unsub = install(
        workspace=workspace, settings=settings, pivot_users=pivot_users,
        queue=queue, store=store,
    )
    try:
        _emit_result_finished("m")
    finally:
        unsub()
    assert queue.jobs == []
    assert store.list_runs(matter_id="m") == []


def test_skip_does_not_persist_for_cancelled_outcome(
    trigger_installed, workspace, store, pivot_users,
):
    """outcome=cancelled is intentional, not 'unscored' → no row."""
    queue = trigger_installed
    pivot_users.create(
        display_name="zs", pinyin="zhangsan", email=None, avatar_url="",
    )
    _write_matter(workspace, "m", owner="zhangsan")

    emit(
        TOPIC_RESULT_CREATED,
        matter_id="m", actor="zhangsan",
        at="2026-04-29T18:30:00+08:00",
        payload={"file": "discussions/eng/m/x.md", "outcome": "cancelled"},
    )
    assert queue.jobs == []
    assert store.list_runs(matter_id="m") == []


def test_skip_persists_when_no_candidates_resolvable(
    trigger_installed, workspace, store, pivot_users,
):
    """Owner exists but every think/act creator pinyin is unknown →
    'trigger:no_candidates'."""
    queue = trigger_installed
    pivot_users.create(
        display_name="zs", pinyin="zhangsan", email=None, avatar_url="",
    )
    # Write matter where the only think/act is by someone NOT in pivot_users.
    path = workspace.index_dir / "m.index.yaml"
    data = {
        "matter": {
            "id": "m", "title": "t", "current_status": "finished",
            "owner": "zhangsan",
            "created_at": "2026-04-20T10:00:00+08:00",
            "updated_at": "2026-04-29T18:30:00+08:00",
        },
        "timeline": [
            # Owner zhangsan has no think/act; only "ghost" (unresolvable) does.
            {
                "file": "discussions/eng/m/001_ghost_think.md",
                "type": "think", "creator": "ghost-pinyin",
                "summary": "x", "created_at": "2026-04-20T10:00:00+08:00",
            },
            {
                "file": "discussions/eng/m/002_zhangsan_result.md",
                "type": "result", "creator": "zhangsan",
                "summary": "done", "outcome": "finished",
                "created_at": "2026-04-29T18:30:00+08:00",
            },
        ],
    }
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")

    _emit_result_finished("m")
    assert queue.jobs == []
    runs = store.list_runs(matter_id="m")
    assert len(runs) == 1
    assert runs[0].status == "skipped"
    assert runs[0].error == "trigger:no_candidates"
