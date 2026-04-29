"""Tests for `server.api.daily_report` admin endpoints (Phase 5).

Covers:
- GET /config: defaults when settings empty
- PUT /config: writes to settings table
- Roundtrip: PUT 后 GET 反映新值
- Auth: 缺 X-Admin-Password 头 → 401
- Trigger when disabled → 409
- Trigger happy path: 后台 thread + last-run 反映完成状态
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.daily_report import build_router
from server.api_tokens import ApiTokenRepo
from server.auth.admin import ADMIN_PASSWORD
from server.auth.deps import make_current_user_cookie_only
from server.auth.session import SessionStore
from server.db import Database
from server.notify import NoOpNotifier
from server.settings import SettingsRepo
from server.users import UserRepo
from server.workspace_runtime import WorkspaceRuntime


# --------------------------------------------------------------------------- #
# fixtures                                                                    #
# --------------------------------------------------------------------------- #


def _admin_headers() -> dict[str, str]:
    return {"X-Admin-Password": ADMIN_PASSWORD}


@pytest.fixture
def app_state(tmp_path):
    db_path = tmp_path / "data.db"
    db = Database(db_path)
    users = UserRepo(db)
    users.upsert_from_feishu(open_id="ou_admin", union_id=None,
                             name="Admin", avatar_url="")
    users.update_profile("ou_admin", pinyin="admin")
    sessions = SessionStore(db)
    sid = sessions.create("ou_admin")
    settings = SettingsRepo(db)
    notifier = NoOpNotifier()
    workspace = WorkspaceRuntime(base_dir=tmp_path / "git", settings=settings)

    cu_cookie = make_current_user_cookie_only(sessions, users)

    app = FastAPI()
    app.include_router(build_router(
        workspace=workspace,
        settings=settings,
        notifier=notifier,
        db_path=db_path,
        current_user_cookie_only=cu_cookie,
    ))
    return app, sid, settings, db_path


# --------------------------------------------------------------------------- #
# config GET defaults                                                         #
# --------------------------------------------------------------------------- #


def test_config_get_returns_defaults_when_empty(app_state):
    app, sid, _settings, _db = app_state
    client = TestClient(app)
    client.cookies.set("sid", sid)
    r = client.get(
        "/api/admin/daily-report/config", headers=_admin_headers(),
    )
    assert r.status_code == 200, r.text
    assert r.json() == {
        "enabled": True,
        "company_enabled": True,
        "personal_enabled": True,
        "time_window_hours": 24,
        "push_time": "09:30",
        "push_freq": "weekdays",
    }


def test_config_get_requires_admin_header(app_state):
    app, sid, _settings, _db = app_state
    client = TestClient(app)
    client.cookies.set("sid", sid)
    r = client.get("/api/admin/daily-report/config")  # no admin header
    assert r.status_code == 401


# --------------------------------------------------------------------------- #
# config PUT roundtrip                                                        #
# --------------------------------------------------------------------------- #


def test_config_put_writes_settings_and_round_trips(app_state):
    app, sid, settings, _db = app_state
    client = TestClient(app)
    client.cookies.set("sid", sid)
    payload = {
        "enabled": True,
        "company_enabled": True,
        "personal_enabled": False,
        "time_window_hours": 12,
        "push_time": "08:15",
        "push_freq": "daily",
    }
    r = client.put(
        "/api/admin/daily-report/config",
        headers=_admin_headers(), json=payload,
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}

    # Direct settings table check
    assert settings.get("daily_report.enabled") == "1"
    assert settings.get("daily_report.personal_enabled") == "0"
    assert settings.get("daily_report.time_window_hours") == "12"
    assert settings.get("daily_report.push_time") == "08:15"
    assert settings.get("daily_report.push_freq") == "daily"

    # GET reflects new values
    r = client.get(
        "/api/admin/daily-report/config", headers=_admin_headers(),
    )
    assert r.json()["personal_enabled"] is False
    assert r.json()["time_window_hours"] == 12
    assert r.json()["push_time"] == "08:15"
    assert r.json()["push_freq"] == "daily"


def test_config_put_validates_window_hours(app_state):
    """time_window_hours 限定 [1, 168] —— 无理范围应 422。"""
    app, sid, _settings, _db = app_state
    client = TestClient(app)
    client.cookies.set("sid", sid)
    bad = {
        "enabled": True, "company_enabled": True, "personal_enabled": True,
        "time_window_hours": 9999, "push_time": "09:30",
        "push_freq": "weekdays",
    }
    r = client.put(
        "/api/admin/daily-report/config",
        headers=_admin_headers(), json=bad,
    )
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# trigger                                                                     #
# --------------------------------------------------------------------------- #


def test_trigger_when_disabled_returns_409(app_state):
    app, sid, settings, _db = app_state
    settings.set("daily_report.enabled", "0")

    client = TestClient(app)
    client.cookies.set("sid", sid)
    r = client.post(
        "/api/admin/daily-report/trigger",
        headers=_admin_headers(),
        json={"dry_run": True, "no_ai": True},
    )
    assert r.status_code == 409
    assert "disabled" in r.json()["detail"]


def test_trigger_starts_thread_and_last_run_reflects_completion(app_state):
    app, sid, _settings, _db = app_state
    client = TestClient(app)
    client.cookies.set("sid", sid)

    # mock run_daily_report to return immediately so the thread completes fast
    def fake_run(*, db_path, workspace_index_dir, dry_run, no_ai, notifier):
        return 0, {"status": "rendered", "n_active": 5}

    with patch(
        "server.api.daily_report.run_daily_report", side_effect=fake_run,
    ):
        r = client.post(
            "/api/admin/daily-report/trigger",
            headers=_admin_headers(),
            json={"dry_run": True, "no_ai": True},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        run_id = body["run_id"]
        assert run_id.startswith("run-")
        assert body["started_at"]

        # Wait briefly for thread to finish
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            r = client.get(
                "/api/admin/daily-report/last-run",
                headers=_admin_headers(),
            )
            assert r.status_code == 200
            data = r.json()
            if data["finished_at"]:
                break
            time.sleep(0.05)

        assert data["run_id"] == run_id
        assert data["rc"] == 0
        assert data["debug"]["status"] == "rendered"
        assert data["debug"]["n_active"] == 5
        assert data["error"] is None


def test_trigger_thread_crash_recorded_in_last_run(app_state):
    app, sid, _settings, _db = app_state
    client = TestClient(app)
    client.cookies.set("sid", sid)

    def boom(*, db_path, workspace_index_dir, dry_run, no_ai, notifier):
        raise RuntimeError("kaboom")

    with patch(
        "server.api.daily_report.run_daily_report", side_effect=boom,
    ):
        r = client.post(
            "/api/admin/daily-report/trigger",
            headers=_admin_headers(),
            json={"dry_run": True, "no_ai": True},
        )
        assert r.status_code == 200

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            data = client.get(
                "/api/admin/daily-report/last-run",
                headers=_admin_headers(),
            ).json()
            if data["finished_at"]:
                break
            time.sleep(0.05)

        assert data["rc"] == -1
        assert "RuntimeError" in (data["error"] or "")
        assert "kaboom" in (data["error"] or "")
