from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest
import yaml

from server.db import Database
from server.pivot_users import PivotUserRepo
from server.scoring.store import ScoringJob, ScoringStore
from server.scoring.trigger import KEY_MODEL, KEY_TIMEOUT_SECONDS
from server.scoring.worker import (
    DEFAULT_TIMEOUT_SECONDS,
    ScoringQueue,
    ScoringWorker,
    compute_timeline_hash,
    run_scoring_once,
)
from server.settings import SettingsRepo


# ---------- fixtures ----------


class _StubWorkspace:
    def __init__(self, root: Path) -> None:
        self.path = root
        (root / "index").mkdir(parents=True, exist_ok=True)

    @property
    def index_dir(self) -> Path:
        return self.path / "index"


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.db")


@pytest.fixture
def store(db):
    return ScoringStore(db)


@pytest.fixture
def pivot_users(db):
    return PivotUserRepo(db)


@pytest.fixture
def settings(db):
    s = SettingsRepo(db)
    # Configure AI endpoint so most tests can succeed
    s.set("ai.openrouter_api_key", "test-key")
    s.set("ai.base_url", "https://api.test")
    s.set("ai.model", "test-model")
    return s


@pytest.fixture
def workspace(tmp_path):
    return _StubWorkspace(tmp_path)


@pytest.fixture
def owner(pivot_users):
    return pivot_users.create(
        display_name="张三", pinyin="zhangsan", email=None, avatar_url="",
    )


# ---------- helpers ----------


def _write_matter(
    workspace, matter_id: str, *, owner_pinyin: str = "zhangsan", category="eng",
) -> dict:
    """Write a finished matter index. Returns the data dict for hashing tests."""
    data = {
        "matter": {
            "id": matter_id,
            "title": "客户验收",
            "current_status": "finished",
            "owner": owner_pinyin,
            "created_at": "2026-04-20T10:00:00+08:00",
            "updated_at": "2026-04-29T18:30:00+08:00",
        },
        "timeline": [
            {
                "file": f"discussions/{category}/{matter_id}/001_zhangsan_act_xx.md",
                "type": "act", "creator": "zhangsan", "owner": "zhangsan",
                "summary": "完成接口对接",
                "created_at": "2026-04-20T10:00:00+08:00",
            },
            {
                "file": f"discussions/{category}/{matter_id}/003_zhangsan_result_xx.md",
                "type": "result", "creator": "zhangsan", "owner": "zhangsan",
                "summary": "客户已接受", "outcome": "finished",
                "created_at": "2026-04-29T18:30:00+08:00",
                "status_change": {"from": "executing", "to": "finished"},
            },
        ],
    }
    path = workspace.index_dir / f"{matter_id}.index.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return data


def _job(owner_id: str, *, matter_id="m", triggered_by="auto") -> ScoringJob:
    return ScoringJob(
        matter_id=matter_id,
        matter_category="eng",
        subject_user_id=owner_id,
        triggered_by=triggered_by,
        triggered_actor_id=owner_id,
    )


def _good_ai_output(subject="zhangsan") -> str:
    """A valid AI output that passes parse_and_validate against the matter
    written by _write_matter."""
    return json.dumps({
        "scores": [{
            "subject_pinyin": subject,
            "overall": 4.2,
            "confidence": "high",
            "rationale": "...",
            "dimensions": {
                "delivery": 4.5,
                "accountability": 4.0,
                "collaboration": None,
                "judgment": None,
                "process": 4.0,
            },
            "evidence": [
                {
                    "dimension": "delivery", "polarity": "positive", "confidence": "high",
                    "source_kind": "file",
                    "source_filename": "001_zhangsan_act_xx.md",
                    "source_file_type": "act",
                    "quote": "interface delivered", "explanation": "...",
                    "weight_applied": 1.0,
                },
                {
                    "dimension": "accountability", "polarity": "positive", "confidence": "high",
                    "source_kind": "file",
                    "source_filename": "003_zhangsan_result_xx.md",
                    "source_file_type": "result",
                    "quote": "customer accepted", "explanation": "...",
                    "weight_applied": 1.0,
                },
                {
                    "dimension": "process", "polarity": "positive", "confidence": "medium",
                    "source_kind": "file",
                    "source_filename": "003_zhangsan_result_xx.md",
                    "source_file_type": "result",
                    "quote": "files complete", "explanation": "...",
                    "weight_applied": 1.0,
                },
            ],
        }],
        "skipped_subjects": [],
    })


# ---------- compute_timeline_hash ----------


def test_timeline_hash_stable_same_input():
    a = {"matter": {"id": "x"}, "timeline": [{"file": "a", "type": "act"}]}
    b = {"matter": {"id": "x"}, "timeline": [{"file": "a", "type": "act"}]}
    assert compute_timeline_hash(a) == compute_timeline_hash(b)


def test_timeline_hash_changes_with_content():
    a = {"matter": {"id": "x"}, "timeline": [{"file": "a", "type": "act"}]}
    b = {"matter": {"id": "x"}, "timeline": [{"file": "a", "type": "verify"}]}
    assert compute_timeline_hash(a) != compute_timeline_hash(b)


# ---------- run_scoring_once happy path ----------


def test_run_scoring_once_success(store, workspace, settings, pivot_users, owner):
    _write_matter(workspace, "m")

    def fake_ai(messages, model, api_key, base_url, timeout_seconds):
        assert "zhangsan" in messages[0]["content"]  # subject baked in
        return _good_ai_output()

    run_scoring_once(
        _job(owner.id), store=store, workspace=workspace,
        settings=settings, pivot_users=pivot_users, ai_call=fake_ai,
    )

    runs = store.list_runs()
    assert len(runs) == 1
    assert runs[0].status == "success"
    got = store.get_score(runs[0].run_id)
    assert got is not None
    score, evidence = got
    assert score.overall == 4.2
    assert score.subject_user_id == owner.id
    assert len(evidence) == 3


def test_run_scoring_once_uses_scoring_model_override(
    store, workspace, settings, pivot_users, owner,
):
    _write_matter(workspace, "m")
    settings.set(KEY_MODEL, "override-model")

    captured: dict = {}
    def fake_ai(messages, model, api_key, base_url, timeout_seconds):
        captured["model"] = model
        return _good_ai_output()

    run_scoring_once(
        _job(owner.id), store=store, workspace=workspace,
        settings=settings, pivot_users=pivot_users, ai_call=fake_ai,
    )
    assert captured["model"] == "override-model"
    assert store.list_runs()[0].model == "override-model"


def test_run_scoring_once_uses_default_model_when_override_blank(
    store, workspace, settings, pivot_users, owner,
):
    _write_matter(workspace, "m")
    settings.set(KEY_MODEL, "   ")  # whitespace = blank

    captured: dict = {}
    def fake_ai(messages, model, api_key, base_url, timeout_seconds):
        captured["model"] = model
        return _good_ai_output()

    run_scoring_once(
        _job(owner.id), store=store, workspace=workspace,
        settings=settings, pivot_users=pivot_users, ai_call=fake_ai,
    )
    assert captured["model"] == "test-model"  # from main ai.model


def test_run_scoring_once_uses_configured_timeout(
    store, workspace, settings, pivot_users, owner,
):
    _write_matter(workspace, "m")
    settings.set(KEY_TIMEOUT_SECONDS, "60")

    captured: dict = {}
    def fake_ai(messages, model, api_key, base_url, timeout_seconds):
        captured["timeout"] = timeout_seconds
        return _good_ai_output()

    run_scoring_once(
        _job(owner.id), store=store, workspace=workspace,
        settings=settings, pivot_users=pivot_users, ai_call=fake_ai,
    )
    assert captured["timeout"] == 60.0


def test_run_scoring_once_falls_back_to_default_on_invalid_timeout(
    store, workspace, settings, pivot_users, owner,
):
    _write_matter(workspace, "m")
    settings.set(KEY_TIMEOUT_SECONDS, "not-a-number")

    captured: dict = {}
    def fake_ai(messages, model, api_key, base_url, timeout_seconds):
        captured["timeout"] = timeout_seconds
        return _good_ai_output()

    run_scoring_once(
        _job(owner.id), store=store, workspace=workspace,
        settings=settings, pivot_users=pivot_users, ai_call=fake_ai,
    )
    assert captured["timeout"] == DEFAULT_TIMEOUT_SECONDS


# ---------- skip paths (mark_skipped, no run row state-change) ----------


def test_skips_when_matter_index_missing(
    store, workspace, settings, pivot_users, owner,
):
    # No matter file written
    run_scoring_once(
        _job(owner.id, matter_id="ghost"), store=store, workspace=workspace,
        settings=settings, pivot_users=pivot_users,
        ai_call=lambda **k: pytest.fail("ai shouldn't be called"),
    )
    runs = store.list_runs()
    assert len(runs) == 1
    assert runs[0].status == "skipped"
    assert runs[0].error == "matter_not_found"


def test_skips_duplicate_timeline(store, workspace, settings, pivot_users, owner):
    _write_matter(workspace, "m")

    def fake_ai(**k):
        return _good_ai_output()

    # First run succeeds
    run_scoring_once(
        _job(owner.id), store=store, workspace=workspace,
        settings=settings, pivot_users=pivot_users, ai_call=fake_ai,
    )
    # Second auto run should skip (idempotent)
    run_scoring_once(
        _job(owner.id), store=store, workspace=workspace,
        settings=settings, pivot_users=pivot_users,
        ai_call=lambda **k: pytest.fail("ai shouldn't be called for duplicate"),
    )

    runs = store.list_runs()
    assert len(runs) == 2
    statuses = {r.status for r in runs}
    assert statuses == {"success", "skipped"}
    skipped = next(r for r in runs if r.status == "skipped")
    assert skipped.error == "duplicate_timeline"


def test_admin_rerun_creates_new_success(
    store, workspace, settings, pivot_users, owner,
):
    """Admin rerun bypasses has_success() AND the relaxed partial idx
    (which only blocks queued/running) allows a new run after prior success."""
    _write_matter(workspace, "m")
    fake_ai = lambda **k: _good_ai_output()  # noqa: E731

    # Initial auto run succeeds
    run_scoring_once(
        _job(owner.id), store=store, workspace=workspace,
        settings=settings, pivot_users=pivot_users, ai_call=fake_ai,
    )
    # Admin rerun creates a second success row (audit trail / re-evaluation)
    run_scoring_once(
        _job(owner.id, triggered_by="admin:rerun"),
        store=store, workspace=workspace,
        settings=settings, pivot_users=pivot_users, ai_call=fake_ai,
    )
    runs = store.list_runs()
    statuses = [r.status for r in runs]
    assert statuses == ["success", "success"]
    triggered = [r.triggered_by for r in runs]
    assert "admin:rerun" in triggered
    assert "auto" in triggered


def test_admin_rerun_blocked_by_in_flight_run(
    store, workspace, settings, pivot_users, owner,
):
    """Concurrent admin rerun while another run is queued/running gets race_lost."""
    _write_matter(workspace, "m")
    # Manually create a queued run to simulate in-flight state
    in_flight_id = store.start_run(
        _job(owner.id), timeline_hash="any", model="m",
    )
    store.transition_running(in_flight_id)

    # Now trigger admin rerun — partial idx blocks because matter+hash overlap
    # if hash matches. Compute the actual hash to mimic the race precisely.
    from server.matter_index import matter_index_path, read_matter_index
    from server.scoring.worker import compute_timeline_hash
    index = read_matter_index(matter_index_path(workspace.index_dir, "m"))
    real_hash = compute_timeline_hash(index)

    # Replace the in-flight row's hash to match what the rerun will compute
    with store._db.connect() as conn:
        conn.execute(
            "UPDATE matter_scoring_runs SET timeline_hash=? WHERE run_id=?",
            (real_hash, in_flight_id),
        )

    run_scoring_once(
        _job(owner.id, triggered_by="admin:rerun"),
        store=store, workspace=workspace,
        settings=settings, pivot_users=pivot_users,
        ai_call=lambda **k: pytest.fail("AI shouldn't be called"),
    )
    runs = store.list_runs()
    skipped = [r for r in runs if r.status == "skipped"]
    assert len(skipped) == 1
    assert skipped[0].error == "race_lost"


def test_skips_when_owner_missing_in_index(
    store, workspace, settings, pivot_users, owner,
):
    # Manually write index without owner field
    matter_id = "no-owner"
    data = {
        "matter": {"id": matter_id, "title": "x", "current_status": "finished"},
        "timeline": [
            {"file": f"discussions/eng/{matter_id}/001.md", "type": "result"},
        ],
    }
    path = workspace.index_dir / f"{matter_id}.index.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    run_scoring_once(
        _job(owner.id, matter_id=matter_id), store=store, workspace=workspace,
        settings=settings, pivot_users=pivot_users,
        ai_call=lambda **k: pytest.fail("shouldn't reach AI"),
    )
    runs = store.list_runs()
    assert runs[0].status == "skipped"
    assert runs[0].error == "no_owner"


# ---------- failure paths (run created, finish_run('failed')) ----------


def test_fails_when_ai_key_missing(store, workspace, pivot_users, owner, db):
    settings = SettingsRepo(db)
    # Don't set ai.openrouter_api_key
    _write_matter(workspace, "m")

    run_scoring_once(
        _job(owner.id), store=store, workspace=workspace,
        settings=settings, pivot_users=pivot_users,
        ai_call=lambda **k: pytest.fail("shouldn't reach AI"),
    )
    runs = store.list_runs()
    assert runs[0].status == "failed"
    assert runs[0].error == "ai_key_missing"


def test_fails_when_ai_raises_aierror(store, workspace, settings, pivot_users, owner):
    _write_matter(workspace, "m")
    from server.ai.client import AIError

    def fake_ai(**k):
        raise AIError("AI endpoint 503: rate limit")

    run_scoring_once(
        _job(owner.id), store=store, workspace=workspace,
        settings=settings, pivot_users=pivot_users, ai_call=fake_ai,
    )
    runs = store.list_runs()
    assert runs[0].status == "failed"
    assert "AIError" in runs[0].error


def test_fails_when_ai_times_out(store, workspace, settings, pivot_users, owner):
    _write_matter(workspace, "m")

    def fake_ai(**k):
        raise TimeoutError("ai took too long")

    run_scoring_once(
        _job(owner.id), store=store, workspace=workspace,
        settings=settings, pivot_users=pivot_users, ai_call=fake_ai,
    )
    runs = store.list_runs()
    assert runs[0].status == "failed"
    assert "TimeoutError" in runs[0].error


def test_fails_on_invalid_ai_json(store, workspace, settings, pivot_users, owner):
    _write_matter(workspace, "m")

    def fake_ai(**k):
        return "this is not json at all"

    run_scoring_once(
        _job(owner.id), store=store, workspace=workspace,
        settings=settings, pivot_users=pivot_users, ai_call=fake_ai,
    )
    runs = store.list_runs()
    assert runs[0].status == "failed"
    assert "schema_error" in runs[0].error


def test_fails_when_subject_not_owner(store, workspace, settings, pivot_users, owner):
    _write_matter(workspace, "m")

    # AI returns a score for "lisi" but matter.owner is "zhangsan"
    def fake_ai(**k):
        return _good_ai_output(subject="lisi")

    run_scoring_once(
        _job(owner.id), store=store, workspace=workspace,
        settings=settings, pivot_users=pivot_users, ai_call=fake_ai,
    )
    runs = store.list_runs()
    assert runs[0].status == "failed"
    assert "subject_not_owner" in runs[0].error


def test_fails_on_fabricated_filename(store, workspace, settings, pivot_users, owner):
    _write_matter(workspace, "m")

    def fake_ai(**k):
        out = json.loads(_good_ai_output())
        out["scores"][0]["evidence"][0]["source_filename"] = "999_fake.md"
        return json.dumps(out)

    run_scoring_once(
        _job(owner.id), store=store, workspace=workspace,
        settings=settings, pivot_users=pivot_users, ai_call=fake_ai,
    )
    runs = store.list_runs()
    assert runs[0].status == "failed"
    assert "fabricated_source_filename" in runs[0].error


def test_success_when_ai_returns_skipped_subjects(
    store, workspace, settings, pivot_users, owner,
):
    """AI explicitly skipped (insufficient evidence) — run is still success
    but no score row written."""
    _write_matter(workspace, "m")

    def fake_ai(**k):
        return json.dumps({
            "scores": [],
            "skipped_subjects": ["zhangsan"],
        })

    run_scoring_once(
        _job(owner.id), store=store, workspace=workspace,
        settings=settings, pivot_users=pivot_users, ai_call=fake_ai,
    )
    runs = store.list_runs()
    assert runs[0].status == "success"
    # No score row should exist
    assert store.get_score(runs[0].run_id) is None


# ---------- weight integration ----------


def test_weights_injected_into_prompt(
    store, workspace, settings, pivot_users, owner,
):
    """Set up a CEO weighted user; verify prompt builder sees them annotated."""
    ceo = pivot_users.create(
        display_name="CEO", pinyin="bigboss", email=None, avatar_url="",
    )
    admin = pivot_users.create(
        display_name="Admin", pinyin="admin", email=None, avatar_url="",
    )
    store.upsert_weight(
        pivot_user_id=ceo.id, weight=2.0, label="CEO",
        note=None, updated_by=admin.id,
    )
    _write_matter(workspace, "m")

    captured: dict = {}
    def fake_ai(messages, **k):
        # Find the user message
        user_msg = next(m for m in messages if m["role"] == "user")
        captured["user_content"] = user_msg["content"]
        # Return valid output to let the run complete
        return _good_ai_output()

    run_scoring_once(
        _job(owner.id), store=store, workspace=workspace,
        settings=settings, pivot_users=pivot_users, ai_call=fake_ai,
    )
    # Even though bigboss isn't in this matter timeline, the weight rule
    # prose appears in system prompt; we just verify it doesn't error
    assert store.list_runs()[0].status == "success"


# ---------- queue + worker (asyncio integration) ----------


@pytest.mark.asyncio
async def test_queue_threadsafe_enqueue_to_async_get():
    """enqueue from a non-loop thread, verify worker-side get receives it."""
    queue = ScoringQueue()
    loop = asyncio.get_running_loop()
    queue.attach(loop)

    job = ScoringJob(
        matter_id="m", matter_category="eng",
        subject_user_id="user1", triggered_by="auto",
        triggered_actor_id=None,
    )

    # enqueue from a separate thread
    t = threading.Thread(target=queue.enqueue, args=(job,))
    t.start()
    t.join()

    received = await asyncio.wait_for(queue.get(), timeout=2.0)
    assert received is not None
    assert received.matter_id == "m"


@pytest.mark.asyncio
async def test_queue_signal_stop_returns_none():
    queue = ScoringQueue()
    queue.attach(asyncio.get_running_loop())
    queue.signal_stop()
    received = await asyncio.wait_for(queue.get(), timeout=2.0)
    assert received is None


@pytest.mark.asyncio
async def test_worker_processes_job_then_exits(
    store, workspace, settings, pivot_users, owner,
):
    _write_matter(workspace, "m")
    queue = ScoringQueue()

    fake_calls: list = []
    def fake_ai(**k):
        fake_calls.append(k)
        return _good_ai_output()

    worker = ScoringWorker(
        queue=queue, store=store, workspace=workspace,
        settings=settings, pivot_users=pivot_users, ai_call=fake_ai,
    )
    await worker.start()

    queue.enqueue(_job(owner.id))
    # Give the worker time to run the job (bounded — cap at 5s)
    for _ in range(50):
        await asyncio.sleep(0.1)
        if store.list_runs():
            break

    await worker.stop()

    assert len(fake_calls) == 1
    runs = store.list_runs()
    assert len(runs) == 1
    assert runs[0].status == "success"


@pytest.mark.asyncio
async def test_worker_continues_after_one_job_fails(
    store, workspace, settings, pivot_users, owner,
):
    """If a job's AI raises, worker logs + recovers + processes the next."""
    _write_matter(workspace, "m1")
    _write_matter(workspace, "m2")
    queue = ScoringQueue()

    call_count = [0]
    def fake_ai(**k):
        call_count[0] += 1
        if call_count[0] == 1:
            from server.ai.client import AIError
            raise AIError("first call fails")
        return _good_ai_output()

    worker = ScoringWorker(
        queue=queue, store=store, workspace=workspace,
        settings=settings, pivot_users=pivot_users, ai_call=fake_ai,
    )
    await worker.start()

    queue.enqueue(_job(owner.id, matter_id="m1"))
    queue.enqueue(_job(owner.id, matter_id="m2"))

    for _ in range(50):
        await asyncio.sleep(0.1)
        if len(store.list_runs()) >= 2:
            break

    await worker.stop()

    runs = sorted(store.list_runs(), key=lambda r: r.matter_id)
    assert len(runs) == 2
    statuses_by_matter = {r.matter_id: r.status for r in runs}
    assert statuses_by_matter["m1"] == "failed"
    assert statuses_by_matter["m2"] == "success"


@pytest.mark.asyncio
async def test_queue_drops_when_unattached(caplog):
    """If enqueue() is called before attach() (rare race during boot), no crash."""
    queue = ScoringQueue()
    job = ScoringJob(
        matter_id="m", matter_category="eng",
        subject_user_id="x", triggered_by="auto",
    )
    queue.enqueue(job)  # should log warning but not raise


@pytest.mark.asyncio
async def test_queue_double_attach_raises():
    queue = ScoringQueue()
    queue.attach(asyncio.get_running_loop())
    with pytest.raises(RuntimeError, match="already attached"):
        queue.attach(asyncio.get_running_loop())
