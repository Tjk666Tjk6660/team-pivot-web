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
from server.events import Event, clear_subscribers, subscribe
from server.favorites import FavoriteRepo
from server.file_reads import FileReadRepo
from server.notify import NoOpNotifier
from server.read_state import ReadStateRepo
from server.external_bindings import ExternalBindingRepo
from server.mentions import DisplayResolver
from server.pivot_users import PivotUserRepo
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


def _seed_pivot_user_with_feishu(
    db, *, pinyin: str, display_name: str, open_id: str,
) -> str:
    """Test helper: create a pivot_user + feishu external_binding so the @
    resolver path can map pinyin / open_id / display_name to a real user.

    Returns the new pivot_user id.
    """
    pivot_users = PivotUserRepo(db)
    bindings = ExternalBindingRepo(db)
    user = pivot_users.create(
        display_name=display_name, pinyin=pinyin,
        email=None, avatar_url="",
    )
    bindings.bind(
        pivot_user_id=user.id, provider="feishu",
        external_id=open_id, external_union_id=None,
        raw_profile_json=None,
    )
    return user.id


@pytest.fixture
def client(db, users, tmp_path):
    workspace = _WorkspaceStub(tmp_path)
    users.upsert_from_feishu(open_id="ou_1", union_id=None, name="邓柯", avatar_url="")
    users.update_profile("ou_1", pinyin="dengke")
    pivot_users = PivotUserRepo(db)
    bindings = ExternalBindingRepo(db)
    current_pivot_user_id = _seed_pivot_user_with_feishu(
        db, pinyin="dengke", display_name="閭撴煰", open_id="ou_1",
    )
    sessions = SessionStore(db)
    sid = sessions.create(current_pivot_user_id)
    current_user = make_current_user(sessions, pivot_users, ApiTokenRepo(db))

    app = FastAPI()
    app.include_router(
        build_router(
            workspace, pivot_users, bindings, NoOpNotifier(),
            ReadStateRepo(db), FavoriteRepo(db), FileReadRepo(db),
            RelevanceEventsRepo(db), DisplayResolver(pivot_users, bindings), current_user,
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


def test_create_matter_adds_matter_owner_to_restricted_visibility(client, db):
    from server.matter_index import matter_index_path, read_matter_index

    owner_id = _seed_pivot_user_with_feishu(
        db, pinyin="liuyu", display_name="liuyu", open_id="ou_2",
    )

    r = client.post("/api/matters", json={
        "category": "Pivot",
        "title": "Owner Visible Matter",
        "owner_id": owner_id,
        "visibility": {
            "mode": "restricted",
            "roles": [],
            "user_ids": ["ou_1"],
        },
        "initial_file": {
            "type": "think",
            "summary": "restricted",
            "body": "body",
        },
    })
    assert r.status_code == 200, r.text

    raw = read_matter_index(
        matter_index_path(client.workspace.index_dir, r.json()["matter_id"])
    )
    visibility = raw["matter"]["visibility"]
    assert visibility["mode"] == "restricted"
    assert visibility["user_ids"] == ["ou_1", owner_id]


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


def test_append_comment_ok(client, event_bucket, users):
    users.upsert_from_feishu(open_id="ou_2", union_id=None, name="刘昱", avatar_url="")
    users.update_profile("ou_2", pinyin="liuyu")
    mentioned_user_id = _seed_pivot_user_with_feishu(
        users._db, pinyin="liuyu", display_name="liuyu", open_id="ou_2",
    )

    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]
    target = r.json()["initial_timeline_item"]["file"]

    r2 = client.post(f"/api/matters/{matter_id}/mentions", json={
        "target_file": target,
        "body": "同意",
        "targets": ["ou_2"],
    })
    assert r2.status_code == 200, r2.text

    detail = client.get(f"/api/matters/{matter_id}").json()
    mentions = detail["timeline"][0]["mentions"]
    assert len(mentions) == 1
    assert mentions[0]["body"] == "同意"
    assert mentions[0]["targets"] == [mentioned_user_id]
    assert mentions[0]["author"] == "dengke"

    assert any(e.topic == "matter.mention_appended" for e in event_bucket)


def test_comment_mentions_resolve_open_id_to_pinyin(client, users):
    """注册用户的 open_id 写入 index 时转换为 pinyin，与 creator/owner 同格式。"""
    users.upsert_from_feishu(open_id="ou_2", union_id=None, name="刘昱", avatar_url="")
    users.update_profile("ou_2", pinyin="liuyu")
    mentioned_user_id = _seed_pivot_user_with_feishu(
        users._db, pinyin="liuyu", display_name="liuyu", open_id="ou_2",
    )

    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]
    target = r.json()["initial_timeline_item"]["file"]

    r2 = client.post(f"/api/matters/{matter_id}/mentions", json={
        "target_file": target,
        "body": "请确认",
        "targets": ["ou_2"],
    })
    assert r2.status_code == 200, r2.text

    # 直读磁盘 yaml，避免 GET 渲染层做了二次解析掩盖真实写入形态
    from server.matter_index import read_matter_index, matter_index_path
    raw = read_matter_index(matter_index_path(client.workspace.index_dir, matter_id))
    on_disk_mentions = raw["timeline"][0]["mentions"][0]["targets"]
    assert on_disk_mentions == [mentioned_user_id], on_disk_mentions


def test_comment_mentions_keep_open_id_for_unregistered(client):
    """未注册（无 pinyin）的 open_id 写入 index 时保留 open_id 原文。"""
    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]
    target = r.json()["initial_timeline_item"]["file"]

    unregistered = "ou_unregistered_0000000000000001"
    r2 = client.post(f"/api/matters/{matter_id}/mentions", json={
        "target_file": target,
        "body": "FYI",
        "targets": [unregistered],
    })
    assert r2.status_code == 200, r2.text

    from server.matter_index import read_matter_index, matter_index_path
    raw = read_matter_index(matter_index_path(client.workspace.index_dir, matter_id))
    on_disk_mentions = raw["timeline"][0]["mentions"][0]["targets"]
    assert on_disk_mentions == [unregistered], on_disk_mentions


def test_comment_mcp_pinyin_input_renders_chinese_name(client, db):
    """MCP add_comment 直传 pinyin（"zhangbo"），且该联系人只在 contacts、未
    注册过 Pivot。旧逻辑把 "zhangbo" 原样写进 index，GET 渲染时 resolve_id
    在 users/contacts 都找不到（contacts.get_by_any_id 不查 pinyin 列），兜底
    返回原字符串，Web 上就显示 @zhangbo 而不是 @张菠。
    Fix: publish 应先把名/拼音解析为 open_id 再走 _resolve_mentions_for_index。
    回归 2026-04-29 用户报告的 MCP 圈人显示拼音 bug。"""
    _seed_pivot_user_with_feishu(db, pinyin="zhangbo", display_name="张菠",
                                 open_id="ou_zhangbo")

    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]
    target = r.json()["initial_timeline_item"]["file"]

    r2 = client.post(f"/api/matters/{matter_id}/mentions", json={
        "target_file": target,
        "body": "测试圈人",
        "targets": ["zhangbo"],
    })
    assert r2.status_code == 200, r2.text

    detail = client.get(f"/api/matters/{matter_id}").json()
    cm = detail["timeline"][0]["mentions"][0]
    assert cm["targets_display"] == ["张菠"], cm


def test_create_matter_mcp_pinyin_input_renders_chinese_name(client, db):
    """create_matter 路径同 add_comment：MCP 直传 pinyin，渲染应是中文名而非
    拼音。回归 2026-04-29 用户报告。"""
    _seed_pivot_user_with_feishu(db, pinyin="zhangbo", display_name="张菠",
                                 open_id="ou_zhangbo")

    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {
            "type": "think", "summary": "s", "body": "",
            "mentions": [{"body": "@ 张菠", "targets": ["zhangbo"]}],
        },
    })
    assert r.status_code == 200, r.text
    matter_id = r.json()["matter_id"]

    detail = client.get(f"/api/matters/{matter_id}").json()
    cm = detail["timeline"][0]["mentions"][0]
    assert cm["targets_display"] == ["张菠"], cm


def test_append_file_mcp_pinyin_input_renders_chinese_name(client, db):
    """append_file (POST /matters/{id}/files) 路径同 add_comment：MCP 直传
    pinyin，渲染应是中文名。回归 2026-04-29 用户报告。"""
    _seed_pivot_user_with_feishu(db, pinyin="zhangbo", display_name="张菠",
                                 open_id="ou_zhangbo")

    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "act", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]

    r2 = client.post(f"/api/matters/{matter_id}/files", json={
        "type": "act", "summary": "go",
        "status_change": {"from": "planning", "to": "executing"},
        "mentions": [{"body": "@ 张菠", "targets": ["zhangbo"]}],
    })
    assert r2.status_code == 200, r2.text

    detail = client.get(f"/api/matters/{matter_id}").json()
    cm = detail["timeline"][1]["mentions"][0]
    assert cm["targets_display"] == ["张菠"], cm


def test_append_file_mentions_targets_resolved(client, users):
    """append_file 路径里 mentions[].targets 同样要走 open_id → pinyin 转换。"""
    users.upsert_from_feishu(open_id="ou_3", union_id=None, name="唐昆", avatar_url="")
    users.update_profile("ou_3", pinyin="tangkun")
    mentioned_user_id = _seed_pivot_user_with_feishu(
        users._db, pinyin="tangkun", display_name="tangkun", open_id="ou_3",
    )

    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "act", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]

    r2 = client.post(f"/api/matters/{matter_id}/files", json={
        "type": "act", "summary": "go",
        "status_change": {"from": "planning", "to": "executing"},
        "mentions": [{"body": "请看一下", "targets": ["ou_3"]}],
    })
    assert r2.status_code == 200, r2.text

    from server.matter_index import read_matter_index, matter_index_path
    raw = read_matter_index(matter_index_path(client.workspace.index_dir, matter_id))
    appended = raw["timeline"][1]
    assert appended["mentions"][0]["targets"] == [mentioned_user_id]


def test_create_matter_resolves_owner_open_id_to_pinyin(client, users):
    """创建 matter 时,前端 OwnerPicker 提交注册用户的 open_id;
    index 落盘前必须解析为 pinyin,与 creator 同格式。
    回归 2026-04-27 报告的 owner=ou_xxx 落盘 bug。"""
    users.upsert_from_feishu(open_id="ou_2", union_id=None, name="刘昱", avatar_url="")
    users.update_profile("ou_2", pinyin="liuyu")
    _seed_pivot_user_with_feishu(
        users._db, pinyin="liuyu", display_name="liuyu", open_id="ou_2",
    )

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
    _seed_pivot_user_with_feishu(
        users._db, pinyin="liuyu", display_name="liuyu", open_id="ou_2",
    )

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
    _seed_pivot_user_with_feishu(
        users._db, pinyin="liuyu", display_name="liuyu", open_id="ou_2",
    )

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


def test_append_file_mentions_have_author(client):
    """嵌入提醒（随 POST /files 一起提交）写入 index 时必须带 author=发文者
    pinyin，与独立 POST /mentions 路径一致。回归 2026-04-26 报告的 author
    缺失 bug。"""
    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {
            "type": "act", "summary": "s", "body": "",
            "mentions": [{"body": "顺便说一句"}],
        },
    })
    assert r.status_code == 200, r.text
    matter_id = r.json()["matter_id"]

    r2 = client.post(f"/api/matters/{matter_id}/files", json={
        "type": "act", "summary": "go",
        "status_change": {"from": "planning", "to": "executing"},
        "mentions": [{"body": "请跟进"}],
    })
    assert r2.status_code == 200, r2.text

    from server.matter_index import read_matter_index, matter_index_path
    raw = read_matter_index(matter_index_path(client.workspace.index_dir, matter_id))
    assert raw["timeline"][0]["mentions"][0]["author"] == "dengke"
    assert raw["timeline"][1]["mentions"][0]["author"] == "dengke"


def test_append_mention_target_not_found(client):
    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]

    r2 = client.post(f"/api/matters/{matter_id}/mentions", json={
        "target_file": "discussions/Pivot/does-not-exist.md",
        "body": "x",
    })
    assert r2.status_code == 404
    assert r2.json()["detail"]["code"] == "mention_target_not_found"


def test_post_mentions_rejects_legacy_comments_field(client):
    """Legacy clients sending `mentions` (the old inner @ key) at the body's
    top level — instead of the renamed `targets` — must get a 422. Pydantic
    extra=forbid surfaces the bad key explicitly so old MCP / web clients
    fail loud rather than silently dropping their @-targets."""
    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]
    target = r.json()["initial_timeline_item"]["file"]

    r2 = client.post(f"/api/matters/{matter_id}/mentions", json={
        "target_file": target,
        "body": "x",
        "mentions": ["ou_2"],  # legacy key — should be `targets`
    })
    assert r2.status_code == 422, r2.text


def test_create_matter_rejects_legacy_comments_field(client):
    """Same 422 guarantee for the embedded list on initial_file: the legacy
    name `comments` is no longer accepted; clients must use `mentions`."""
    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {
            "type": "think", "summary": "s", "body": "",
            "comments": [{"body": "x"}],  # legacy outer key
        },
    })
    assert r.status_code == 422, r.text


# ---------- GET /api/matters (list + filters) ----------


def test_list_matters_empty(client):
    r = client.get("/api/matters")
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["has_more"] is False


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
    assert all_r["total"] == 2
    assert all_r["has_more"] is False
    titles = {m["title"] for m in all_r["items"]}
    assert titles == {"Auth", "Billing"}

    # status filter (single value — back-compat with older clients)
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
    assert empty_own["total"] == 0


def test_list_matters_multi_select_filters(client):
    r_auth = client.post("/api/matters", json={
        "category": "Pivot", "title": "Auth",
        "initial_file": {"type": "think", "summary": "s1", "body": ""},
    })
    client.post("/api/matters", json={
        "category": "Pivot", "title": "Billing",
        "initial_file": {"type": "think", "summary": "s2", "body": ""},
    })
    r_search = client.post("/api/matters", json={
        "category": "Pivot", "title": "Search",
        "initial_file": {"type": "act", "summary": "s3", "body": ""},
    })
    # Push Auth → executing; Search → executing → finished
    client.post(f"/api/matters/{r_auth.json()['matter_id']}/files", json={
        "type": "act", "summary": "a",
        "status_change": {"from": "planning", "to": "executing"},
    })
    client.post(f"/api/matters/{r_search.json()['matter_id']}/files", json={
        "type": "act", "summary": "a",
        "status_change": {"from": "planning", "to": "executing"},
    })
    rfin = client.post(f"/api/matters/{r_search.json()['matter_id']}/result", json={
        "summary": "done", "outcome": "finished",
    })
    assert rfin.status_code == 200, rfin.text

    # status multi-select: planning + executing
    multi_status = client.get(
        "/api/matters?status=planning&status=executing"
    ).json()
    assert {m["title"] for m in multi_status["items"]} == {"Auth", "Billing"}
    assert multi_status["total"] == 2

    # owner multi-select with non-existent owner mixed in still matches dengke
    multi_owner = client.get(
        "/api/matters?owner=dengke&owner=nobody"
    ).json()
    assert len(multi_owner["items"]) == 3

    # q + status intersection
    intersect = client.get(
        "/api/matters?q=auth&status=executing"
    ).json()
    assert len(intersect["items"]) == 1
    assert intersect["items"][0]["title"] == "Auth"


def test_list_matters_owner_filter_ignores_per_file_owner(client, db, users):
    """Owner filter must only match matter-level owner, not the per-file
    owner of a single timeline item — regression for matter-view-improvement
    spec §1.2."""
    users.upsert_from_feishu(open_id="ou_2", union_id=None, name="Terry", avatar_url="")
    users.update_profile("ou_2", pinyin="terry")

    # dengke creates a matter and assigns the first think file's owner=terry
    # at the file level. Matter-level owner stays dengke (default = creator).
    client.post("/api/matters", json={
        "category": "Pivot", "title": "shared",
        "initial_file": {"type": "think", "summary": "s", "body": "", "owner": "terry"},
    })

    # Sanity: dengke (matter owner) should match
    r_dengke = client.get("/api/matters?owner=dengke").json()
    assert len(r_dengke["items"]) == 1

    # terry is only the per-file owner — should NOT match
    r_terry = client.get("/api/matters?owner=terry").json()
    assert r_terry["items"] == []


def test_list_matters_pagination(client):
    for i in range(5):
        client.post("/api/matters", json={
            "category": "Pivot", "title": f"M{i}",
            "initial_file": {"type": "think", "summary": "s", "body": ""},
        })

    page1 = client.get("/api/matters?limit=2&offset=0").json()
    assert len(page1["items"]) == 2
    assert page1["total"] == 5
    assert page1["has_more"] is True

    page3 = client.get("/api/matters?limit=2&offset=4").json()
    assert len(page3["items"]) == 1
    assert page3["has_more"] is False


def test_list_matters_scope_relevant_includes_mentioned_matter(
    client, db, users, tmp_path,
):
    """a 提及 b 后，b 的 scope=relevant 必须包含该 matter — 端到端覆盖
    publish_matter_comment → emit(TOPIC_COMMENT_APPENDED) → relevance_writer
    →_handle_comment_appended → insert_mention →
    matter_ids_for_user → _is_matter_relevant_to_user 整条链路。"""
    from server.api_tokens import ApiTokenRepo
    from server.auth.deps import make_current_user
    from server.notify import NoOpNotifier
    from server.relevance_writer import install as install_relevance_writer

    users.upsert_from_feishu(open_id="ou_a", union_id=None, name="A", avatar_url="")
    users.update_profile("ou_a", pinyin="alice")
    users.upsert_from_feishu(open_id="ou_b", union_id=None, name="B", avatar_url="")
    users.update_profile("ou_b", pinyin="bob")

    # The default `client` fixture installs the matters router only — the
    # relevance_writer subscriber lives in app.py and is not wired into the
    # FastAPI test app. Install it on the shared event bus so emit() actually
    # reaches the writer.
    install_relevance_writer(
        workspace=client.workspace,
        users_repo=users,
        repo=RelevanceEventsRepo(db),
    )

    # Switch to alice (default fixture session is dengke) and create a matter
    sessions = SessionStore(db)
    sid_a = sessions.create("ou_a")
    client.cookies.set("sid", sid_a)
    r_create = client.post("/api/matters", json={
        "category": "Pivot", "title": "shared",
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    })
    assert r_create.status_code == 200, r_create.text
    matter_id = r_create.json()["matter_id"]
    target_file = r_create.json()["file"]

    # alice posts a comment that @-mentions bob (open_id passed in)
    r_cmt = client.post(f"/api/matters/{matter_id}/comments", json={
        "target_file": target_file,
        "body": "hey @bob look at this",
        "mentions": ["ou_b"],
    })
    assert r_cmt.status_code == 200, r_cmt.text

    # Verify the mention row landed in relevance_events
    repo = RelevanceEventsRepo(db)
    bobs_matters = repo.matter_ids_for_user("ou_b")
    assert matter_id in bobs_matters, (
        f"mention row missing — matter_ids_for_user(ou_b) = {bobs_matters}"
    )

    # Switch session to bob and verify list_matters?scope=relevant returns the matter
    sid_b = sessions.create("ou_b")
    client.cookies.set("sid", sid_b)
    r_list = client.get("/api/matters?scope=relevant").json()
    titles = {m["title"] for m in r_list["items"]}
    assert "shared" in titles, (
        f"bob's relevant scope missing the @-mentioned matter: {titles}"
    )


def test_list_matters_scope_relevant(client, db, users):
    # Set up a second user (terry) and create a matter as terry — dengke
    # is not relevant to it.
    users.upsert_from_feishu(open_id="ou_2", union_id=None, name="Terry", avatar_url="")
    users.update_profile("ou_2", pinyin="terry")

    # dengke (sid set in fixture) creates matter A
    client.post("/api/matters", json={
        "category": "Pivot", "title": "A-by-dengke",
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    })

    # Switch session to terry to create matter B owned by terry only
    sessions = SessionStore(db)
    sid_terry = sessions.create("ou_2")
    client.cookies.set("sid", sid_terry)
    client.post("/api/matters", json={
        "category": "Pivot", "title": "B-by-terry",
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    })

    # Back to dengke
    sid_dengke = sessions.create("ou_1")
    client.cookies.set("sid", sid_dengke)

    all_r = client.get("/api/matters").json()
    assert len(all_r["items"]) == 2

    relevant = client.get("/api/matters?scope=relevant").json()
    titles = {m["title"] for m in relevant["items"]}
    # Self-creation gap: dengke's own matter has no relevance_events row
    # (compute_relevance excludes ``creator == me``), so the timeline-scan
    # fallback in _is_matter_relevant_to_user must still pick it up.
    assert titles == {"A-by-dengke"}


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
            body=None, owner_open_id=None, mention_open_ids=None, mention_comments=None,
        ):
            calls.append(("new_thread", {
                "category": category, "slug": slug, "title": title,
                "author_name": author_name, "filename": filename, "body": body,
                "owner_open_id": owner_open_id,
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
            dm_extra_open_ids=None,
        ):
            calls.append(("standalone_mention", {
                "category": category, "slug": slug,
                "thread_title": thread_title,
                "target_filename": target_filename,
                "author_name": author_name,
                "mention_open_ids": mention_open_ids,
                "mention_comments": mention_comments,
                "dm_extra_open_ids": dm_extra_open_ids,
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
            workspace, PivotUserRepo(db), ExternalBindingRepo(db), RecordingNotifier(),
            ReadStateRepo(db), FavoriteRepo(db), FileReadRepo(db),
            RelevanceEventsRepo(db), DisplayResolver(PivotUserRepo(db), ExternalBindingRepo(db)), current_user,
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
    c.post(f"/api/matters/{matter_id}/mentions", json={
        "target_file": r.json()["initial_timeline_item"]["file"],
        "body": "请看一下",
        "targets": ["ou_test0000000000000001"],
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
        def notify_owner_change(self, **kw): calls.append(("owner_change", kw))
        def notify_standalone_mention(self, **kw): calls.append(("standalone_mention", kw))

    workspace = _WorkspaceStub(tmp_path)
    users.upsert_from_feishu(open_id="ou_1", union_id=None, name="邓柯", avatar_url="")
    users.update_profile("ou_1", pinyin="dengke")
    pivot_users = PivotUserRepo(db)
    bindings = ExternalBindingRepo(db)
    current_pivot_user_id = _seed_pivot_user_with_feishu(
        db, pinyin="dengke", display_name="dengke", open_id="ou_1",
    )
    sessions = SessionStore(db)
    sid = sessions.create(current_pivot_user_id)
    current_user = make_current_user(sessions, pivot_users, ApiTokenRepo(db))

    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(
        build_router(
            workspace, pivot_users, bindings, RecordingNotifier(),
            ReadStateRepo(db), FavoriteRepo(db), FileReadRepo(db),
            RelevanceEventsRepo(db), DisplayResolver(pivot_users, bindings), current_user,
        )
    )
    c = TestClient(app)
    c.cookies.set("sid", sid)

    # create with bundled mention
    r = c.post("/api/matters", json={
        "category": "Pivot", "title": "M",
        "initial_file": {
            "type": "think", "summary": "s", "body": "",
            "mentions": [
                {"body": "请关注一下", "targets": ["ou_alice000000000000", "ou_bob00000000000000"]},
            ],
        },
    })
    assert r.status_code == 200, r.text
    matter_id = r.json()["matter_id"]

    new_thread_kw = next(kw for t, kw in calls if t == "new_thread")
    assert new_thread_kw["mention_open_ids"] == [
        "ou_alice000000000000",
        "ou_bob00000000000000",
    ]
    assert new_thread_kw["owner_open_id"] == "ou_1"
    assert new_thread_kw["mention_comments"] == "请关注一下"

    # append with bundled mention
    calls.clear()
    r2 = c.post(f"/api/matters/{matter_id}/files", json={
        "type": "act", "summary": "go",
        "status_change": {"from": "planning", "to": "executing"},
        "mentions": [
            {"body": "你来跟一下进度", "targets": ["ou_carol00000000000000"]},
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


def test_mcp_name_mentions_resolve_to_open_ids_for_notifier(db, users, tmp_path):
    """MCP lets AI pass natural strings (邓柯 / dengke) instead of raw open_ids;
    the notifier needs the actual open_id to deliver Feishu DMs. Resolution
    now happens via pivot_user + external_binding(feishu). Web's path (real
    open_ids) must keep working unchanged.
    """
    calls: list[tuple[str, dict]] = []

    class RecordingNotifier:
        def notify_new_thread(self, **kw): calls.append(("new_thread", kw))
        def notify_new_reply(self, **kw):  calls.append(("new_reply", kw))
        def notify_status_change(self, **kw): calls.append(("status_change", kw))
        def notify_standalone_mention(self, **kw): calls.append(("standalone_mention", kw))

    workspace = _WorkspaceStub(tmp_path)
    users.upsert_from_feishu(open_id="ou_creator", union_id=None, name="作者", avatar_url="")
    users.update_profile("ou_creator", pinyin="zuozhe")
    sessions = SessionStore(db)
    sid = sessions.create("ou_creator")
    current_user = make_current_user(sessions, users, ApiTokenRepo(db))

    _seed_pivot_user_with_feishu(db, pinyin="dengke", display_name="邓柯",
                                 open_id="ou_dengke")

    pivot_users = PivotUserRepo(db)
    bindings = ExternalBindingRepo(db)
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(
        build_router(
            workspace, pivot_users, bindings, RecordingNotifier(),
            ReadStateRepo(db), FavoriteRepo(db), FileReadRepo(db),
            RelevanceEventsRepo(db), DisplayResolver(pivot_users, bindings), current_user,
        )
    )
    c = TestClient(app)
    c.cookies.set("sid", sid)

    r = c.post("/api/matters", json={
        "category": "Pivot", "title": "MCP Mention Resolution",
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]
    target_file = r.json()["initial_timeline_item"]["file"]

    # Case 1: AI passes Chinese name → notifier gets resolved open_id
    calls.clear()
    r2 = c.post(f"/api/matters/{matter_id}/mentions", json={
        "target_file": target_file,
        "body": "请 review 这条",
        "targets": ["邓柯"],
    })
    assert r2.status_code == 200, r2.text
    sm = next(kw for t, kw in calls if t == "standalone_mention")
    assert sm["mention_open_ids"] == ["ou_dengke"]

    # Case 2: Web path (real open_id) unchanged
    calls.clear()
    c.post(f"/api/matters/{matter_id}/mentions", json={
        "target_file": target_file, "body": "y", "targets": ["ou_dengke"],
    })
    sm2 = next(kw for t, kw in calls if t == "standalone_mention")
    assert sm2["mention_open_ids"] == ["ou_dengke"]

    # Case 3: Unresolvable name → notifier NOT called for this mention
    calls.clear()
    r5 = c.post(f"/api/matters/{matter_id}/mentions", json={
        "target_file": target_file, "body": "hi",
        "targets": ["不存在的人"],
    })
    assert r5.status_code == 200
    assert not any(t == "standalone_mention" for t, _ in calls)

    # Case 4: Mixed — one resolves, one doesn't → notifier gets only resolved
    calls.clear()
    c.post(f"/api/matters/{matter_id}/mentions", json={
        "target_file": target_file, "body": "mixed",
        "targets": ["邓柯", "不存在的人"],
    })
    sm5 = next(kw for t, kw in calls if t == "standalone_mention")
    assert sm5["mention_open_ids"] == ["ou_dengke"]

    # Case 5: AI passes pinyin (e.g. 'dengke' for 邓柯) → resolved
    # via pivot_user.pinyin exact match.
    calls.clear()
    c.post(f"/api/matters/{matter_id}/mentions", json={
        "target_file": target_file, "body": "ping by pinyin",
        "targets": ["dengke"],
    })
    sm6 = next(kw for t, kw in calls if t == "standalone_mention")
    assert sm6["mention_open_ids"] == ["ou_dengke"]


def test_comment_with_ambiguous_pinyin_returns_422_with_candidates(db, users, tmp_path):
    """Two contacts share pinyin 'zhangbo' (张博 + 张菠). MCP圈人 with 'zhangbo'
    must NOT silently pick one — it must:
      1. Refuse the write (no half-applied state on disk)
      2. Return 422 with the structured candidate list so AI can ask the user
         "你想 @ 哪个 zhangbo?" and re-issue with the chosen open_id.
    """
    calls: list[tuple[str, dict]] = []

    class RecordingNotifier:
        def notify_new_thread(self, **kw): calls.append(("new_thread", kw))
        def notify_new_reply(self, **kw):  calls.append(("new_reply", kw))
        def notify_status_change(self, **kw): calls.append(("status_change", kw))
        def notify_standalone_mention(self, **kw): calls.append(("standalone_mention", kw))

    workspace = _WorkspaceStub(tmp_path)
    users.upsert_from_feishu(open_id="ou_creator", union_id=None, name="作者", avatar_url="")
    users.update_profile("ou_creator", pinyin="zuozhe")
    sessions = SessionStore(db)
    sid = sessions.create("ou_creator")
    current_user = make_current_user(sessions, users, ApiTokenRepo(db))

    _seed_pivot_user_with_feishu(db, pinyin="zhangbo", display_name="张博",
                                 open_id="ou_zhangbo1")
    _seed_pivot_user_with_feishu(db, pinyin="zhangbo", display_name="张菠",
                                 open_id="ou_zhangbo2")

    pivot_users = PivotUserRepo(db)
    bindings = ExternalBindingRepo(db)
    app = FastAPI()
    app.include_router(
        build_router(
            workspace, pivot_users, bindings, RecordingNotifier(),
            ReadStateRepo(db), FavoriteRepo(db), FileReadRepo(db),
            RelevanceEventsRepo(db), DisplayResolver(pivot_users, bindings), current_user,
        )
    )
    c = TestClient(app)
    c.cookies.set("sid", sid)

    r = c.post("/api/matters", json={
        "category": "Pivot", "title": "Ambig",
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]
    target_file = r.json()["initial_timeline_item"]["file"]

    calls.clear()
    r2 = c.post(f"/api/matters/{matter_id}/mentions", json={
        "target_file": target_file,
        "body": "请 review",
        "targets": ["zhangbo"],
    })

    # 422 + structured ambiguities: { code, ambiguities: [{input, candidates}] }
    assert r2.status_code == 422, r2.text
    detail = r2.json()["detail"]
    assert detail["code"] == "ambiguous_mention"
    assert len(detail["ambiguities"]) == 1
    a = detail["ambiguities"][0]
    assert a["input"] == "zhangbo"
    candidate_ids = sorted(c["open_id"] for c in a["candidates"])
    assert candidate_ids == ["ou_zhangbo1", "ou_zhangbo2"]
    assert {c["open_id"]: c["name"] for c in a["candidates"]} == {
        "ou_zhangbo1": "张博",
        "ou_zhangbo2": "张菠",
    }

    # No notifier dispatch
    assert not any(t == "standalone_mention" for t, _ in calls)

    # No mention written: re-fetching the matter should still show the original
    # timeline item with no mentions attached.
    r3 = c.get(f"/api/matters/{matter_id}")
    assert r3.status_code == 200
    timeline = r3.json()["timeline"]
    assert all(not (t.get("mentions") or []) for t in timeline), timeline


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
            body=None, owner_open_id=None, mention_open_ids=None, mention_comments=None,
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
            dm_extra_open_ids=None,
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
    pivot_users = PivotUserRepo(db)
    bindings = ExternalBindingRepo(db)
    app.include_router(
        build_router(
            workspace, pivot_users, bindings, notifier,
            ReadStateRepo(db), FavoriteRepo(db), FileReadRepo(db),
            RelevanceEventsRepo(db), DisplayResolver(pivot_users, bindings), current_user,
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

    # Standalone mention with target — used to TypeError on post_excerpt arg.
    r2 = c.post(f"/api/matters/{matter_id}/mentions", json={
        "target_file": target_file,
        "body": "请关注一下",
        "targets": ["ou_x000000000000000000"],
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
    # Authors are auto-marked as readers of their own files at publish time,
    # so each freshly-created file starts with exactly one reader (ou_1).
    detail0 = client.get(f"/api/matters/{matter_id}").json()
    for item in detail0["timeline"]:
        assert item["readers_count"] == 1
        assert len(item["readers"]) == 1
        assert item["readers"][0]["open_id"] == "ou_1"

    # Re-marking by the same user is a no-op — count stays at 1.
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
    # file2 unaffected (still just the auto-marked author).
    assert by_basename[file2]["readers_count"] == 1
    assert by_basename[file2]["readers"][0]["open_id"] == "ou_1"


# ---------- annotations (Phase 6) ----------


def test_append_annotation_happy_path(client, event_bucket):
    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]
    target = r.json()["initial_timeline_item"]["file"]

    r2 = client.post(f"/api/matters/{matter_id}/annotations", json={
        "target_file": target,
        "type": "evaluation",
        "body": "结构清楚",
    })
    assert r2.status_code == 200, r2.text

    detail = client.get(f"/api/matters/{matter_id}").json()
    annotations = detail["timeline"][0]["annotations"]
    assert len(annotations) == 1
    a = annotations[0]
    assert a["type"] == "evaluation"
    assert a["body"] == "结构清楚"
    assert a["author"] == "dengke"
    # _render_item enriches with display + view
    assert "author_display" in a
    assert "author_view" in a

    # SSE event emitted
    assert any(e.topic == "matter.annotation_appended" for e in event_bucket)


def test_append_annotation_unknown_type_rejected(client):
    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]
    target = r.json()["initial_timeline_item"]["file"]

    r2 = client.post(f"/api/matters/{matter_id}/annotations", json={
        "target_file": target,
        "type": "follow_up_question",  # not in v1 whitelist
        "body": "x",
    })
    assert r2.status_code == 422, r2.text


def test_append_annotation_empty_body_rejected(client):
    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]
    target = r.json()["initial_timeline_item"]["file"]

    r2 = client.post(f"/api/matters/{matter_id}/annotations", json={
        "target_file": target,
        "type": "evaluation",
        "body": "",
    })
    assert r2.status_code == 422


@pytest.mark.parametrize(
    "field,value",
    [
        ("weight", 1.0),
        ("rating", 5),
        ("dimension", "quality"),
        ("sentiment", "positive"),
        ("score_delta", 0.5),
    ],
)
def test_append_annotation_derived_field_rejected(client, field, value):
    """Pydantic guard: each AI-derived field surfaces as 422 with the
    standard validation-error shape. Mirrors writer-side validate_annotation."""
    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]
    target = r.json()["initial_timeline_item"]["file"]

    r2 = client.post(f"/api/matters/{matter_id}/annotations", json={
        "target_file": target,
        "type": "evaluation",
        "body": "x",
        field: value,
    })
    assert r2.status_code == 422
    body = r2.json()
    assert "derived field" in str(body).lower()


def test_append_annotation_missing_target_file_returns_404(client):
    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]

    r2 = client.post(f"/api/matters/{matter_id}/annotations", json={
        "target_file": "discussions/Pivot/" + matter_id + "/does-not-exist.md",
        "type": "evaluation",
        "body": "x",
    })
    assert r2.status_code == 404
    body = r2.json()
    assert body["detail"]["code"] == "annotation_target_not_found"


def test_no_delete_annotation_route_exists(client):
    """v1 contract: annotations are append-only. A DELETE route would
    weaken audit semantics + open up "the eval was deleted" disputes.
    Confirms routing returns 405 (route exists but method not allowed)
    or 404 (route doesn't exist) rather than 200 — both prove the
    operation isn't reachable."""
    r = client.post("/api/matters", json={
        "category": "Pivot", "title": "T",
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    })
    matter_id = r.json()["matter_id"]
    target = r.json()["initial_timeline_item"]["file"]
    r2 = client.post(f"/api/matters/{matter_id}/annotations", json={
        "target_file": target, "type": "evaluation", "body": "x",
    })
    assert r2.status_code == 200

    # Try DELETE on the collection — should be 404 or 405
    r_del = client.delete(f"/api/matters/{matter_id}/annotations")
    assert r_del.status_code in (404, 405), r_del.status_code

    # Try DELETE on an item-style path
    r_del_item = client.delete(f"/api/matters/{matter_id}/annotations/0")
    assert r_del_item.status_code in (404, 405), r_del_item.status_code


# ---------- POST /api/matters/{id}/events (invalidate / restore) ---------


def _create_matter_with_act(client, *, title: str = "Auth", category: str = "Pivot"):
    """Helper: dengke creates a matter (think) + appends an act. Returns
    (matter_id, act_file_path)."""
    r = client.post("/api/matters", json={
        "category": category, "title": title,
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    })
    assert r.status_code == 200, r.text
    matter_id = r.json()["matter_id"]
    r2 = client.post(f"/api/matters/{matter_id}/files", json={
        "type": "act",
        "summary": "推进",
        "body": "",
        "status_change": {"from": "planning", "to": "executing"},
    })
    assert r2.status_code == 200, r2.text
    act_file = r2.json()["item"]["file"]
    return matter_id, act_file


def test_post_event_invalidate_happy_path(client, event_bucket):
    matter_id, act_file = _create_matter_with_act(client)
    # Reset event bucket so we only see the event_appended emission
    event_bucket.clear()

    r = client.post(f"/api/matters/{matter_id}/events", json={
        "target_file": act_file,
        "reason": "misposted",
        "summary": "误发,撤回此文档",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    # event echo
    assert body["event"]["creator"] == "dengke"
    assert body["event"]["quote"] == act_file
    assert body["event"]["reason"] == "misposted"
    assert body["event"]["summary"] == "误发,撤回此文档"
    # target reverse-write echo
    target = body["target"]
    assert target["file"] == act_file
    assert target["invalidated"] is True
    assert target["invalidated_reason"] == "misposted"
    assert target["invalidated_by"] == "dengke"
    assert target["invalidated_at"] is not None
    # emit event
    topics = [e.topic for e in event_bucket]
    assert "matter.event_appended" in topics
    ev = next(e for e in event_bucket if e.topic == "matter.event_appended")
    assert ev.matter_id == matter_id
    assert ev.actor == "dengke"
    assert ev.payload["target_file"] == act_file
    assert ev.payload["reason"] == "misposted"


def test_post_event_restore_happy_path(client):
    matter_id, act_file = _create_matter_with_act(client)
    # First invalidate
    client.post(f"/api/matters/{matter_id}/events", json={
        "target_file": act_file, "reason": "misposted",
    })
    # Then restore
    r = client.post(f"/api/matters/{matter_id}/events", json={
        "target_file": act_file, "reason": "restored",
    })
    assert r.status_code == 200, r.text
    target = r.json()["target"]
    assert target["invalidated"] is False
    # audit trail kept
    assert target["invalidated_at"] is not None
    assert target["invalidated_reason"] == "misposted"
    assert target["invalidated_by"] == "dengke"


def test_post_event_creator_mismatch_403(client, db, users):
    """非作者来失效 → 403."""
    matter_id, act_file = _create_matter_with_act(client)

    # Create liuyu + a TestClient with liuyu's session, hitting the same app.
    from fastapi.testclient import TestClient
    users.upsert_from_feishu(open_id="ou_2", union_id=None, name="刘昱", avatar_url="")
    users.update_profile("ou_2", pinyin="liuyu")
    sessions = SessionStore(db)
    sid_liuyu = sessions.create("ou_2")
    liuyu_client = TestClient(client.app)
    liuyu_client.cookies.set("sid", sid_liuyu)

    r = liuyu_client.post(f"/api/matters/{matter_id}/events", json={
        "target_file": act_file, "reason": "misposted",
    })
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "event_creator_mismatch"


def test_post_event_already_invalidated_409(client):
    matter_id, act_file = _create_matter_with_act(client)
    # First invalidate
    r1 = client.post(f"/api/matters/{matter_id}/events", json={
        "target_file": act_file, "reason": "misposted",
    })
    assert r1.status_code == 200
    # Second invalidate without restore in between
    r2 = client.post(f"/api/matters/{matter_id}/events", json={
        "target_file": act_file, "reason": "inaccurate",
    })
    assert r2.status_code == 409, r2.text
    assert r2.json()["detail"]["code"] == "target_already_invalidated"


def test_post_event_target_not_invalidated_409(client):
    """未失效就发 restored → 409."""
    matter_id, act_file = _create_matter_with_act(client)
    r = client.post(f"/api/matters/{matter_id}/events", json={
        "target_file": act_file, "reason": "restored",
    })
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "target_not_invalidated"


def test_post_event_target_not_found_in_matter_404(client):
    matter_id, _act_file = _create_matter_with_act(client)
    r = client.post(f"/api/matters/{matter_id}/events", json={
        "target_file": "discussions/Pivot/other-matter/001.md",  # 跨 matter
        "reason": "misposted",
    })
    assert r.status_code == 404, r.text
    assert r.json()["detail"]["code"] == "target_not_found"


def test_post_event_matter_not_found_404(client):
    r = client.post("/api/matters/no-such-matter/events", json={
        "target_file": "x", "reason": "misposted",
    })
    assert r.status_code == 404, r.text
    assert r.json()["detail"]["code"] == "matter_not_found"


def test_post_event_invalid_reason_422(client):
    matter_id, act_file = _create_matter_with_act(client)
    r = client.post(f"/api/matters/{matter_id}/events", json={
        "target_file": act_file, "reason": "bogus",
    })
    # Pydantic Literal rejection → 422 (validator层面), not 400
    assert r.status_code == 422, r.text


def test_post_event_full_lifecycle_invalidate_restore_invalidate(client):
    """End-to-end: create → append act → invalidate → restore → re-invalidate."""
    matter_id, act_file = _create_matter_with_act(client)

    # Round 1: invalidate as misposted
    r1 = client.post(f"/api/matters/{matter_id}/events", json={
        "target_file": act_file, "reason": "misposted",
    })
    assert r1.status_code == 200
    assert r1.json()["target"]["invalidated"] is True
    assert r1.json()["target"]["invalidated_reason"] == "misposted"

    # Round 2: restore
    r2 = client.post(f"/api/matters/{matter_id}/events", json={
        "target_file": act_file, "reason": "restored",
    })
    assert r2.status_code == 200
    assert r2.json()["target"]["invalidated"] is False

    # Round 3: re-invalidate as inaccurate (overwrites prior reason)
    r3 = client.post(f"/api/matters/{matter_id}/events", json={
        "target_file": act_file, "reason": "inaccurate",
    })
    assert r3.status_code == 200
    assert r3.json()["target"]["invalidated"] is True
    assert r3.json()["target"]["invalidated_reason"] == "inaccurate"

    # Read full matter detail: timeline must contain 1 think + 1 act + 3 event entries
    detail = client.get(f"/api/matters/{matter_id}").json()
    assert len(detail["timeline"]) == 5


def test_post_event_blocks_quote_to_invalidated_file(client):
    """§5.3: invalidated 后,新 think/act 的 quote 指向它会被拒绝."""
    matter_id, act_file = _create_matter_with_act(client)
    # invalidate
    client.post(f"/api/matters/{matter_id}/events", json={
        "target_file": act_file, "reason": "misposted",
    })
    # try to append a new act that quotes the invalidated act
    r = client.post(f"/api/matters/{matter_id}/files", json={
        "type": "act",
        "summary": "继续",
        "body": "",
        "quote": act_file,
    })
    # Existing /files endpoint maps validator errors; expect 422 with our new code
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "quote_target_invalidated"
