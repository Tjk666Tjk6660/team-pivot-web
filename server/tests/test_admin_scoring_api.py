"""End-to-end API tests for /api/admin/scoring/*.

The new auth model uses a session cookie + role='admin' check (per
server/auth/deps.py.make_require_admin_user_cookie). For tests we inject a
stub admin_user_dep that returns a real PivotUser with role='admin'.

A "non-admin" stub is used to verify the 403 path; a fixture that depends on
session/cookies is overkill for unit-level coverage and would require booting
the full auth stack.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from server.api.admin_scoring import build_router
from server.db import Database
from server.pivot_users import PivotUser, PivotUserRepo
from server.scoring.store import ScoringJob, ScoringStore
from server.scoring.trigger import (
    KEY_ENABLED,
    KEY_MODEL,
    KEY_TIMEOUT_SECONDS,
    KEY_VISIBILITY,
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


class _RecordingQueue:
    def __init__(self) -> None:
        self.jobs: list[ScoringJob] = []

    def enqueue(self, job: ScoringJob) -> None:
        self.jobs.append(job)


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
    return SettingsRepo(db)


@pytest.fixture
def workspace(tmp_path):
    return _StubWorkspace(tmp_path)


@pytest.fixture
def queue():
    return _RecordingQueue()


@pytest.fixture
def admin_user(pivot_users):
    """A real PivotUser with role='admin' — passed back by the dep stub."""
    return pivot_users.create(
        display_name="Admin", pinyin="admin_user", email="admin@x.test",
        avatar_url="", role="admin",
    )


@pytest.fixture
def app(store, queue, workspace, settings, pivot_users, admin_user):
    def admin_dep() -> PivotUser:
        return admin_user

    app = FastAPI()
    app.include_router(
        build_router(
            store=store, queue=queue, workspace=workspace,
            settings=settings, pivot_users=pivot_users,
            admin_user_dep=admin_dep,
        )
    )
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def _admin_headers() -> dict[str, str]:
    """Kept for compatibility with old test cases — new auth doesn't need
    headers, the cookie/dep injection handles it. Returning empty dict so
    explicit pass-through still works."""
    return {}


def _build_app_with_dep(
    *, store, queue, workspace, settings, pivot_users, admin_dep,
) -> FastAPI:
    """Build a fresh app instance with a custom admin_user_dep — used by
    the gate tests to simulate non-admin / unauthenticated callers."""
    app = FastAPI()
    app.include_router(
        build_router(
            store=store, queue=queue, workspace=workspace,
            settings=settings, pivot_users=pivot_users,
            admin_user_dep=admin_dep,
        )
    )
    return app


def _write_matter(workspace, matter_id, *, owner_pinyin="zhangsan", title="客户验收") -> None:
    data = {
        "matter": {
            "id": matter_id, "title": title,
            "current_status": "finished", "owner": owner_pinyin,
            "created_at": "2026-04-20T10:00:00+08:00",
            "updated_at": "2026-04-29T18:30:00+08:00",
        },
        "timeline": [
            {
                "file": f"discussions/eng/{matter_id}/001.md",
                "type": "act", "creator": "zhangsan", "owner": "zhangsan",
                "summary": "first", "created_at": "2026-04-20T10:00:00+08:00",
            },
            {
                "file": f"discussions/eng/{matter_id}/003.md",
                "type": "result", "creator": "zhangsan", "owner": "zhangsan",
                "summary": "done", "outcome": "finished",
                "created_at": "2026-04-29T18:30:00+08:00",
            },
        ],
    }
    (workspace.index_dir / f"{matter_id}.index.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True), encoding="utf-8",
    )


def _job(owner_id: str, *, matter_id="m") -> ScoringJob:
    return ScoringJob(
        matter_id=matter_id, matter_category="eng",
        subject_user_id=owner_id, triggered_by="auto",
    )


# ---------- admin gate ----------


def test_admin_gate_rejects_unauthenticated(
    store, queue, workspace, settings, pivot_users,
):
    """No session → 401 (mirrors make_require_admin_user_cookie behavior)."""
    def no_auth():
        raise HTTPException(status_code=401, detail="not logged in")

    app = _build_app_with_dep(
        store=store, queue=queue, workspace=workspace,
        settings=settings, pivot_users=pivot_users, admin_dep=no_auth,
    )
    client = TestClient(app)
    r = client.get("/api/admin/scoring/config")
    assert r.status_code == 401


def test_admin_gate_rejects_non_admin_role(
    store, queue, workspace, settings, pivot_users,
):
    """Logged-in member (not admin) → 403 admin_required."""
    def non_admin():
        raise HTTPException(status_code=403, detail="admin_required")

    app = _build_app_with_dep(
        store=store, queue=queue, workspace=workspace,
        settings=settings, pivot_users=pivot_users, admin_dep=non_admin,
    )
    client = TestClient(app)
    r = client.get("/api/admin/scoring/config")
    assert r.status_code == 403
    assert r.json()["detail"] == "admin_required"


def test_admin_gate_accepts_admin(client):
    r = client.get("/api/admin/scoring/config", headers=_admin_headers())
    assert r.status_code == 200


# ---------- config GET ----------


def test_get_config_defaults(client):
    r = client.get("/api/admin/scoring/config", headers=_admin_headers())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {
        "enabled": False,
        "visibility": "admin_only",
        "model": "",
        "timeout_seconds": 180,
    }


def test_get_config_with_set_values(client, settings):
    settings.set(KEY_ENABLED, "1")
    settings.set(KEY_VISIBILITY, "subjects")
    settings.set(KEY_MODEL, "anthropic/claude-sonnet-4-5")
    settings.set(KEY_TIMEOUT_SECONDS, "60")
    r = client.get("/api/admin/scoring/config", headers=_admin_headers())
    body = r.json()
    assert body["enabled"] is True
    assert body["visibility"] == "subjects"
    assert body["model"] == "anthropic/claude-sonnet-4-5"
    assert body["timeout_seconds"] == 60


def test_get_config_falls_back_for_invalid_visibility(client, settings):
    settings.set(KEY_VISIBILITY, "bogus")
    r = client.get("/api/admin/scoring/config", headers=_admin_headers())
    assert r.json()["visibility"] == "admin_only"


def test_get_config_falls_back_for_invalid_timeout(client, settings):
    settings.set(KEY_TIMEOUT_SECONDS, "not-a-number")
    r = client.get("/api/admin/scoring/config", headers=_admin_headers())
    assert r.json()["timeout_seconds"] == 180


# ---------- config PUT ----------


def test_put_config_persists(client, settings):
    r = client.put(
        "/api/admin/scoring/config",
        headers=_admin_headers(),
        json={
            "enabled": True,
            "visibility": "all",
            "model": "anthropic/claude-haiku-4-5",
            "timeout_seconds": 90,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}
    assert settings.get(KEY_ENABLED) == "1"
    assert settings.get(KEY_VISIBILITY) == "all"
    assert settings.get(KEY_MODEL) == "anthropic/claude-haiku-4-5"
    assert settings.get(KEY_TIMEOUT_SECONDS) == "90"


def test_put_config_rejects_invalid_visibility(client):
    r = client.put(
        "/api/admin/scoring/config",
        headers=_admin_headers(),
        json={
            "enabled": True, "visibility": "everyone",
            "model": "", "timeout_seconds": 120,
        },
    )
    assert r.status_code == 422  # pydantic enum validation


def test_put_config_rejects_invalid_timeout(client):
    r = client.put(
        "/api/admin/scoring/config",
        headers=_admin_headers(),
        json={
            "enabled": True, "visibility": "admin_only",
            "model": "", "timeout_seconds": 999999,
        },
    )
    assert r.status_code == 422


# ---------- runs list ----------


def test_list_runs_empty(client):
    r = client.get("/api/admin/scoring/runs", headers=_admin_headers())
    body = r.json()
    assert body == {"items": [], "total": 0, "has_more": False}


def test_list_runs_returns_runs_with_enrichment(
    client, store, pivot_users, workspace,
):
    owner = pivot_users.create(
        display_name="张三", pinyin="zhangsan", email=None, avatar_url="https://avatar/x",
    )
    _write_matter(workspace, "m", title="客户验收流程优化")
    rid = store.start_run(_job(owner.id), timeline_hash="h", model="m1")
    store.finish_run(rid, "failed", error="ai_timeout")

    r = client.get("/api/admin/scoring/runs", headers=_admin_headers())
    body = r.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["run_id"] == rid
    assert item["matter_id"] == "m"
    assert item["matter_title"] == "客户验收流程优化"
    assert item["subject_user_id"] == owner.id
    assert item["subject_display"] == "张三"
    assert item["subject_avatar_url"] == "https://avatar/x"
    assert item["status"] == "failed"
    assert item["error"] == "ai_timeout"
    assert item["model"] == "m1"
    assert item["score"] is None  # only set on success


def test_list_runs_filters_by_status(client, store, pivot_users, workspace):
    owner = pivot_users.create(
        display_name="zs", pinyin="zhangsan", email=None, avatar_url="",
    )
    _write_matter(workspace, "m1")
    _write_matter(workspace, "m2")
    a = store.start_run(_job(owner.id, matter_id="m1"), timeline_hash="h1", model="m")
    store.finish_run(a, "success")
    b = store.start_run(_job(owner.id, matter_id="m2"), timeline_hash="h2", model="m")
    store.finish_run(b, "failed", error="x")

    r = client.get(
        "/api/admin/scoring/runs?status=success", headers=_admin_headers(),
    )
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["matter_id"] == "m1"


def test_list_runs_matter_query_substring(client, store, pivot_users, workspace):
    """matter_query passes through to store as a LIKE substring filter."""
    owner = pivot_users.create(
        display_name="zs", pinyin="zhangsan", email=None, avatar_url="",
    )
    _write_matter(workspace, "客户验收流程优化")
    _write_matter(workspace, "测试评分体系")
    store.start_run(
        _job(owner.id, matter_id="客户验收流程优化"),
        timeline_hash="h1", model="m",
    )
    store.start_run(
        _job(owner.id, matter_id="测试评分体系"),
        timeline_hash="h2", model="m",
    )

    r = client.get(
        "/api/admin/scoring/runs?matter_query=验收",
        headers=_admin_headers(),
    )
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["matter_id"] == "客户验收流程优化"

    r = client.get(
        "/api/admin/scoring/runs?matter_query=评分",
        headers=_admin_headers(),
    )
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["matter_id"] == "测试评分体系"


def test_list_runs_pagination(client, store, pivot_users, workspace):
    owner = pivot_users.create(
        display_name="zs", pinyin="zhangsan", email=None, avatar_url="",
    )
    for i in range(5):
        mid = f"m{i}"
        _write_matter(workspace, mid)
        rid = store.start_run(_job(owner.id, matter_id=mid), timeline_hash=f"h{i}", model="m")
        store.finish_run(rid, "success")

    r = client.get(
        "/api/admin/scoring/runs?limit=2&offset=0", headers=_admin_headers(),
    )
    body = r.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["has_more"] is True

    r = client.get(
        "/api/admin/scoring/runs?limit=2&offset=4", headers=_admin_headers(),
    )
    body = r.json()
    assert len(body["items"]) == 1
    assert body["has_more"] is False


def test_list_runs_rejects_bad_pagination(client):
    r = client.get(
        "/api/admin/scoring/runs?limit=999", headers=_admin_headers(),
    )
    assert r.status_code == 400
    r = client.get(
        "/api/admin/scoring/runs?offset=-1", headers=_admin_headers(),
    )
    assert r.status_code == 400


# ---------- run detail ----------


def test_get_run_detail_404_when_missing(client):
    r = client.get(
        "/api/admin/scoring/runs/nonexistent", headers=_admin_headers(),
    )
    assert r.status_code == 404


def test_get_run_detail_returns_run_only_when_no_score(
    client, store, pivot_users, workspace,
):
    owner = pivot_users.create(
        display_name="zs", pinyin="zhangsan", email=None, avatar_url="",
    )
    _write_matter(workspace, "m")
    rid = store.start_run(_job(owner.id), timeline_hash="h", model="m")
    store.finish_run(rid, "failed", error="ai_error")

    r = client.get(f"/api/admin/scoring/runs/{rid}", headers=_admin_headers())
    body = r.json()
    assert body["run"]["run_id"] == rid
    assert body["run"]["status"] == "failed"
    assert body["score"] is None
    assert body["evidence"] == []


def test_get_run_detail_returns_score_and_evidence(
    client, store, pivot_users, workspace,
):
    from server.scoring.store import EvidenceWrite, ScoreWrite
    owner = pivot_users.create(
        display_name="zs", pinyin="zhangsan", email=None, avatar_url="",
    )
    commenter = pivot_users.create(
        display_name="李四", pinyin="lisi", email=None, avatar_url="",
    )
    _write_matter(workspace, "m")
    rid = store.start_run(_job(owner.id), timeline_hash="h", model="m")
    store.write_results(
        rid,
        ScoreWrite(
            subject_user_id=owner.id,
            overall=4.2, confidence="high", rationale="...",
            delivery=4.5, accountability=4.0, process=4.0,
        ),
        [
            EvidenceWrite(
                dimension="delivery", polarity="positive", confidence="high",
                source_kind="comment", source_filename="002.md",
                source_file_type="verify",
                source_comment_created_at="2026-04-22T14:00:00+08:00",
                source_comment_author_id=commenter.id,
                weight_applied=1.5, quote="lgtm", explanation="ok",
            ),
            EvidenceWrite(
                dimension="accountability", polarity="positive", confidence="high",
                source_kind="file", source_filename="001.md",
                source_file_type="act", quote="...", explanation="...",
            ),
            EvidenceWrite(
                dimension="process", polarity="positive", confidence="medium",
                source_kind="file", source_filename="003.md",
                source_file_type="result", quote="...", explanation="...",
            ),
        ],
    )
    store.finish_run(rid, "success", prompt_tokens=100, completion_tokens=50)

    r = client.get(f"/api/admin/scoring/runs/{rid}", headers=_admin_headers())
    body = r.json()
    assert body["run"]["status"] == "success"
    assert body["run"]["prompt_tokens"] == 100
    assert body["run"]["score"] == {
        "overall": 4.2, "confidence": "high", "override_overall": None,
    }
    assert body["score"]["overall"] == 4.2
    assert body["score"]["dimensions"]["delivery"] == 4.5
    assert body["score"]["dimensions"]["judgment"] is None
    assert len(body["evidence"]) == 3
    # commenter enrichment
    comment_e = next(e for e in body["evidence"] if e["source_kind"] == "comment")
    assert comment_e["source_comment_author_display"] == "李四"
    assert comment_e["weight_applied"] == 1.5
    # v2.1: new evidence fields present (NULL for legacy / single-subject)
    assert comment_e["source_annotation_created_at"] is None
    assert comment_e["source_annotation_author_id"] is None
    assert comment_e["attribution_basis"] is None
    # v2.1: schema_version exposed in run summary
    assert body["run"]["schema_version"] == 1
    # v2.1: subject_scores array always present (back-compat with single-subject)
    assert len(body["subject_scores"]) == 1
    primary = body["subject_scores"][0]
    assert primary["score"]["subject_user_id"] == owner.id
    assert primary["subject_display"] == "zs"
    assert len(primary["evidence"]) == 3


def test_get_run_detail_multi_subject_returns_subject_scores(
    client, store, pivot_users, workspace,
):
    """v2.1: a run with multiple matter_scores rows surfaces them all in
    subject_scores; top-level `score` returns the primary (matter.owner)."""
    from server.scoring.store import EvidenceWrite, ScoreWrite
    owner = pivot_users.create(
        display_name="zs", pinyin="zhangsan", email=None, avatar_url="",
    )
    lisi = pivot_users.create(
        display_name="李四", pinyin="lisi", email=None, avatar_url="",
    )
    _write_matter(workspace, "m")
    rid = store.start_run(
        _job(owner.id), timeline_hash="h", model="m", schema_version=2,
    )
    # Owner score
    store.write_results(
        rid,
        ScoreWrite(
            subject_user_id=owner.id,
            overall=4.2, confidence="high", rationale="owner",
            delivery=4.5,
        ),
        [EvidenceWrite(
            dimension="delivery", polarity="positive", confidence="high",
            source_kind="file", source_filename="001.md",
            source_file_type="act", quote="z", explanation="...",
            attribution_basis="file_creator",
        )],
    )
    # lisi score
    store.write_results(
        rid,
        ScoreWrite(
            subject_user_id=lisi.id,
            overall=3.8, confidence="medium", rationale="lisi",
            collaboration=4.0,
        ),
        [EvidenceWrite(
            dimension="collaboration", polarity="positive", confidence="medium",
            source_kind="annotation", source_filename="002.md",
            source_file_type="act",
            source_annotation_created_at="2026-04-22T14:00:00+08:00",
            source_annotation_author_id=owner.id,
            attribution_basis="file_creator",
            quote="lisi 协作好", explanation="...",
        )],
    )
    store.finish_run(rid, "success")

    r = client.get(f"/api/admin/scoring/runs/{rid}", headers=_admin_headers())
    body = r.json()
    assert body["run"]["schema_version"] == 2
    # Top-level primary = owner
    assert body["score"]["subject_user_id"] == owner.id
    # subject_scores has both rows; primary first
    sub = body["subject_scores"]
    assert len(sub) == 2
    assert sub[0]["score"]["subject_user_id"] == owner.id
    assert sub[1]["score"]["subject_user_id"] == lisi.id
    assert sub[1]["subject_display"] == "李四"
    # lisi's evidence shows annotation fields populated
    ann_e = sub[1]["evidence"][0]
    assert ann_e["source_kind"] == "annotation"
    assert ann_e["source_annotation_author_display"] == "zs"
    assert ann_e["attribution_basis"] == "file_creator"


# ---------- rerun ----------


def test_rerun_enqueues_admin_rerun_job(
    client, queue, pivot_users, workspace,
):
    owner = pivot_users.create(
        display_name="zs", pinyin="zhangsan", email=None, avatar_url="",
    )
    _write_matter(workspace, "m")

    r = client.post(
        "/api/admin/scoring/matters/m/rerun", headers=_admin_headers(),
    )
    assert r.status_code == 200, r.text
    assert r.json()["queued"] is True
    assert len(queue.jobs) == 1
    job = queue.jobs[0]
    assert job.matter_id == "m"
    assert job.subject_user_id == owner.id
    assert job.triggered_by == "admin:rerun"


def test_rerun_404_when_matter_missing(client):
    r = client.post(
        "/api/admin/scoring/matters/ghost/rerun", headers=_admin_headers(),
    )
    assert r.status_code == 404


def test_rerun_422_when_owner_unresolvable(client, workspace, queue):
    _write_matter(workspace, "m", owner_pinyin="ghost-owner")
    r = client.post(
        "/api/admin/scoring/matters/m/rerun", headers=_admin_headers(),
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "owner_unknown"
    assert queue.jobs == []


def test_rerun_422_when_owner_empty(client, workspace, queue):
    # Write matter without owner
    data = {
        "matter": {"id": "m", "title": "t", "current_status": "finished"},
        "timeline": [
            {"file": "discussions/eng/m/001.md", "type": "act", "summary": "x",
             "created_at": "2026-04-20"},
        ],
    }
    (workspace.index_dir / "m.index.yaml").write_text(
        yaml.safe_dump(data), encoding="utf-8",
    )
    r = client.post(
        "/api/admin/scoring/matters/m/rerun", headers=_admin_headers(),
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "no_owner"


# ---------- human override ----------


def _setup_run_with_score(client, store, pivot_users, workspace, owner):
    """Helper: create a run + score so override tests have something to work on."""
    from server.scoring.store import EvidenceWrite, ScoreWrite
    _write_matter(workspace, "m")
    rid = store.start_run(_job(owner.id), timeline_hash="h", model="m")
    store.write_results(
        rid,
        ScoreWrite(
            subject_user_id=owner.id,
            overall=4.2, confidence="high", rationale="...",
            delivery=4.5, accountability=4.0, process=4.0,
        ),
        [
            EvidenceWrite(
                dimension="delivery", polarity="positive", confidence="high",
                source_kind="file", source_filename="001.md",
                source_file_type="act", quote="...", explanation="...",
            ),
            EvidenceWrite(
                dimension="accountability", polarity="positive", confidence="high",
                source_kind="file", source_filename="003.md",
                source_file_type="result", quote="...", explanation="...",
            ),
            EvidenceWrite(
                dimension="process", polarity="positive", confidence="medium",
                source_kind="file", source_filename="003.md",
                source_file_type="result", quote="...", explanation="...",
            ),
        ],
    )
    store.finish_run(rid, "success")
    return rid


def test_override_404_when_run_missing(client):
    r = client.post(
        "/api/admin/scoring/scores/nonexistent/override",
        headers=_admin_headers(),
        json={"overall": 3.5, "note": "too generous"},
    )
    assert r.status_code == 404


def test_override_422_when_run_has_no_score(
    client, store, pivot_users, workspace, admin_user,
):
    """Failed / queued / skipped runs have no score row — 422."""
    owner = pivot_users.create(
        display_name="zs", pinyin="zhangsan", email=None, avatar_url="",
    )
    _write_matter(workspace, "m")
    rid = store.start_run(_job(owner.id), timeline_hash="h", model="m")
    store.finish_run(rid, "failed", error="ai_timeout")

    r = client.post(
        f"/api/admin/scoring/scores/{rid}/override",
        headers=_admin_headers(),
        json={"overall": 3.5, "note": "n/a"},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "no_score_to_override"


def test_override_writes_human_fields(
    client, store, pivot_users, workspace, admin_user,
):
    owner = pivot_users.create(
        display_name="zs", pinyin="zhangsan", email=None, avatar_url="",
    )
    rid = _setup_run_with_score(client, store, pivot_users, workspace, owner)

    r = client.post(
        f"/api/admin/scoring/scores/{rid}/override",
        headers=_admin_headers(),
        json={"overall": 3.5, "note": "AI 给得太高，扣回半分"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["human_override"]["overall"] == 3.5
    assert body["human_override"]["note"] == "AI 给得太高，扣回半分"
    assert body["human_override"]["by"] == admin_user.id
    assert body["human_override"]["at"] is not None
    # Original AI score is preserved
    assert body["overall"] == 4.2


def test_override_422_for_invalid_overall(
    client, store, pivot_users, workspace, admin_user,
):
    owner = pivot_users.create(
        display_name="zs", pinyin="zhangsan", email=None, avatar_url="",
    )
    rid = _setup_run_with_score(client, store, pivot_users, workspace, owner)

    r = client.post(
        f"/api/admin/scoring/scores/{rid}/override",
        headers=_admin_headers(),
        json={"overall": 99.0, "note": "x"},
    )
    assert r.status_code == 422  # pydantic ge/le


def test_override_422_for_blank_note(
    client, store, pivot_users, workspace, admin_user,
):
    owner = pivot_users.create(
        display_name="zs", pinyin="zhangsan", email=None, avatar_url="",
    )
    rid = _setup_run_with_score(client, store, pivot_users, workspace, owner)

    r = client.post(
        f"/api/admin/scoring/scores/{rid}/override",
        headers=_admin_headers(),
        json={"overall": 3.5, "note": ""},
    )
    assert r.status_code == 422  # pydantic min_length


def test_override_overwrites_prior_override(
    client, store, pivot_users, workspace, admin_user,
):
    owner = pivot_users.create(
        display_name="zs", pinyin="zhangsan", email=None, avatar_url="",
    )
    rid = _setup_run_with_score(client, store, pivot_users, workspace, owner)

    # First override
    client.post(
        f"/api/admin/scoring/scores/{rid}/override",
        headers=_admin_headers(),
        json={"overall": 3.5, "note": "first"},
    )
    # Second override replaces it
    r = client.post(
        f"/api/admin/scoring/scores/{rid}/override",
        headers=_admin_headers(),
        json={"overall": 4.0, "note": "reconsidered"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["human_override"]["overall"] == 4.0
    assert body["human_override"]["note"] == "reconsidered"


def test_list_runs_exposes_override_overall_in_score_brief(
    client, store, pivot_users, workspace, admin_user,
):
    """List view needs override_overall so the table can render the effective
    score (with ✏ marker) without drilling into a drawer."""
    owner = pivot_users.create(
        display_name="zs", pinyin="zhangsan", email=None, avatar_url="",
    )
    rid = _setup_run_with_score(client, store, pivot_users, workspace, owner)

    # Before override: override_overall is null
    r1 = client.get("/api/admin/scoring/runs", headers=_admin_headers())
    item = r1.json()["items"][0]
    assert item["score"]["overall"] == 4.2
    assert item["score"]["override_overall"] is None

    # After override: override_overall reflects the new value, AI overall stays
    client.post(
        f"/api/admin/scoring/scores/{rid}/override",
        headers=_admin_headers(),
        json={"overall": 3.5, "note": "n/a"},
    )
    r2 = client.get("/api/admin/scoring/runs", headers=_admin_headers())
    item = r2.json()["items"][0]
    assert item["score"]["overall"] == 4.2          # AI original preserved
    assert item["score"]["override_overall"] == 3.5  # admin's adjustment


# ---------- commenter weights ----------


def test_list_weights_empty(client):
    r = client.get(
        "/api/admin/scoring/commenter-weights", headers=_admin_headers(),
    )
    assert r.json() == {"items": []}


def test_upsert_weight_creates(client, pivot_users):
    ceo = pivot_users.create(
        display_name="CEO", pinyin="ceo", email=None, avatar_url="https://avatar/ceo",
    )
    r = client.post(
        "/api/admin/scoring/commenter-weights",
        headers=_admin_headers(),
        json={
            "pivot_user_id": ceo.id,
            "weight": 2.0,
            "label": "CEO",
            "note": "首席",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pivot_user_id"] == ceo.id
    assert body["weight"] == 2.0
    assert body["label"] == "CEO"
    assert body["user_display"] == "CEO"
    assert body["user_avatar_url"] == "https://avatar/ceo"


def test_upsert_weight_404_when_user_missing(client):
    r = client.post(
        "/api/admin/scoring/commenter-weights",
        headers=_admin_headers(),
        json={
            "pivot_user_id": "ghost",
            "weight": 1.5,
            "label": "ghost",
        },
    )
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "user_not_found"


def test_upsert_weight_422_for_invalid_weight(client, pivot_users):
    u = pivot_users.create(display_name="x", pinyin="x", email=None, avatar_url="")
    r = client.post(
        "/api/admin/scoring/commenter-weights",
        headers=_admin_headers(),
        json={"pivot_user_id": u.id, "weight": 99.0, "label": "x"},
    )
    assert r.status_code == 422  # pydantic ge/le


def test_update_weight_patches_only_given_fields(client, pivot_users):
    user = pivot_users.create(
        display_name="X", pinyin="x", email=None, avatar_url="",
    )
    client.post(
        "/api/admin/scoring/commenter-weights",
        headers=_admin_headers(),
        json={"pivot_user_id": user.id, "weight": 1.5, "label": "CTO", "note": "old"},
    )
    r = client.put(
        f"/api/admin/scoring/commenter-weights/{user.id}",
        headers=_admin_headers(),
        json={"weight": 2.0},  # only update weight
    )
    body = r.json()
    assert body["weight"] == 2.0
    assert body["label"] == "CTO"  # unchanged
    assert body["note"] == "old"   # unchanged


def test_update_weight_404_when_not_found(client):
    r = client.put(
        "/api/admin/scoring/commenter-weights/nonexistent",
        headers=_admin_headers(),
        json={"weight": 2.0},
    )
    assert r.status_code == 404


def test_delete_weight(client, pivot_users):
    user = pivot_users.create(
        display_name="X", pinyin="x", email=None, avatar_url="",
    )
    client.post(
        "/api/admin/scoring/commenter-weights",
        headers=_admin_headers(),
        json={"pivot_user_id": user.id, "weight": 1.5, "label": "X"},
    )
    r = client.delete(
        f"/api/admin/scoring/commenter-weights/{user.id}",
        headers=_admin_headers(),
    )
    assert r.json()["ok"] is True
    # Listing should be empty
    r2 = client.get(
        "/api/admin/scoring/commenter-weights", headers=_admin_headers(),
    )
    assert r2.json()["items"] == []


def test_delete_weight_404_when_missing(client):
    r = client.delete(
        "/api/admin/scoring/commenter-weights/ghost", headers=_admin_headers(),
    )
    assert r.status_code == 404


def test_list_weights_with_user_enrichment(client, pivot_users, store):
    ceo = pivot_users.create(
        display_name="CEO", pinyin="ceo", email=None, avatar_url="https://avatar/ceo",
    )
    cto = pivot_users.create(
        display_name="CTO", pinyin="cto", email=None, avatar_url="",
    )
    admin = pivot_users.create(
        display_name="A", pinyin="a", email=None, avatar_url="",
    )
    store.upsert_weight(
        pivot_user_id=ceo.id, weight=2.0, label="CEO", note=None, updated_by=admin.id,
    )
    store.upsert_weight(
        pivot_user_id=cto.id, weight=1.5, label="CTO", note=None, updated_by=admin.id,
    )

    r = client.get(
        "/api/admin/scoring/commenter-weights", headers=_admin_headers(),
    )
    items = r.json()["items"]
    assert len(items) == 2
    # ordered by weight DESC
    assert items[0]["label"] == "CEO"
    assert items[0]["user_display"] == "CEO"
    assert items[1]["label"] == "CTO"
