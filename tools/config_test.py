"""Tests for config module (tenant/user context from env)."""
import json

import pytest

from tools import config


class TestConfig:
    def test_from_env_reads_required_vars(self, monkeypatch):
        monkeypatch.setenv("PIVOT_TENANT_ID", "tenant-a")
        monkeypatch.setenv("PIVOT_USER_ID", "huangshengli")
        monkeypatch.setenv("PIVOT_DATA_SPACE_DIR", "/tmp/ws")
        monkeypatch.setenv("PIVOT_APP_NAME", "pivot")

        ctx = config.from_env()
        assert ctx.tenant_id == "tenant-a"
        assert ctx.user_id == "huangshengli"
        assert ctx.data_space_dir == "/tmp/ws"
        assert ctx.app_name == "pivot"

    def test_from_env_raises_when_missing(self, monkeypatch):
        monkeypatch.delenv("PIVOT_TENANT_ID", raising=False)
        with pytest.raises(config.ConfigError, match="PIVOT_TENANT_ID"):
            config.from_env()

    def test_user_id_optional_for_system_triggers(self, monkeypatch):
        monkeypatch.setenv("PIVOT_TENANT_ID", "tenant-a")
        monkeypatch.setenv("PIVOT_DATA_SPACE_DIR", "/tmp/ws")
        monkeypatch.setenv("PIVOT_APP_NAME", "pivot")
        monkeypatch.delenv("PIVOT_USER_ID", raising=False)

        ctx = config.from_env()
        assert ctx.user_id is None


class TestStatusDisplay:
    def test_discuss_status_display_returns_chinese_name(self):
        assert config.get_status_display("discuss", "open") == "讨论中"
        assert config.get_status_display("discuss", "concluded") == "已达成结论"
        assert config.get_status_display("discuss", "produced") == "已转为项目"
        assert config.get_status_display("discuss", "closed") == "已关闭"
        assert config.get_status_display("discuss", "pending") == "暂时搁置"

    def test_unknown_status_returns_status_itself(self):
        assert config.get_status_display("discuss", "foo") == "foo"
        assert config.get_status_display("unknown_module", "open") == "open"


class TestUserMap:
    def test_empty_env_returns_empty_dict(self, monkeypatch):
        monkeypatch.delenv("PIVOT_USER_MAP", raising=False)
        assert config.get_user_map() == {}

    def test_valid_json_parsed(self, monkeypatch):
        monkeypatch.setenv(
            "PIVOT_USER_MAP",
            json.dumps({"ken": {"feishu_id": "ou_xxx", "wecom_id": "wx_xxx"}}),
        )
        result = config.get_user_map()
        assert result == {"ken": {"feishu_id": "ou_xxx", "wecom_id": "wx_xxx"}}

    def test_malformed_json_returns_empty_dict(self, monkeypatch):
        monkeypatch.setenv("PIVOT_USER_MAP", "not-json-at-all")
        assert config.get_user_map() == {}

    def test_non_object_top_level_returns_empty_dict(self, monkeypatch):
        monkeypatch.setenv("PIVOT_USER_MAP", '["a", "b"]')
        assert config.get_user_map() == {}


class TestBuildThreadUrl:
    def test_with_category(self):
        url = config.build_thread_url(category="enclaws", thread="auth-redesign")
        assert url == "https://pivot.example.com/thread/enclaws/auth-redesign"

    def test_without_category(self):
        url = config.build_thread_url(thread="auth-redesign")
        assert url == "https://pivot.example.com/thread/auth-redesign"
