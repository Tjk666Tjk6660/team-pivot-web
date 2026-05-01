"""Tests for `server.api.daily_report_v2` admin endpoints.

覆盖:
- jobs CRUD: list / create / get / update / status / delete(soft archive)
- run-now / manual-trigger: 后台 thread 跑完写 runs.finish
- runs 历史:分页 / 单条详情(含 debug_json)
- admin-notify GET/PUT 配置往返
- feishu-chats 列表
- 鉴权:缺 X-Admin-Password → 401
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.daily_report_v2 import (
    KEY_ADMIN_NOTIFY_CHAT_IDS,
    KEY_ADMIN_NOTIFY_OPEN_IDS,
    build_router,
)
from server.auth.admin import ADMIN_PASSWORD
from server.auth.deps import make_current_user_cookie_only
from server.auth.session import SessionStore
from server.daily_report.jobs_repo import JobsRepo
from server.daily_report.runs_repo import RunsRepo
from server.daily_report.window import CHINA_TZ
from server.db import Database
from server.notify import NoOpNotifier
from server.settings import SettingsRepo
from server.users import UserRepo
from server.workspace_runtime import WorkspaceRuntime


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


def _admin_headers() -> dict[str, str]:
    return {"X-Admin-Password": ADMIN_PASSWORD}


class FakeNotifier(NoOpNotifier):
    """记录发送调用,默认全部成功。可注入失败模式。"""

    def __init__(self) -> None:
        self.broadcast_calls: list[tuple[dict, str]] = []
        self.chat_calls: list[tuple[list[str], str]] = []
        self.user_calls: list[tuple[list[str], str]] = []
        self.bot_chats: list[dict] = [
            {"chat_id": "oc_111", "name": "默认群", "avatar": ""},
            {"chat_id": "oc_222", "name": "管理员群", "avatar": ""},
        ]
        self.fail_mode: str | None = None  # "broadcast" / "chats" / "users"

    def broadcast_card(self, card: dict, *, event: str) -> None:
        if self.fail_mode == "broadcast":
            raise RuntimeError("broadcast fail")
        self.broadcast_calls.append((card, event))

    def send_card_to_chats(self, card, chat_ids, *, event):
        self.chat_calls.append((list(chat_ids), event))
        if self.fail_mode == "chats":
            return 0, len(chat_ids), [
                {"to": c, "error": "fake_fail"} for c in chat_ids
            ]
        return len(chat_ids), len(chat_ids), []

    def send_card_to_users(self, card, open_ids, *, event):
        self.user_calls.append((list(open_ids), event))
        if self.fail_mode == "users":
            return 0, len(open_ids), [
                {"to": o, "error": "fake_fail"} for o in open_ids
            ]
        return len(open_ids), len(open_ids), []

    def list_bot_chats(self) -> list[dict]:
        return list(self.bot_chats)


@pytest.fixture
def app_state(tmp_path):
    db_path = tmp_path / "data.db"
    db = Database(db_path)
    users_repo = UserRepo(db)
    users_repo.upsert_from_feishu(
        open_id="ou_admin", union_id=None, name="Admin", avatar_url="",
    )
    users_repo.update_profile("ou_admin", pinyin="admin")
    sessions = SessionStore(db)
    sid = sessions.create("ou_admin")
    settings = SettingsRepo(db)
    notifier = FakeNotifier()
    workspace = WorkspaceRuntime(base_dir=tmp_path / "git", settings=settings)
    # 让 workspace.path / "index" 存在,run-now 才不会走 rc=2
    (tmp_path / "git" / "index").mkdir(parents=True, exist_ok=True)

    jobs_repo = JobsRepo(db)
    runs_repo = RunsRepo(db)

    cu_cookie = make_current_user_cookie_only(sessions, users_repo)
    app = FastAPI()
    app.include_router(build_router(
        workspace=workspace,
        settings=settings,
        notifier=notifier,
        db_path=db_path,
        jobs_repo=jobs_repo,
        runs_repo=runs_repo,
        current_user_cookie_only=cu_cookie,
    ))
    return {
        "app": app,
        "sid": sid,
        "settings": settings,
        "jobs": jobs_repo,
        "runs": runs_repo,
        "notifier": notifier,
        "db_path": db_path,
        "tmp_path": tmp_path,
    }


def _client(state) -> TestClient:
    c = TestClient(state["app"])
    c.cookies.set("sid", state["sid"])
    return c


def _wait_run_finished(client, run_id: int, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = client.get(f"/api/admin/daily-report/runs/{run_id}",
                       headers=_admin_headers())
        if r.status_code == 200 and r.json().get("finished_at"):
            return r.json()
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not finish in {timeout}s")


# --------------------------------------------------------------------------- #
# auth                                                                        #
# --------------------------------------------------------------------------- #


def test_missing_admin_header_returns_401(app_state):
    c = _client(app_state)
    r = c.get("/api/admin/daily-report/jobs")
    assert r.status_code == 401


# --------------------------------------------------------------------------- #
# jobs CRUD                                                                   #
# --------------------------------------------------------------------------- #


def test_list_jobs_empty(app_state):
    c = _client(app_state)
    r = c.get("/api/admin/daily-report/jobs", headers=_admin_headers())
    assert r.status_code == 200
    assert r.json() == []


def test_create_job_minimal(app_state):
    c = _client(app_state)
    payload = {
        "name": "公司视角早报",
        "view": "company",
        "push_time": "09:30",
        "receiver_type": "groups",
    }
    r = c.post("/api/admin/daily-report/jobs",
               headers=_admin_headers(), json=payload)
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["id"] > 0
    assert job["name"] == "公司视角早报"
    assert job["view"] == "company"
    assert job["status"] == "active"
    assert job["push_freq"] == "weekdays"
    assert job["window_hours"] == 24
    assert job["channel"] == "feishu"
    assert job["receiver_type"] == "groups"
    assert job["receiver_ids"] is None
    assert job["next_run_at"] is not None  # active → 算了 next_run_at
    assert job["created_by"] == "ou_admin"


def test_create_job_accepts_new_push_freq_values(app_state):
    """周一 / 月初 / 月末等新枚举值能被 API 接受并写入 next_run_at"""
    c = _client(app_state)
    for freq in ["mon", "fri", "sun", "month_start", "month_end"]:
        r = c.post("/api/admin/daily-report/jobs", headers=_admin_headers(),
                   json={
                       "name": f"job-{freq}",
                       "view": "company",
                       "push_time": "09:30",
                       "push_freq": freq,
                       "receiver_type": "groups",
                   })
        assert r.status_code == 201, f"freq={freq}: {r.text}"
        body = r.json()
        assert body["push_freq"] == freq
        assert body["next_run_at"] is not None


def test_create_job_rejects_unknown_push_freq(app_state):
    """超出 Literal 的值应该被 Pydantic 拦下"""
    c = _client(app_state)
    r = c.post("/api/admin/daily-report/jobs", headers=_admin_headers(),
               json={
                   "name": "x",
                   "view": "company",
                   "push_time": "09:30",
                   "push_freq": "fortnightly",
                   "receiver_type": "groups",
               })
    assert r.status_code == 422


def test_create_job_paused_no_next_run_at(app_state):
    c = _client(app_state)
    r = c.post("/api/admin/daily-report/jobs", headers=_admin_headers(),
               json={
                   "name": "paused job",
                   "view": "personal",
                   "push_time": "10:00",
                   "receiver_type": "users",
                   "receiver_ids": ["ou_a", "ou_b"],
                   "status": "paused",
               })
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["status"] == "paused"
    assert job["next_run_at"] is None
    assert job["receiver_ids"] == ["ou_a", "ou_b"]


def test_create_job_validates_push_time(app_state):
    c = _client(app_state)
    r = c.post("/api/admin/daily-report/jobs", headers=_admin_headers(),
               json={
                   "name": "bad time",
                   "view": "company",
                   "push_time": "25:99",
                   "receiver_type": "groups",
               })
    assert r.status_code == 422


def test_get_job_not_found(app_state):
    c = _client(app_state)
    r = c.get("/api/admin/daily-report/jobs/9999", headers=_admin_headers())
    assert r.status_code == 404


def test_get_job_after_create(app_state):
    job = app_state["jobs"].create(
        name="x", view="company", push_time="09:30",
        receiver_type="groups",
    )
    c = _client(app_state)
    r = c.get(f"/api/admin/daily-report/jobs/{job.id}", headers=_admin_headers())
    assert r.status_code == 200
    assert r.json()["id"] == job.id


def test_update_job_partial_keeps_other_fields(app_state):
    job = app_state["jobs"].create(
        name="orig", view="company", push_time="09:30",
        receiver_type="groups",
        next_run_at=datetime(2026, 5, 1, 9, 30, tzinfo=CHINA_TZ),
    )
    c = _client(app_state)
    r = c.put(f"/api/admin/daily-report/jobs/{job.id}",
              headers=_admin_headers(),
              json={"name": "renamed"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["name"] == "renamed"
    assert out["push_time"] == "09:30"   # 没传 → 没变
    # next_run_at 没改 push_time/freq → 没重算
    assert out["next_run_at"] is not None


def test_update_job_push_time_recomputes_next_run_at(app_state):
    """改 push_time 且 status=active → 重算 next_run_at。"""
    job = app_state["jobs"].create(
        name="x", view="company", push_time="09:30",
        receiver_type="groups",
        next_run_at=datetime(2026, 5, 1, 9, 30, tzinfo=CHINA_TZ),
    )
    c = _client(app_state)
    r = c.put(f"/api/admin/daily-report/jobs/{job.id}",
              headers=_admin_headers(),
              json={"push_time": "08:00"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["push_time"] == "08:00"
    # next_run_at 重算了:跟原来不同
    assert out["next_run_at"] is not None
    new_next = datetime.fromisoformat(out["next_run_at"])
    assert new_next.hour == 8 and new_next.minute == 0


def test_update_job_clears_receiver_ids_with_empty_list(app_state):
    job = app_state["jobs"].create(
        name="x", view="company", push_time="09:30",
        receiver_type="groups", receiver_ids=["oc_1", "oc_2"],
    )
    c = _client(app_state)
    r = c.put(f"/api/admin/daily-report/jobs/{job.id}",
              headers=_admin_headers(),
              json={"receiver_ids": []})
    assert r.status_code == 200
    assert r.json()["receiver_ids"] is None


def test_update_archived_job_returns_409(app_state):
    job = app_state["jobs"].create(
        name="x", view="company", push_time="09:30",
        receiver_type="groups", status="archived",
    )
    c = _client(app_state)
    r = c.put(f"/api/admin/daily-report/jobs/{job.id}",
              headers=_admin_headers(), json={"name": "no"})
    assert r.status_code == 409


def test_update_status_to_active_sets_next_run_at(app_state):
    job = app_state["jobs"].create(
        name="x", view="company", push_time="09:30",
        receiver_type="groups", status="paused",
    )
    c = _client(app_state)
    r = c.put(f"/api/admin/daily-report/jobs/{job.id}/status",
              headers=_admin_headers(), json={"status": "active"})
    assert r.status_code == 200
    out = r.json()
    assert out["status"] == "active"
    assert out["next_run_at"] is not None


def test_update_status_to_paused_clears_next_run_at(app_state):
    job = app_state["jobs"].create(
        name="x", view="company", push_time="09:30",
        receiver_type="groups",
        next_run_at=datetime.now(tz=CHINA_TZ) + timedelta(hours=1),
    )
    c = _client(app_state)
    r = c.put(f"/api/admin/daily-report/jobs/{job.id}/status",
              headers=_admin_headers(), json={"status": "paused"})
    assert r.status_code == 200
    out = r.json()
    assert out["status"] == "paused"
    assert out["next_run_at"] is None


def test_delete_job_archives(app_state):
    job = app_state["jobs"].create(
        name="x", view="company", push_time="09:30",
        receiver_type="groups",
    )
    c = _client(app_state)
    r = c.delete(f"/api/admin/daily-report/jobs/{job.id}",
                 headers=_admin_headers())
    assert r.status_code == 200
    assert r.json() == {"ok": True}

    # status=archived,默认 list 不返回
    r = c.get("/api/admin/daily-report/jobs", headers=_admin_headers())
    assert r.json() == []
    # include_archived=true 才返回
    r = c.get("/api/admin/daily-report/jobs?include_archived=true",
              headers=_admin_headers())
    body = r.json()
    assert len(body) == 1
    assert body[0]["status"] == "archived"


# --------------------------------------------------------------------------- #
# run-now / manual-trigger                                                    #
# --------------------------------------------------------------------------- #


def test_run_now_starts_thread_and_records_run(app_state):
    job = app_state["jobs"].create(
        name="x", view="company", push_time="09:30",
        receiver_type="groups",
    )
    c = _client(app_state)
    fake_debug = {"status": "rendered", "n_active": 3,
                  "receivers": {"sent": 1, "total": 1}}
    with patch(
        "server.daily_report.runner.run_daily_report_for_job",
        return_value=(0, fake_debug),
    ):
        r = c.post(f"/api/admin/daily-report/jobs/{job.id}/run-now",
                   headers=_admin_headers(),
                   json={"dry_run": True, "no_ai": True})
        assert r.status_code == 200, r.text
        body = r.json()
        run_id = body["run_id"]
        assert body["ok"] is True
        assert run_id > 0

        finished = _wait_run_finished(c, run_id)
        assert finished["status"] == "succeeded"
        assert finished["rc"] == 0
        assert finished["job_id"] == job.id
        assert finished["trigger_type"] == "retry"
        assert finished["cards_sent"] == 1
        assert finished["cards_total"] == 1
        # debug_json 是 detail 字段
        debug = json.loads(finished["debug_json"])
        assert debug["status"] == "rendered"
        assert debug["n_active"] == 3


def test_run_now_archived_returns_409(app_state):
    job = app_state["jobs"].create(
        name="x", view="company", push_time="09:30",
        receiver_type="groups", status="archived",
    )
    c = _client(app_state)
    r = c.post(f"/api/admin/daily-report/jobs/{job.id}/run-now",
               headers=_admin_headers(), json={})
    assert r.status_code == 409


def test_run_now_records_failure(app_state):
    job = app_state["jobs"].create(
        name="x", view="company", push_time="09:30",
        receiver_type="groups",
    )
    c = _client(app_state)
    with patch(
        "server.daily_report.runner.run_daily_report_for_job",
        return_value=(2, {"error": "workspace missing"}),
    ):
        r = c.post(f"/api/admin/daily-report/jobs/{job.id}/run-now",
                   headers=_admin_headers(),
                   json={"dry_run": False, "no_ai": True})
        assert r.status_code == 200
        run_id = r.json()["run_id"]
        finished = _wait_run_finished(c, run_id)
        assert finished["status"] == "failed"
        assert finished["rc"] == 2
        assert "workspace missing" in (finished["error"] or "")


def test_run_now_records_crash(app_state):
    job = app_state["jobs"].create(
        name="x", view="company", push_time="09:30",
        receiver_type="groups",
    )
    c = _client(app_state)
    with patch(
        "server.daily_report.runner.run_daily_report_for_job",
        side_effect=RuntimeError("kaboom"),
    ):
        r = c.post(f"/api/admin/daily-report/jobs/{job.id}/run-now",
                   headers=_admin_headers(), json={})
        run_id = r.json()["run_id"]
        finished = _wait_run_finished(c, run_id)
        assert finished["status"] == "failed"
        assert finished["rc"] == -1
        assert "RuntimeError" in (finished["error"] or "")
        assert "kaboom" in (finished["error"] or "")


def test_manual_trigger_creates_run_with_no_job_id(app_state):
    c = _client(app_state)
    fake_debug = {"status": "rendered",
                  "receivers": {"sent": 2, "total": 2}}
    with patch(
        "server.daily_report.runner.run_daily_report_for_job",
        return_value=(0, fake_debug),
    ):
        r = c.post("/api/admin/daily-report/manual-trigger",
                   headers=_admin_headers(),
                   json={
                       "view": "company",
                       "window_hours": 12,
                       "receiver_type": "groups",
                       "dry_run": True,
                       "no_ai": True,
                   })
        assert r.status_code == 200, r.text
        run_id = r.json()["run_id"]
        finished = _wait_run_finished(c, run_id)
        assert finished["status"] == "succeeded"
        assert finished["job_id"] is None      # 手动触发不绑 job
        assert finished["trigger_type"] == "manual"


def test_manual_trigger_requires_receiver_ids_for_users(app_state):
    c = _client(app_state)
    r = c.post("/api/admin/daily-report/manual-trigger",
               headers=_admin_headers(),
               json={
                   "view": "personal",
                   "receiver_type": "users",
                   # 漏 receiver_ids
               })
    assert r.status_code == 400


def test_manual_trigger_with_explicit_time_range(app_state):
    """显式 since/until 模式 —— 跑历史时段。"""
    c = _client(app_state)
    fake_debug = {"status": "rendered",
                  "receivers": {"sent": 0, "total": 0}}
    with patch(
        "server.daily_report.runner.run_daily_report_for_job",
        return_value=(0, fake_debug),
    ):
        r = c.post("/api/admin/daily-report/manual-trigger",
                   headers=_admin_headers(),
                   json={
                       "view": "company",
                       "since": "2026-04-29T00:00:00+08:00",
                       "until": "2026-04-30T00:00:00+08:00",
                       "receiver_type": "groups",
                       "dry_run": True,
                       "no_ai": True,
                   })
        assert r.status_code == 200, r.text
        run_id = r.json()["run_id"]
        finished = _wait_run_finished(c, run_id)
        assert finished["status"] == "succeeded"


def test_manual_trigger_rejects_inverted_time_range(app_state):
    c = _client(app_state)
    r = c.post("/api/admin/daily-report/manual-trigger",
               headers=_admin_headers(),
               json={
                   "view": "company",
                   "since": "2026-04-30T00:00:00+08:00",
                   "until": "2026-04-29T00:00:00+08:00",  # until < since
                   "receiver_type": "groups",
               })
    assert r.status_code == 400
    assert "since must be before until" in r.text


def test_manual_trigger_rejects_overlong_time_range(app_state):
    c = _client(app_state)
    r = c.post("/api/admin/daily-report/manual-trigger",
               headers=_admin_headers(),
               json={
                   "view": "company",
                   "since": "2026-04-01T00:00:00+08:00",
                   "until": "2026-04-30T00:00:00+08:00",  # 29 天 > 168h
                   "receiver_type": "groups",
               })
    assert r.status_code == 400
    assert "too large" in r.text


def test_manual_trigger_rejects_partial_time_range(app_state):
    """只给 since 不给 until(或反之)应当报错。"""
    c = _client(app_state)
    r = c.post("/api/admin/daily-report/manual-trigger",
               headers=_admin_headers(),
               json={
                   "view": "company",
                   "since": "2026-04-29T00:00:00+08:00",
                   # 没有 until
                   "receiver_type": "groups",
               })
    assert r.status_code == 400
    assert "together" in r.text


# --------------------------------------------------------------------------- #
# runs 历史                                                                   #
# --------------------------------------------------------------------------- #


def test_list_runs_for_job_pagination(app_state):
    job = app_state["jobs"].create(
        name="x", view="company", push_time="09:30",
        receiver_type="groups",
    )
    # 插 25 条 runs
    base = datetime.now(tz=CHINA_TZ) - timedelta(hours=1)
    for i in range(25):
        rid = app_state["runs"].start(
            job_id=job.id, trigger_type="scheduled",
            view="company",
            started_at=base + timedelta(minutes=i),
        )
        app_state["runs"].finish(
            rid, status="succeeded", rc=0,
            cards_sent=1, cards_total=1,
        )

    c = _client(app_state)
    r = c.get(f"/api/admin/daily-report/jobs/{job.id}/runs?page=1&size=10",
              headers=_admin_headers())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 25
    assert body["page"] == 1
    assert body["size"] == 10
    assert len(body["items"]) == 10
    # DESC 顺序:最新的在前
    times = [item["started_at"] for item in body["items"]]
    assert times == sorted(times, reverse=True)

    # 第三页只剩 5 条
    r3 = c.get(f"/api/admin/daily-report/jobs/{job.id}/runs?page=3&size=10",
               headers=_admin_headers())
    assert len(r3.json()["items"]) == 5


def test_list_runs_for_unknown_job_returns_404(app_state):
    c = _client(app_state)
    r = c.get("/api/admin/daily-report/jobs/9999/runs",
              headers=_admin_headers())
    assert r.status_code == 404


def test_get_run_returns_debug_json(app_state):
    rid = app_state["runs"].start(
        job_id=None, trigger_type="manual", view="company",
    )
    app_state["runs"].finish(
        rid, status="succeeded", rc=0,
        debug_json='{"hello":"world"}',
    )
    c = _client(app_state)
    r = c.get(f"/api/admin/daily-report/runs/{rid}",
              headers=_admin_headers())
    assert r.status_code == 200
    assert r.json()["debug_json"] == '{"hello":"world"}'


def test_get_run_not_found(app_state):
    c = _client(app_state)
    r = c.get("/api/admin/daily-report/runs/9999",
              headers=_admin_headers())
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# admin-notify 配置                                                           #
# --------------------------------------------------------------------------- #


def test_admin_notify_get_default_empty(app_state):
    c = _client(app_state)
    r = c.get("/api/admin/daily-report/admin-notify",
              headers=_admin_headers())
    assert r.status_code == 200
    assert r.json() == {"chat_ids": [], "open_ids": []}


def test_admin_notify_put_and_round_trip(app_state):
    c = _client(app_state)
    payload = {"chat_ids": ["oc_alert"], "open_ids": ["ou_admin1", "ou_admin2"]}
    r = c.put("/api/admin/daily-report/admin-notify",
              headers=_admin_headers(), json=payload)
    assert r.status_code == 200
    assert r.json() == {"ok": True}

    # 直接读 settings 验证
    raw_chat = app_state["settings"].get(KEY_ADMIN_NOTIFY_CHAT_IDS)
    raw_open = app_state["settings"].get(KEY_ADMIN_NOTIFY_OPEN_IDS)
    assert json.loads(raw_chat) == ["oc_alert"]
    assert json.loads(raw_open) == ["ou_admin1", "ou_admin2"]

    # GET 也反映
    r = c.get("/api/admin/daily-report/admin-notify",
              headers=_admin_headers())
    assert r.json() == payload


def test_admin_notify_get_handles_corrupt_json(app_state):
    """settings 里坏 JSON → 返回空列表,不崩。"""
    app_state["settings"].set(KEY_ADMIN_NOTIFY_CHAT_IDS, "not-json")
    c = _client(app_state)
    r = c.get("/api/admin/daily-report/admin-notify",
              headers=_admin_headers())
    assert r.status_code == 200
    assert r.json()["chat_ids"] == []


# --------------------------------------------------------------------------- #
# feishu-chats                                                                #
# --------------------------------------------------------------------------- #


def test_feishu_chats_lists_bot_groups(app_state):
    c = _client(app_state)
    r = c.get("/api/admin/daily-report/feishu-chats",
              headers=_admin_headers())
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert body[0]["chat_id"] == "oc_111"
    assert body[0]["name"] == "默认群"
