from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.matters import build_router
from server.api_tokens import ApiTokenRepo
from server.auth.deps import make_current_user
from server.auth.session import SessionStore
from server.contacts import ContactRepo
from server.events import Event, clear_subscribers, subscribe
from server.favorites import FavoriteRepo
from server.notify import NoOpNotifier
from server.read_state import ReadStateRepo


class _WorkspaceStub:
    def __init__(self, root: Path) -> None:
        self.path = root
        self.discussions_dir = root / "discussions"
        self.index_dir = root / "index"

    @contextmanager
    def write_session(self, **_: object):
        self.discussions_dir.mkdir(parents=True, exist_ok=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        yield


@pytest.fixture(autouse=True)
def _clear_events():
    clear_subscribers()
    yield
    clear_subscribers()


@pytest.fixture
def event_bucket():
    bucket: list[Event] = []
    subscribe(bucket.append)
    return bucket


@pytest.fixture
def client(db, users, tmp_path):
    workspace = _WorkspaceStub(tmp_path)
    users.upsert_from_feishu(open_id="ou_1", union_id=None, name="邓柯", avatar_url="")
    users.update_profile("ou_1", pinyin="dengke")
    sessions = SessionStore(db)
    sid = sessions.create("ou_1")
    current_user = make_current_user(sessions, users, ApiTokenRepo(db))

    app = FastAPI()
    app.include_router(
        build_router(
            workspace, users, ContactRepo(db), NoOpNotifier(),
            ReadStateRepo(db), FavoriteRepo(db), current_user,
        )
    )
    c = TestClient(app)
    c.cookies.set("sid", sid)
    c.workspace = workspace  # type: ignore[attr-defined]
    return c


# ---------- POST /api/matters ----------


def test_create_matter_happy_path(client, event_bucket):
    r = client.post("/api/matters", json={
        "category": "Pivot",
        "title": "Auth Redesign",
        "initial_file": {
            "type": "think",
            "summary": "初步思考",
            "body": "# Summary\n\n初步思考\n",
        },
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["matter"]["current_status"] == "planning"
    assert data["matter"]["title"] == "Auth Redesign"
    assert data["initial_timeline_item"]["type"] == "think"
    assert data["initial_timeline_item"]["creator"] == "dengke"
    assert data["initial_timeline_item"]["owner"] == "dengke"

    # MD file exists
    ws = client.workspace
    matter_id = data["matter_id"]
    md_dir = ws.discussions_dir / "Pivot" / matter_id
    assert any(md_dir.glob("001_dengke_think_*.md"))

    # Events
    topics = [e.topic for e in event_bucket]
    assert "matter.created" in topics
    assert "matter.file_appended" in topics


def test_create_matter_rejects_result_as_initial(client):
    r = client.post("/api/matters", json={
        "category": "Pivot",
        "title": "x",
        "initial_file": {
            "type": "result",
            "summary": "no",
            "body": "",
        },
    })
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "type_not_allowed"


def test_create_matter_rejects_missing_type(client):
    # Pydantic catches min_length=1 on type field first (422)
    r = client.post("/api/matters", json={
        "category": "Pivot",
        "title": "x",
        "initial_file": {"type": "", "summary": "s", "body": ""},
    })
    assert r.status_code == 422


# ---------- GET /api/matters/{id} ----------


def test_get_matter_404(client):
    r = client.get("/api/matters/does-not-exist")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "matter_not_found"


def test_get_matter_returns_timeline_with_body(client):
    r = client.post("/api/matters", json={
        "category": "Pivot",
        "title": "T",
        "initial_file": {"type": "think", "summary": "s", "body": "# T\n\nhello\n"},
    })
    matter_id = r.json()["matter_id"]

    r2 = client.get(f"/api/matters/{matter_id}")
    assert r2.status_code == 200
    data = r2.json()
    assert data["matter"]["id"] == matter_id
    assert len(data["timeline"]) == 1
    entry = data["timeline"][0]
    assert entry["type"] == "think"
    assert entry["expanded"] is False
    assert "hello" in entry["body"]
    assert entry["refer"] == []


# ---------- POST /api/matters/{id}/files ----------


def test_append_file_think_ok(client, event_bucket):
    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]

    r2 = client.post(f"/api/matters/{matter_id}/files", json={
        "type": "think",
        "summary": "second thought",
        "body": "body text",
        "quote": r.json()["initial_timeline_item"]["file"],
    })
    assert r2.status_code == 200, r2.text
    item = r2.json()["item"]
    assert item["type"] == "think"
    assert item["summary"] == "second thought"
    assert item["quote"] == r.json()["initial_timeline_item"]["file"]

    detail = client.get(f"/api/matters/{matter_id}").json()
    assert len(detail["timeline"]) == 2

    # Event emitted
    file_events = [e for e in event_bucket if e.topic == "matter.file_appended"]
    assert len(file_events) == 2


def test_append_act_with_status_change_to_executing(client, event_bucket):
    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]

    r2 = client.post(f"/api/matters/{matter_id}/files", json={
        "type": "act",
        "summary": "start",
        "status_change": {"from": "planning", "to": "executing"},
    })
    assert r2.status_code == 200, r2.text
    assert r2.json()["matter"]["current_status"] == "executing"

    status_events = [e for e in event_bucket if e.topic == "matter.status_changed"]
    assert len(status_events) == 1
    assert status_events[0].payload["to"] == "executing"


def test_append_result_with_trigger_to_finished(client, event_bucket):
    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "act", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]

    client.post(f"/api/matters/{matter_id}/files", json={
        "type": "act",
        "summary": "another",
        "status_change": {"from": "planning", "to": "executing"},
    })

    r3 = client.post(f"/api/matters/{matter_id}/files", json={
        "type": "result",
        "summary": "done",
        "outcome": "finished",
        "status_change": {"from": "executing", "to": "finished"},
    })
    assert r3.status_code == 200, r3.text
    assert r3.json()["matter"]["current_status"] == "finished"
    assert r3.json()["item"]["outcome"] == "finished"

    assert any(e.topic == "matter.result_created" for e in event_bucket)


def test_append_verify_with_verifications(client):
    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "act", "summary": "act1", "body": ""},
    })
    matter_id = r.json()["matter_id"]
    act_file = r.json()["initial_timeline_item"]["file"]

    r2 = client.post(f"/api/matters/{matter_id}/files", json={
        "type": "verify",
        "summary": "check",
        "quote": act_file,
        "verifications": [
            {"target": act_file, "judgement": "passed", "comment": "ok"},
        ],
    })
    assert r2.status_code == 200, r2.text
    item = r2.json()["item"]
    assert item["verifications"][0]["judgement"] == "passed"


def test_append_verify_target_not_found_422(client):
    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]

    r2 = client.post(f"/api/matters/{matter_id}/files", json={
        "type": "verify",
        "summary": "check",
        "verifications": [
            {"target": "discussions/other/999_nobody.md",
             "judgement": "passed", "comment": ""},
        ],
    })
    assert r2.status_code == 422
    assert r2.json()["detail"]["code"] == "verification_target_not_found"


def test_append_verify_target_not_act_422(client):
    # Matter has a think only; verify pointing at it should be rejected.
    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]
    think_file = r.json()["initial_timeline_item"]["file"]

    r2 = client.post(f"/api/matters/{matter_id}/files", json={
        "type": "verify",
        "summary": "check",
        "verifications": [
            {"target": think_file, "judgement": "passed", "comment": ""},
        ],
    })
    assert r2.status_code == 422
    assert r2.json()["detail"]["code"] == "verification_target_not_act"


def test_append_verify_target_via_refer_ok(client):
    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]
    external = "discussions/another-matter/001_u_act_x.md"

    r2 = client.post(f"/api/matters/{matter_id}/files", json={
        "type": "verify",
        "summary": "check cross-matter",
        "refer": [external],
        "verifications": [
            {"target": external, "judgement": "passed", "comment": "cross-matter"},
        ],
    })
    assert r2.status_code == 200, r2.text


def test_append_verify_missing_verifications_422(client):
    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]

    r2 = client.post(f"/api/matters/{matter_id}/files", json={
        "type": "verify",
        "summary": "check",
    })
    assert r2.status_code == 422
    assert r2.json()["detail"]["code"] == "verifications_required"


def test_append_result_without_outcome_422(client):
    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "act", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]
    client.post(f"/api/matters/{matter_id}/files", json={
        "type": "act", "summary": "a",
        "status_change": {"from": "planning", "to": "executing"},
    })
    r3 = client.post(f"/api/matters/{matter_id}/files", json={
        "type": "result", "summary": "s",
        "status_change": {"from": "executing", "to": "finished"},
    })
    assert r3.status_code == 422
    assert r3.json()["detail"]["code"] == "outcome_required"


def test_append_wrong_status_change_from(client):
    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]

    r2 = client.post(f"/api/matters/{matter_id}/files", json={
        "type": "act", "summary": "x",
        "status_change": {"from": "executing", "to": "finished"},
    })
    assert r2.status_code == 422
    assert r2.json()["detail"]["code"] == "status_change_from_mismatch"


def test_append_404_matter_not_found(client):
    r = client.post("/api/matters/ghost/files", json={
        "type": "think", "summary": "x",
    })
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "matter_not_found"


# ---------- POST /api/matters/{id}/result ----------


def test_result_convenience_endpoint(client, event_bucket):
    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "act", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]
    client.post(f"/api/matters/{matter_id}/files", json={
        "type": "act", "summary": "a",
        "status_change": {"from": "planning", "to": "executing"},
    })

    r3 = client.post(f"/api/matters/{matter_id}/result", json={
        "summary": "done",
        "body": "事项完成",
        "outcome": "finished",
    })
    assert r3.status_code == 200, r3.text
    assert r3.json()["matter"]["current_status"] == "finished"
    assert r3.json()["item"]["outcome"] == "finished"
    assert any(e.topic == "matter.result_created" for e in event_bucket)


def test_result_cancelled_path(client):
    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "act", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]
    client.post(f"/api/matters/{matter_id}/files", json={
        "type": "act", "summary": "a",
        "status_change": {"from": "planning", "to": "executing"},
    })
    r3 = client.post(f"/api/matters/{matter_id}/result", json={
        "summary": "cancel", "outcome": "cancelled",
    })
    assert r3.status_code == 200
    assert r3.json()["matter"]["current_status"] == "cancelled"


# ---------- comments ----------


def test_append_comment_ok(client, event_bucket):
    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]
    target = r.json()["initial_timeline_item"]["file"]

    r2 = client.post(f"/api/matters/{matter_id}/comments", json={
        "target_file": target,
        "body": "同意",
        "mentions": ["liuyu"],
    })
    assert r2.status_code == 200, r2.text

    detail = client.get(f"/api/matters/{matter_id}").json()
    comments = detail["timeline"][0]["comments"]
    assert len(comments) == 1
    assert comments[0]["body"] == "同意"
    assert comments[0]["mentions"] == ["liuyu"]

    assert any(e.topic == "matter.comment_appended" for e in event_bucket)


def test_append_comment_target_not_found(client):
    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]

    r2 = client.post(f"/api/matters/{matter_id}/comments", json={
        "target_file": "discussions/Pivot/does-not-exist.md",
        "body": "x",
    })
    assert r2.status_code == 404
    assert r2.json()["detail"]["code"] == "comment_target_not_found"


# ---------- GET /api/matters (list + filters) ----------


def test_list_matters_empty(client):
    r = client.get("/api/matters")
    assert r.status_code == 200
    assert r.json() == {"items": []}


def test_list_matters_basic_and_filters(client):
    r1 = client.post("/api/matters", json={
        "category": "Pivot", "title": "Auth",
        "initial_file": {"type": "think", "summary": "s1", "body": ""},
    })
    r2 = client.post("/api/matters", json={
        "category": "Pivot", "title": "Billing",
        "initial_file": {"type": "act", "summary": "s2", "body": ""},
    })
    # Push Billing to executing
    client.post(f"/api/matters/{r2.json()['matter_id']}/files", json={
        "type": "act", "summary": "a",
        "status_change": {"from": "planning", "to": "executing"},
    })

    all_r = client.get("/api/matters").json()
    assert len(all_r["items"]) == 2
    titles = {m["title"] for m in all_r["items"]}
    assert titles == {"Auth", "Billing"}

    # status filter
    exec_r = client.get("/api/matters?status=executing").json()
    assert len(exec_r["items"]) == 1
    assert exec_r["items"][0]["title"] == "Billing"

    # q filter
    auth_q = client.get("/api/matters?q=auth").json()
    assert len(auth_q["items"]) == 1

    # owner filter (uses pinyin; dengke is the creator/owner by default)
    own_r = client.get("/api/matters?owner=dengke").json()
    assert len(own_r["items"]) == 2
    empty_own = client.get("/api/matters?owner=nobody").json()
    assert empty_own["items"] == []


# ---------- full lifecycle + reviewed ----------


def test_notifier_is_called_on_append_and_status_change(db, users, tmp_path):
    """P4.5 G: publish_matter_append must reuse notify_new_reply;
    status_change must trigger notify_status_change."""
    calls: list[tuple[str, dict]] = []

    class RecordingNotifier:
        def notify_new_thread(self, **kwargs):
            calls.append(("new_thread", kwargs))

        def notify_new_reply(self, **kwargs):
            calls.append(("new_reply", kwargs))

        def notify_status_change(self, **kwargs):
            calls.append(("status_change", kwargs))

        def notify_standalone_mention(self, **kwargs):
            calls.append(("standalone_mention", kwargs))

    workspace = _WorkspaceStub(tmp_path)
    users.upsert_from_feishu(open_id="ou_1", union_id=None, name="邓柯", avatar_url="")
    users.update_profile("ou_1", pinyin="dengke")
    sessions = SessionStore(db)
    sid = sessions.create("ou_1")
    current_user = make_current_user(sessions, users, ApiTokenRepo(db))

    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(
        build_router(
            workspace, users, ContactRepo(db), RecordingNotifier(),
            ReadStateRepo(db), FavoriteRepo(db), current_user,
        )
    )
    c = TestClient(app)
    c.cookies.set("sid", sid)

    r = c.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]
    c.post(f"/api/matters/{matter_id}/files", json={
        "type": "act", "summary": "go",
        "status_change": {"from": "planning", "to": "executing"},
    })
    c.post(f"/api/matters/{matter_id}/comments", json={
        "target_file": r.json()["initial_timeline_item"]["file"],
        "body": "请看一下",
        "mentions": ["ou_test0000000000000001"],
    })

    topics = [t for t, _ in calls]
    assert "new_thread" in topics, topics
    assert "new_reply" in topics, topics
    assert "status_change" in topics, topics
    assert "standalone_mention" in topics, topics


def test_full_lifecycle_planning_to_reviewed(client):
    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "Lifecycle",
        "initial_file": {"type": "act", "summary": "start", "body": ""},
    })
    matter_id = r.json()["matter_id"]

    # planning -> executing
    client.post(f"/api/matters/{matter_id}/files", json={
        "type": "act", "summary": "a",
        "status_change": {"from": "planning", "to": "executing"},
    })
    # verify (no status change)
    client.post(f"/api/matters/{matter_id}/files", json={
        "type": "verify", "summary": "v",
        "verifications": [
            {"target": r.json()["initial_timeline_item"]["file"],
             "judgement": "passed", "comment": "ok"},
        ],
    })
    # executing -> finished via result
    client.post(f"/api/matters/{matter_id}/result", json={
        "summary": "done", "outcome": "finished",
    })
    # finished -> reviewed via insight
    r5 = client.post(f"/api/matters/{matter_id}/files", json={
        "type": "insight", "summary": "lesson",
        "status_change": {"from": "finished", "to": "reviewed"},
    })
    assert r5.status_code == 200
    assert r5.json()["matter"]["current_status"] == "reviewed"

    # reviewed is strict deny
    r6 = client.post(f"/api/matters/{matter_id}/files", json={
        "type": "insight", "summary": "more",
    })
    assert r6.status_code == 422
    assert r6.json()["detail"]["code"] == "type_not_allowed"
