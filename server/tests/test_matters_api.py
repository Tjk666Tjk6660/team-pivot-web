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
            ReadStateRepo(db), FavoriteRepo(db), FileReadRepo(db),
            RelevanceEventsRepo(db), current_user,
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


def test_create_matter_writes_body_source_when_provided(client):
    from server.posts import read_post

    r = client.post("/api/matters", json={
        "category": "Pivot",
        "title": "AI-co Matter",
        "initial_file": {
            "type": "think",
            "summary": "AI 协作产出",
            "body": "正文",
            "body_source": "ai",
        },
    })
    assert r.status_code == 200, r.text

    ws = client.workspace
    md = next((ws.discussions_dir / "Pivot" / r.json()["matter_id"]).glob(
        "001_dengke_think_*.md"
    ))
    post = read_post(md)
    assert post.frontmatter.get("body_source") == "ai"


def test_create_matter_omits_body_source_when_absent(client):
    from server.posts import read_post

    r = client.post("/api/matters", json={
        "category": "Pivot",
        "title": "Plain Matter",
        "initial_file": {
            "type": "think",
            "summary": "无来源标记",
            "body": "正文",
        },
    })
    assert r.status_code == 200, r.text

    ws = client.workspace
    md = next((ws.discussions_dir / "Pivot" / r.json()["matter_id"]).glob(
        "001_dengke_think_*.md"
    ))
    post = read_post(md)
    assert "body_source" not in post.frontmatter


def test_append_file_writes_body_source_manual(client):
    from server.posts import read_post

    r0 = client.post("/api/matters", json={
        "category": "Pivot",
        "title": "Append Test",
        "initial_file": {"type": "think", "summary": "起点", "body": "起点正文"},
    })
    matter_id = r0.json()["matter_id"]
    quote_file = r0.json()["file"]

    r = client.post(f"/api/matters/{matter_id}/files", json={
        "type": "think",
        "summary": "回复",
        "body": "手写回复",
        "quote": quote_file,
        "body_source": "manual",
    })
    assert r.status_code == 200, r.text

    ws = client.workspace
    md = next((ws.discussions_dir / "Pivot" / matter_id).glob(
        "002_dengke_think_*.md"
    ))
    post = read_post(md)
    assert post.frontmatter.get("body_source") == "manual"


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
    assert comments[0]["author"] == "dengke"

    assert any(e.topic == "matter.comment_appended" for e in event_bucket)


def test_comment_mentions_resolve_open_id_to_pinyin(client, users):
    """注册用户的 open_id 写入 index 时转换为 pinyin，与 creator/owner 同格式。"""
    users.upsert_from_feishu(open_id="ou_2", union_id=None, name="刘昱", avatar_url="")
    users.update_profile("ou_2", pinyin="liuyu")

    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]
    target = r.json()["initial_timeline_item"]["file"]

    r2 = client.post(f"/api/matters/{matter_id}/comments", json={
        "target_file": target,
        "body": "请确认",
        "mentions": ["ou_2"],
    })
    assert r2.status_code == 200, r2.text

    # 直读磁盘 yaml，避免 GET 渲染层做了二次解析掩盖真实写入形态
    from server.matter_index import read_matter_index, matter_index_path
    raw = read_matter_index(matter_index_path(client.workspace.index_dir, matter_id))
    on_disk_mentions = raw["timeline"][0]["comments"][0]["mentions"]
    assert on_disk_mentions == ["liuyu"], on_disk_mentions


def test_comment_mentions_keep_open_id_for_unregistered(client):
    """未注册（无 pinyin）的 open_id 写入 index 时保留 open_id 原文。"""
    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]
    target = r.json()["initial_timeline_item"]["file"]

    unregistered = "ou_unregistered_0000000000000001"
    r2 = client.post(f"/api/matters/{matter_id}/comments", json={
        "target_file": target,
        "body": "FYI",
        "mentions": [unregistered],
    })
    assert r2.status_code == 200, r2.text

    from server.matter_index import read_matter_index, matter_index_path
    raw = read_matter_index(matter_index_path(client.workspace.index_dir, matter_id))
    on_disk_mentions = raw["timeline"][0]["comments"][0]["mentions"]
    assert on_disk_mentions == [unregistered], on_disk_mentions


def test_append_file_comments_mentions_resolved(client, users):
    """append_file 路径里 comments[].mentions 同样要走 open_id → pinyin 转换。"""
    users.upsert_from_feishu(open_id="ou_3", union_id=None, name="唐昆", avatar_url="")
    users.update_profile("ou_3", pinyin="tangkun")

    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "act", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]

    r2 = client.post(f"/api/matters/{matter_id}/files", json={
        "type": "act", "summary": "go",
        "status_change": {"from": "planning", "to": "executing"},
        "comments": [{"body": "请看一下", "mentions": ["ou_3"]}],
    })
    assert r2.status_code == 200, r2.text

    from server.matter_index import read_matter_index, matter_index_path
    raw = read_matter_index(matter_index_path(client.workspace.index_dir, matter_id))
    appended = raw["timeline"][1]
    assert appended["comments"][0]["mentions"] == ["tangkun"]


def test_create_matter_resolves_owner_open_id_to_pinyin(client, users):
    """创建 matter 时,前端 OwnerPicker 提交注册用户的 open_id;
    index 落盘前必须解析为 pinyin,与 creator 同格式。
    回归 2026-04-27 报告的 owner=ou_xxx 落盘 bug。"""
    users.upsert_from_feishu(open_id="ou_2", union_id=None, name="刘昱", avatar_url="")
    users.update_profile("ou_2", pinyin="liuyu")

    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {
            "type": "act",
            "summary": "执行",
            "body": "",
            "owner": "ou_2",   # 前端 OwnerPicker 提交 open_id
        },
    })
    assert r.status_code == 200, r.text
    matter_id = r.json()["matter_id"]

    from server.matter_index import read_matter_index, matter_index_path
    raw = read_matter_index(matter_index_path(client.workspace.index_dir, matter_id))
    assert raw["timeline"][0]["owner"] == "liuyu", raw["timeline"][0]
    assert raw["timeline"][0]["creator"] == "dengke"


def test_create_matter_keeps_owner_open_id_for_unregistered(client):
    """owner 选了未注册联系人(无 pinyin)时保留 open_id 原文,
    与 mentions 兜底语义一致。"""
    unregistered = "ou_unregistered_0000000000000001"
    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {
            "type": "act",
            "summary": "执行",
            "body": "",
            "owner": unregistered,
        },
    })
    assert r.status_code == 200, r.text
    matter_id = r.json()["matter_id"]

    from server.matter_index import read_matter_index, matter_index_path
    raw = read_matter_index(matter_index_path(client.workspace.index_dir, matter_id))
    assert raw["timeline"][0]["owner"] == unregistered, raw["timeline"][0]


def test_append_file_resolves_owner_open_id_to_pinyin(client, users):
    """append act/verify 路径同样要把 owner 转 pinyin。
    没有这一步,前端 OwnerPicker 选别人 → owner 落 ou_xxx。"""
    users.upsert_from_feishu(open_id="ou_2", union_id=None, name="刘昱", avatar_url="")
    users.update_profile("ou_2", pinyin="liuyu")

    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "act", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]

    r2 = client.post(f"/api/matters/{matter_id}/files", json={
        "type": "act", "summary": "execute",
        "owner": "ou_2",
        "status_change": {"from": "planning", "to": "executing"},
    })
    assert r2.status_code == 200, r2.text

    from server.matter_index import read_matter_index, matter_index_path
    raw = read_matter_index(matter_index_path(client.workspace.index_dir, matter_id))
    assert raw["timeline"][1]["owner"] == "liuyu", raw["timeline"][1]


def test_verifications_received_verified_by_uses_pinyin(client, users):
    """verify 文件触发反向写入 act.verifications_received[].verified_by
    时,verified_by 从 verify 的 owner 派生。owner 已是 pinyin → verified_by
    也是 pinyin。这是 owner 修复的衍生效果。"""
    users.upsert_from_feishu(open_id="ou_2", union_id=None, name="刘昱", avatar_url="")
    users.update_profile("ou_2", pinyin="liuyu")

    # 1) 建 matter,初始 act 触发 planning → executing
    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {
            "type": "act", "summary": "first act", "body": "",
            "status_change": {"from": "planning", "to": "executing"},
        },
    })
    matter_id = r.json()["matter_id"]
    target_act = r.json()["initial_timeline_item"]["file"]

    # 2) 追加 verify,owner 选别人 (ou_2 = liuyu),verifications 指向 act
    r2 = client.post(f"/api/matters/{matter_id}/files", json={
        "type": "verify",
        "summary": "checked",
        "owner": "ou_2",
        "verifications": [
            {"target": target_act, "judgement": "passed", "comment": "ok"},
        ],
    })
    assert r2.status_code == 200, r2.text

    from server.matter_index import read_matter_index, matter_index_path
    raw = read_matter_index(matter_index_path(client.workspace.index_dir, matter_id))
    # verify item 自身的 owner 是 pinyin
    verify_item = raw["timeline"][1]
    assert verify_item["owner"] == "liuyu"
    # 反向写到 act 上的 verifications_received[].verified_by 也是 pinyin
    act_item = raw["timeline"][0]
    received = act_item.get("verifications_received") or []
    assert len(received) == 1
    assert received[0]["verified_by"] == "liuyu", received[0]


def test_append_file_comments_have_author(client):
    """嵌入评论(随 POST /files 一起提交)写入 index 时必须带 author=发文者pinyin，
    与独立 POST /comments 路径一致。回归 2026-04-26 报告的 author 缺失 bug。"""
    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {
            "type": "act", "summary": "s", "body": "",
            "comments": [{"body": "顺便说一句"}],
        },
    })
    assert r.status_code == 200, r.text
    matter_id = r.json()["matter_id"]

    r2 = client.post(f"/api/matters/{matter_id}/files", json={
        "type": "act", "summary": "go",
        "status_change": {"from": "planning", "to": "executing"},
        "comments": [{"body": "请跟进"}],
    })
    assert r2.status_code == 200, r2.text

    from server.matter_index import read_matter_index, matter_index_path
    raw = read_matter_index(matter_index_path(client.workspace.index_dir, matter_id))
    assert raw["timeline"][0]["comments"][0]["author"] == "dengke"
    assert raw["timeline"][1]["comments"][0]["author"] == "dengke"


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

    # Mirror FeishuNotifier signatures exactly (no **kwargs sponge): if a
    # caller passes an unexpected kwarg, the call raises TypeError under test
    # the same way it does in production, instead of being silently swallowed.
    # (Regression guard for the post_excerpt='' bug — was hidden because the
    # mock used to be **kwargs.)
    class RecordingNotifier:
        def notify_new_thread(
            self, *, category, slug, title, author_name, filename,
            body=None, mention_open_ids=None, mention_comments=None,
        ):
            calls.append(("new_thread", {
                "category": category, "slug": slug, "title": title,
                "author_name": author_name, "filename": filename, "body": body,
                "mention_open_ids": mention_open_ids,
                "mention_comments": mention_comments,
            }))

        def notify_new_reply(
            self, *, category, slug, thread_title, author_name, filename,
            body=None, mention_open_ids=None, mention_comments=None,
        ):
            calls.append(("new_reply", {
                "category": category, "slug": slug, "thread_title": thread_title,
                "author_name": author_name, "filename": filename, "body": body,
                "mention_open_ids": mention_open_ids,
                "mention_comments": mention_comments,
            }))

        def notify_status_change(
            self, *, category, slug, thread_title, from_state, to_state,
            author_name, reason,
            trigger_type=None, trigger_summary=None, trigger_filename=None,
        ):
            calls.append(("status_change", {
                "category": category, "slug": slug,
                "thread_title": thread_title, "from_state": from_state,
                "to_state": to_state, "author_name": author_name,
                "reason": reason, "trigger_type": trigger_type,
                "trigger_summary": trigger_summary,
                "trigger_filename": trigger_filename,
            }))

        def notify_standalone_mention(
            self, *, category, slug, thread_title, target_filename,
            author_name, mention_open_ids, mention_comments,
        ):
            calls.append(("standalone_mention", {
                "category": category, "slug": slug,
                "thread_title": thread_title,
                "target_filename": target_filename,
                "author_name": author_name,
                "mention_open_ids": mention_open_ids,
                "mention_comments": mention_comments,
            }))

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
            ReadStateRepo(db), FavoriteRepo(db), FileReadRepo(db),
            RelevanceEventsRepo(db), current_user,
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

    # P4.5 G 补遗：matter 路径的 status_change 必须带"触发三件套"
    status_kwargs = next(kw for t, kw in calls if t == "status_change")
    assert status_kwargs.get("trigger_type") == "act"
    assert status_kwargs.get("trigger_summary") == "go"
    tf = status_kwargs.get("trigger_filename") or ""
    assert tf.endswith(".md") and "act" in tf, f"unexpected trigger_filename: {tf!r}"


def test_create_and_append_propagate_bundled_mentions_to_notifier(db, users, tmp_path):
    """Regression: 圈人飞书没发通知。

    Frontend (CreateFileDialog) 把 @-mentions 折成 comments[0] 上传。早先的
    publish_matter_create / publish_matter_append 给 notifier 写死
    mention_open_ids=None，导致群卡片不带 <at> 块、被圈人也没 DM。这条用例
    锁住"comments[0].mentions 必须透传到 notify_new_thread / notify_new_reply"。
    """
    calls: list[tuple[str, dict]] = []

    class RecordingNotifier:
        def notify_new_thread(self, **kw): calls.append(("new_thread", kw))
        def notify_new_reply(self, **kw):  calls.append(("new_reply", kw))
        def notify_status_change(self, **kw): calls.append(("status_change", kw))
        def notify_standalone_mention(self, **kw): calls.append(("standalone_mention", kw))

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
            ReadStateRepo(db), FavoriteRepo(db), FileReadRepo(db),
            RelevanceEventsRepo(db), current_user,
        )
    )
    c = TestClient(app)
    c.cookies.set("sid", sid)

    # create with bundled mention
    r = c.post("/api/matters", json={
        "category": "Pivot", "title": "M",
        "initial_file": {
            "type": "think", "summary": "s", "body": "",
            "comments": [
                {"body": "请关注一下", "mentions": ["ou_alice000000000000", "ou_bob00000000000000"]},
            ],
        },
    })
    assert r.status_code == 200, r.text
    matter_id = r.json()["matter_id"]

    new_thread_kw = next(kw for t, kw in calls if t == "new_thread")
    assert new_thread_kw["mention_open_ids"] == ["ou_alice000000000000", "ou_bob00000000000000"]
    assert new_thread_kw["mention_comments"] == "请关注一下"

    # append with bundled mention
    calls.clear()
    r2 = c.post(f"/api/matters/{matter_id}/files", json={
        "type": "act", "summary": "go",
        "status_change": {"from": "planning", "to": "executing"},
        "comments": [
            {"body": "你来跟一下进度", "mentions": ["ou_carol00000000000000"]},
        ],
    })
    assert r2.status_code == 200, r2.text

    new_reply_kw = next(kw for t, kw in calls if t == "new_reply")
    assert new_reply_kw["mention_open_ids"] == ["ou_carol00000000000000"]
    assert new_reply_kw["mention_comments"] == "你来跟一下进度"

    # sanity: 没 comments 时 notifier 仍然不带 mention，行为不变
    calls.clear()
    r3 = c.post(f"/api/matters/{matter_id}/files", json={
        "type": "think", "summary": "no-mention",
    })
    assert r3.status_code == 200, r3.text
    new_reply_kw2 = next(kw for t, kw in calls if t == "new_reply")
    assert new_reply_kw2["mention_open_ids"] is None
    assert new_reply_kw2["mention_comments"] is None


def test_comment_route_does_not_pass_unknown_kwargs_to_notifier(db, users, tmp_path):
    """Regression: publish_matter_comment used to pass post_excerpt="" to
    notify_standalone_mention, which the Feishu / NoOp notifier protocol
    does not declare. RecordingNotifier(**kwargs) mocks ate the extra arg
    silently, but the real FeishuNotifier raised TypeError → 500 in prod.

    Use a strict notifier whose signatures match the Notifier protocol
    exactly (no **kwargs) so any future drift fails this test loudly.
    """
    class StrictNotifier:
        def __init__(self):
            self.calls = []

        def notify_new_thread(
            self, *, category, slug, title, author_name, filename,
            body=None, mention_open_ids=None, mention_comments=None,
        ):
            self.calls.append("new_thread")

        def notify_new_reply(
            self, *, category, slug, thread_title, author_name, filename,
            body=None, mention_open_ids=None, mention_comments=None,
        ):
            self.calls.append("new_reply")

        def notify_status_change(
            self, *, category, slug, thread_title, from_state, to_state,
            author_name, reason,
            trigger_type=None, trigger_summary=None, trigger_filename=None,
        ):
            self.calls.append("status_change")

        def notify_standalone_mention(
            self, *, category, slug, thread_title, target_filename,
            author_name, mention_open_ids, mention_comments,
        ):
            self.calls.append("standalone_mention")

    workspace = _WorkspaceStub(tmp_path)
    users.upsert_from_feishu(open_id="ou_1", union_id=None, name="邓柯", avatar_url="")
    users.update_profile("ou_1", pinyin="dengke")
    sessions = SessionStore(db)
    sid = sessions.create("ou_1")
    current_user = make_current_user(sessions, users, ApiTokenRepo(db))

    from fastapi import FastAPI
    app = FastAPI()
    notifier = StrictNotifier()
    app.include_router(
        build_router(
            workspace, users, ContactRepo(db), notifier,
            ReadStateRepo(db), FavoriteRepo(db), FileReadRepo(db),
            RelevanceEventsRepo(db), current_user,
        )
    )
    c = TestClient(app)
    c.cookies.set("sid", sid)

    r = c.post("/api/matters", json={
        "category": "Pivot", "title": "M",
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]
    target_file = r.json()["initial_timeline_item"]["file"]

    # Standalone comment with mention — used to TypeError on post_excerpt arg.
    r2 = c.post(f"/api/matters/{matter_id}/comments", json={
        "target_file": target_file,
        "body": "请关注一下",
        "mentions": ["ou_x000000000000000000"],
    })
    assert r2.status_code == 200, r2.text
    assert "standalone_mention" in notifier.calls


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


# ---------- POST /api/matters/{id}/files/{filename}/read ----------


def _create_matter_with_two_files(client) -> tuple[str, str, str]:
    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "think", "summary": "s1", "body": "first"},
    })
    matter_id = r.json()["matter_id"]
    file1 = r.json()["initial_timeline_item"]["file"].rsplit("/", 1)[-1]
    r2 = client.post(f"/api/matters/{matter_id}/files", json={
        "type": "think", "summary": "s2", "body": "second",
    })
    file2 = r2.json()["item"]["file"].rsplit("/", 1)[-1]
    return matter_id, file1, file2


def test_mark_file_read_first_time_returns_iso(client):
    matter_id, file1, _ = _create_matter_with_two_files(client)
    r = client.post(f"/api/matters/{matter_id}/files/{file1}/read")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["matter_id"] == matter_id
    assert data["filename"] == file1
    # ISO 8601 with timezone offset
    assert "T" in data["first_read_at"]
    assert data["first_read_at"].endswith("00") or "+" in data["first_read_at"]


def test_mark_file_read_idempotent(client):
    matter_id, file1, _ = _create_matter_with_two_files(client)
    r1 = client.post(f"/api/matters/{matter_id}/files/{file1}/read")
    r2 = client.post(f"/api/matters/{matter_id}/files/{file1}/read")
    assert r1.status_code == 200
    assert r2.status_code == 200
    # second call returns the original timestamp (not updated)
    assert r2.json()["first_read_at"] == r1.json()["first_read_at"]


def test_mark_file_read_unknown_matter_404(client):
    r = client.post("/api/matters/does-not-exist/files/01.md/read")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "matter_not_found"


def test_mark_file_read_unknown_file_404(client):
    matter_id, _, _ = _create_matter_with_two_files(client)
    r = client.post(f"/api/matters/{matter_id}/files/999_ghost.md/read")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "file_not_in_matter"


def test_get_matter_detail_includes_readers(client):
    matter_id, file1, file2 = _create_matter_with_two_files(client)
    # No reads yet
    detail0 = client.get(f"/api/matters/{matter_id}").json()
    for item in detail0["timeline"]:
        assert item["readers_count"] == 0
        assert item["readers"] == []

    # Mark file1 read
    client.post(f"/api/matters/{matter_id}/files/{file1}/read")
    detail1 = client.get(f"/api/matters/{matter_id}").json()
    by_basename = {
        it["file"].rsplit("/", 1)[-1]: it for it in detail1["timeline"]
    }
    assert by_basename[file1]["readers_count"] == 1
    reader = by_basename[file1]["readers"][0]
    assert reader["open_id"] == "ou_1"
    assert reader["name"] == "邓柯"
    assert "first_read_at" in reader
    # file2 still unread
    assert by_basename[file2]["readers_count"] == 0
    assert by_basename[file2]["readers"] == []
