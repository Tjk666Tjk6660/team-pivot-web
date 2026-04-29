"""Integration tests for matter-level owner: creation with owner_open_id +
POST /api/matters/{id}/owner transfer endpoint + SSE event emission.

Reuses the same TestClient + workspace fixtures pattern as test_matters_api.py.
"""

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
from server.file_reads import FileReadRepo
from server.notify import NoOpNotifier
from server.read_state import ReadStateRepo
from server.relevance_events import RelevanceEventsRepo


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


class _RecordingNotifier(NoOpNotifier):
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def notify_new_thread(self, **kw):
        self.calls.append(("new_thread", kw))

    def notify_owner_change(self, **kw):
        self.calls.append(("owner_change", kw))


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
    """Two-user workspace: ou_1=dengke, ou_2=lisi. Acting user is dengke."""
    workspace = _WorkspaceStub(tmp_path)
    users.upsert_from_feishu(open_id="ou_1", union_id=None, name="邓柯", avatar_url="https://x/1.png")
    users.update_profile("ou_1", pinyin="dengke")
    users.upsert_from_feishu(open_id="ou_2", union_id=None, name="李四", avatar_url="https://x/2.png")
    users.update_profile("ou_2", pinyin="lisi")
    users.upsert_from_feishu(open_id="ou_3", union_id=None, name="王五", avatar_url="")
    users.update_profile("ou_3", pinyin="wangwu")

    sessions = SessionStore(db)
    sid = sessions.create("ou_1")
    current_user = make_current_user(sessions, users, ApiTokenRepo(db))

    notifier = _RecordingNotifier()
    app = FastAPI()
    app.include_router(
        build_router(
            workspace, users, ContactRepo(db), notifier,
            ReadStateRepo(db), FavoriteRepo(db), FileReadRepo(db),
            RelevanceEventsRepo(db), current_user,
        )
    )
    c = TestClient(app)
    c.cookies.set("sid", sid)
    c.workspace = workspace  # type: ignore[attr-defined]
    c.notifier = notifier  # type: ignore[attr-defined]
    return c


def _create_matter(client: TestClient, *, title: str = "Test Matter", owner_open_id: str | None = None) -> str:
    payload = {
        "category": "Pivot",
        "title": title,
        "initial_file": {"type": "think", "summary": "x", "body": "x"},
    }
    if owner_open_id is not None:
        payload["owner_open_id"] = owner_open_id
    r = client.post("/api/matters", json=payload)
    assert r.status_code == 200, r.text
    return r.json()["matter_id"]


# ---------- POST /api/matters with owner_open_id ----------


def test_create_matter_default_owner_is_creator(client):
    mid = _create_matter(client)
    r = client.get(f"/api/matters/{mid}")
    assert r.status_code == 200
    assert r.json()["matter"]["owner"] == "dengke"


def test_create_matter_with_other_owner(client):
    mid = _create_matter(client, owner_open_id="ou_2")
    r = client.get(f"/api/matters/{mid}")
    assert r.json()["matter"]["owner"] == "lisi"


def test_create_matter_owner_open_id_unknown(client):
    r = client.post("/api/matters", json={
        "category": "Pivot",
        "title": "x",
        "owner_open_id": "ou_does_not_exist",
        "initial_file": {"type": "think", "summary": "x", "body": "x"},
    })
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "owner_unknown"


def test_create_matter_owner_self_equivalent_to_no_owner(client):
    """Passing one's own open_id is equivalent to omitting owner_open_id."""
    mid = _create_matter(client, owner_open_id="ou_1")
    r = client.get(f"/api/matters/{mid}")
    assert r.json()["matter"]["owner"] == "dengke"


def test_create_matter_does_not_emit_owner_changed(client, event_bucket):
    _create_matter(client, owner_open_id="ou_2")
    topics = [e.topic for e in event_bucket]
    assert "matter.owner_changed" not in topics


def test_create_matter_matter_owner_independent_from_file_owner(client):
    """matter-level owner and initial_file.owner are independent."""
    r = client.post("/api/matters", json={
        "category": "Pivot",
        "title": "indep",
        "owner_open_id": "ou_2",
        "initial_file": {
            "type": "think",
            "summary": "x",
            "body": "x",
            "owner": "ou_3",  # file-level owner = wangwu
        },
    })
    assert r.status_code == 200
    mid = r.json()["matter_id"]
    detail = client.get(f"/api/matters/{mid}").json()
    assert detail["matter"]["owner"] == "lisi"
    assert detail["timeline"][0]["owner"] == "wangwu"


# ---------- POST /api/matters/{id}/owner ----------


def test_transfer_owner_happy_path(client, event_bucket):
    mid = _create_matter(client)
    r = client.post(f"/api/matters/{mid}/owner", json={
        "to_owner": "ou_2",
        "reason": "lisi takes over",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["matter"]["owner"] == "lisi"
    assert body["item"]["type"] == "owner_change"
    assert body["item"]["actor"] == "dengke"
    assert body["item"]["actor_display"] == "邓柯"
    assert body["item"]["from_owner"] == "dengke"
    assert body["item"]["to_owner"] == "lisi"
    assert body["item"]["to_owner_display"] == "李四"
    assert body["matter"]["owner_display"] == "李四"
    assert body["matter"]["owner_avatar_url"] == "https://x/2.png"
    # Event emitted
    topics = [e.topic for e in event_bucket]
    assert "matter.owner_changed" in topics


def test_transfer_owner_notifies_feishu_group(client):
    mid = _create_matter(client)
    client.notifier.calls.clear()  # type: ignore[attr-defined]

    r = client.post(f"/api/matters/{mid}/owner", json={
        "to_owner": "ou_2",
        "reason": "lisi takes over",
    })

    assert r.status_code == 200, r.text
    calls = client.notifier.calls  # type: ignore[attr-defined]
    name, payload = next(call for call in calls if call[0] == "owner_change")
    assert name == "owner_change"
    assert payload["thread_title"] == "Test Matter"
    assert payload["actor_name"] == "邓柯"
    assert payload["from_owner_name"] == "邓柯"
    assert payload["to_owner_name"] == "李四"
    assert payload["to_owner_open_id"] == "ou_2"
    assert payload["reason"] == "lisi takes over"


def test_list_matters_owner_filter_matches_matter_owner(client):
    mid = _create_matter(client, title="Owned by Lisi", owner_open_id="ou_2")
    _create_matter(client, title="Owned by Dengke")

    r = client.get("/api/matters?owner=lisi")

    assert r.status_code == 200
    ids = [item["id"] for item in r.json()["items"]]
    assert ids == [mid]


def test_transfer_owner_persists_in_index(client):
    mid = _create_matter(client)
    client.post(f"/api/matters/{mid}/owner", json={
        "to_owner": "ou_2",
        "reason": "x",
    })
    detail = client.get(f"/api/matters/{mid}").json()
    assert detail["matter"]["owner"] == "lisi"
    last = detail["timeline"][-1]
    assert last["type"] == "owner_change"
    assert last["reason"] == "x"


def test_transfer_owner_reason_empty(client):
    mid = _create_matter(client)
    r = client.post(f"/api/matters/{mid}/owner", json={
        "to_owner": "ou_2",
        "reason": "",
    })
    assert r.status_code == 422


def test_transfer_owner_to_owner_unknown(client):
    mid = _create_matter(client)
    r = client.post(f"/api/matters/{mid}/owner", json={
        "to_owner": "ou_ghost",
        "reason": "x",
    })
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "owner_unknown"


def test_transfer_owner_unchanged(client):
    mid = _create_matter(client)  # owner = dengke
    r = client.post(f"/api/matters/{mid}/owner", json={
        "to_owner": "ou_1",  # same as creator
        "reason": "x",
    })
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "owner_unchanged"


def test_transfer_owner_matter_not_found(client):
    r = client.post("/api/matters/does_not_exist/owner", json={
        "to_owner": "ou_2",
        "reason": "x",
    })
    assert r.status_code == 404


def test_transfer_owner_chain(client):
    """A → B → C; second transfer's from_owner must equal current matter.owner."""
    mid = _create_matter(client)
    r1 = client.post(f"/api/matters/{mid}/owner", json={
        "to_owner": "ou_2", "reason": "first",
    })
    assert r1.status_code == 200
    r2 = client.post(f"/api/matters/{mid}/owner", json={
        "to_owner": "ou_3", "reason": "second",
    })
    assert r2.status_code == 200
    assert r2.json()["matter"]["owner"] == "wangwu"
    # Both events recorded
    detail = client.get(f"/api/matters/{mid}").json()
    oc_events = [t for t in detail["timeline"] if t["type"] == "owner_change"]
    assert len(oc_events) == 2
    assert oc_events[0]["from_owner"] == "dengke"
    assert oc_events[0]["to_owner"] == "lisi"
    assert oc_events[1]["from_owner"] == "lisi"
    assert oc_events[1]["to_owner"] == "wangwu"


# ---------- combined status_change ----------


def test_transfer_owner_with_status_planning_to_executing(client):
    mid = _create_matter(client)
    r = client.post(f"/api/matters/{mid}/owner", json={
        "to_owner": "ou_2",
        "reason": "kick off",
        "status_change": {"from": "planning", "to": "executing"},
    })
    assert r.status_code == 200, r.text
    assert r.json()["matter"]["owner"] == "lisi"
    assert r.json()["matter"]["current_status"] == "executing"
    detail = client.get(f"/api/matters/{mid}").json()
    last = detail["timeline"][-1]
    assert last["type"] == "owner_change"
    assert last["status_change"] == {"from": "planning", "to": "executing"}


def test_transfer_owner_with_status_other_transitions_rejected(client):
    """v1 only allows planning→executing on combined transfer."""
    mid = _create_matter(client)
    # First flip to executing via the combined transfer
    r1 = client.post(f"/api/matters/{mid}/owner", json={
        "to_owner": "ou_2",
        "reason": "kick off",
        "status_change": {"from": "planning", "to": "executing"},
    })
    assert r1.status_code == 200
    # Now try executing→paused via owner_change → should be rejected
    r2 = client.post(f"/api/matters/{mid}/owner", json={
        "to_owner": "ou_3",
        "reason": "x",
        "status_change": {"from": "executing", "to": "paused"},
    })
    assert r2.status_code == 422
    assert r2.json()["detail"]["code"] == "status_change_not_allowed_by_event"


def test_transfer_owner_status_stale(client):
    """status_change.from must equal current matter.current_status."""
    mid = _create_matter(client)  # current = planning
    r = client.post(f"/api/matters/{mid}/owner", json={
        "to_owner": "ou_2",
        "reason": "x",
        "status_change": {"from": "executing", "to": "paused"},
    })
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "status_stale"


# ---------- legacy missing owner / unassigned matter ----------


def test_transfer_legacy_missing_owner_uses_first_timeline_owner(client, tmp_path):
    """Legacy indexes without matter.owner use first timeline owner as current owner."""
    mid = _create_matter(client)
    from server.matter_index import matter_index_path, read_matter_index, _atomic_write_yaml
    p = matter_index_path(client.workspace.index_dir, mid)
    data = read_matter_index(p)
    data["matter"].pop("owner", None)
    _atomic_write_yaml(p, data)

    r = client.post(f"/api/matters/{mid}/owner", json={
        "to_owner": "ou_2",
        "reason": "claim",
    })
    assert r.status_code == 200
    assert r.json()["matter"]["owner"] == "lisi"
    last_item = client.get(f"/api/matters/{mid}").json()["timeline"][-1]
    assert last_item["from_owner"] == "dengke"
    assert last_item["to_owner"] == "lisi"


def test_transfer_unassigned_with_status_to_executing(client):
    mid = _create_matter(client)
    from server.matter_index import matter_index_path, read_matter_index, _atomic_write_yaml
    p = matter_index_path(client.workspace.index_dir, mid)
    data = read_matter_index(p)
    data["matter"].pop("owner", None)
    _atomic_write_yaml(p, data)

    r = client.post(f"/api/matters/{mid}/owner", json={
        "to_owner": "ou_2",
        "reason": "claim and start",
        "status_change": {"from": "planning", "to": "executing"},
    })
    assert r.status_code == 200
    assert r.json()["matter"]["owner"] == "lisi"
    assert r.json()["matter"]["current_status"] == "executing"


def test_transfer_explicit_null_owner_is_unassigned(client):
    mid = _create_matter(client)
    from server.matter_index import matter_index_path, read_matter_index, _atomic_write_yaml
    p = matter_index_path(client.workspace.index_dir, mid)
    data = read_matter_index(p)
    data["matter"]["owner"] = None
    _atomic_write_yaml(p, data)

    r = client.post(f"/api/matters/{mid}/owner", json={
        "to_owner": "ou_2",
        "reason": "claim",
    })

    assert r.status_code == 200
    last_item = client.get(f"/api/matters/{mid}").json()["timeline"][-1]
    assert last_item["from_owner"] is None
    assert last_item["to_owner"] == "lisi"
