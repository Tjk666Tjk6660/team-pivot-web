"""Tests for feishu_token module."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.notify import feishu_token
from tools.notify.feishu_token import FeishuTokenError, get_tenant_access_token


def _setup_env(monkeypatch, tmp_path: Path, app_id: str = "cli_test", secret: str = "s"):
    monkeypatch.setenv("FEISHU_APP_ID", app_id)
    monkeypatch.setenv("FEISHU_APP_SECRET", secret)
    monkeypatch.setenv("PIVOT_DATA_DIR", str(tmp_path))


def _mock_fetch_success(token: str = "t-new", expire: int = 7200):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "code": 0,
        "msg": "ok",
        "tenant_access_token": token,
        "expire": expire,
    }
    mock_resp.text = ""
    return mock_resp


class TestCacheHit:
    def test_returns_cached_when_not_expired(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        cache_file = tmp_path / ".feishu-token-cli_test.json"
        cache_file.write_text(
            json.dumps({"token": "t-cached", "expire_at": time.time() + 7200})
        )
        with patch.object(feishu_token, "requests") as mock_requests:
            token = get_tenant_access_token()
            assert token == "t-cached"
            mock_requests.post.assert_not_called()


class TestCacheRefresh:
    def test_refetches_when_cache_expired(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        cache_file = tmp_path / ".feishu-token-cli_test.json"
        cache_file.write_text(
            json.dumps({"token": "t-old", "expire_at": time.time() - 100})
        )
        with patch.object(feishu_token, "requests") as mock_requests:
            mock_requests.post.return_value = _mock_fetch_success("t-fresh")
            mock_requests.RequestException = Exception
            token = get_tenant_access_token()
            assert token == "t-fresh"
            # 缓存文件被更新
            new_cache = json.loads(cache_file.read_text())
            assert new_cache["token"] == "t-fresh"

    def test_refetches_when_within_refresh_threshold(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        cache_file = tmp_path / ".feishu-token-cli_test.json"
        # expire_at 还有 60 秒，低于 300 秒阈值 → 应该刷新
        cache_file.write_text(
            json.dumps({"token": "t-almost-expired", "expire_at": time.time() + 60})
        )
        with patch.object(feishu_token, "requests") as mock_requests:
            mock_requests.post.return_value = _mock_fetch_success("t-refreshed")
            mock_requests.RequestException = Exception
            token = get_tenant_access_token()
            assert token == "t-refreshed"

    def test_fetches_when_no_cache_file(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        with patch.object(feishu_token, "requests") as mock_requests:
            mock_requests.post.return_value = _mock_fetch_success("t-first")
            mock_requests.RequestException = Exception
            token = get_tenant_access_token()
            assert token == "t-first"
            # 缓存文件被创建
            cache_file = tmp_path / ".feishu-token-cli_test.json"
            assert cache_file.exists()


class TestMultiAppIsolation:
    def test_different_app_ids_use_different_cache_files(self, monkeypatch, tmp_path):
        # Agent A
        _setup_env(monkeypatch, tmp_path, app_id="cli_A", secret="sA")
        with patch.object(feishu_token, "requests") as mock_requests:
            mock_requests.post.return_value = _mock_fetch_success("token_A")
            mock_requests.RequestException = Exception
            assert get_tenant_access_token() == "token_A"

        # Agent B
        _setup_env(monkeypatch, tmp_path, app_id="cli_B", secret="sB")
        with patch.object(feishu_token, "requests") as mock_requests:
            mock_requests.post.return_value = _mock_fetch_success("token_B")
            mock_requests.RequestException = Exception
            assert get_tenant_access_token() == "token_B"

        # 两个缓存文件独立存在
        cache_a = tmp_path / ".feishu-token-cli_A.json"
        cache_b = tmp_path / ".feishu-token-cli_B.json"
        assert cache_a.exists() and cache_b.exists()
        assert json.loads(cache_a.read_text())["token"] == "token_A"
        assert json.loads(cache_b.read_text())["token"] == "token_B"

    def test_agent_a_cache_does_not_pollute_agent_b(self, monkeypatch, tmp_path):
        # Agent A 已缓存有效 token
        (tmp_path / ".feishu-token-cli_A.json").write_text(
            json.dumps({"token": "t-A", "expire_at": time.time() + 7200})
        )
        # Agent B 启动时应该去获取自己的 token，而不是读到 A 的
        _setup_env(monkeypatch, tmp_path, app_id="cli_B", secret="sB")
        with patch.object(feishu_token, "requests") as mock_requests:
            mock_requests.post.return_value = _mock_fetch_success("t-B")
            mock_requests.RequestException = Exception
            token = get_tenant_access_token()
            assert token == "t-B"
            mock_requests.post.assert_called_once()


class TestUnsafeAppId:
    def test_illegal_chars_in_app_id_are_sanitized(self, monkeypatch, tmp_path):
        # app_id 含路径逃逸字符
        _setup_env(monkeypatch, tmp_path, app_id="../evil/app", secret="s")
        with patch.object(feishu_token, "requests") as mock_requests:
            mock_requests.post.return_value = _mock_fetch_success("t-x")
            mock_requests.RequestException = Exception
            get_tenant_access_token()
            # 缓存文件落在 tmp_path 内，不是路径外
            files = list(tmp_path.glob(".feishu-token-*.json"))
            assert len(files) == 1
            # 文件名中非法字符被替换为下划线
            assert files[0].name == ".feishu-token-___evil_app.json"


class TestMissingCredentials:
    def test_raises_when_app_id_missing(self, monkeypatch, tmp_path):
        monkeypatch.delenv("FEISHU_APP_ID", raising=False)
        monkeypatch.setenv("FEISHU_APP_SECRET", "s")
        monkeypatch.setenv("PIVOT_DATA_DIR", str(tmp_path))
        with pytest.raises(FeishuTokenError, match="FEISHU_APP_ID or FEISHU_APP_SECRET"):
            get_tenant_access_token()

    def test_raises_when_app_secret_missing(self, monkeypatch, tmp_path):
        monkeypatch.setenv("FEISHU_APP_ID", "cli_x")
        monkeypatch.delenv("FEISHU_APP_SECRET", raising=False)
        monkeypatch.setenv("PIVOT_DATA_DIR", str(tmp_path))
        with pytest.raises(FeishuTokenError, match="FEISHU_APP_ID or FEISHU_APP_SECRET"):
            get_tenant_access_token()

    def test_raises_when_both_empty_strings(self, monkeypatch, tmp_path):
        monkeypatch.setenv("FEISHU_APP_ID", "   ")
        monkeypatch.setenv("FEISHU_APP_SECRET", "")
        monkeypatch.setenv("PIVOT_DATA_DIR", str(tmp_path))
        with pytest.raises(FeishuTokenError):
            get_tenant_access_token()


class TestApiFailure:
    def test_raises_on_non_zero_code(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": 10003, "msg": "invalid app_id"}
        mock_resp.text = ""
        with patch.object(feishu_token, "requests") as mock_requests:
            mock_requests.post.return_value = mock_resp
            mock_requests.RequestException = Exception
            with pytest.raises(FeishuTokenError, match="Feishu API error"):
                get_tenant_access_token()

    def test_raises_on_network_error(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        import requests as real_requests
        with patch.object(feishu_token, "requests") as mock_requests:
            mock_requests.RequestException = real_requests.RequestException
            mock_requests.post.side_effect = real_requests.ConnectionError("timeout")
            with pytest.raises(FeishuTokenError, match="Feishu token request failed"):
                get_tenant_access_token()

    def test_raises_on_malformed_response(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": 0}  # 缺 token 和 expire
        mock_resp.text = ""
        with patch.object(feishu_token, "requests") as mock_requests:
            mock_requests.post.return_value = mock_resp
            mock_requests.RequestException = Exception
            with pytest.raises(FeishuTokenError, match="malformed"):
                get_tenant_access_token()


class TestCacheWriteFailure:
    def test_token_still_returned_when_cache_write_fails(self, monkeypatch, tmp_path):
        """缓存文件写入失败不应影响 token 返回。"""
        _setup_env(monkeypatch, tmp_path)

        with patch.object(feishu_token, "requests") as mock_requests:
            mock_requests.post.return_value = _mock_fetch_success("t-ok")
            mock_requests.RequestException = Exception
            with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
                # 不应抛异常，依然返回 token
                token = get_tenant_access_token()
                assert token == "t-ok"


class TestIgnoreMalformedCache:
    def test_ignores_invalid_json_in_cache(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        (tmp_path / ".feishu-token-cli_test.json").write_text("not-json-at-all")
        with patch.object(feishu_token, "requests") as mock_requests:
            mock_requests.post.return_value = _mock_fetch_success("t-new")
            mock_requests.RequestException = Exception
            token = get_tenant_access_token()
            assert token == "t-new"

    def test_ignores_cache_without_required_fields(self, monkeypatch, tmp_path):
        _setup_env(monkeypatch, tmp_path)
        (tmp_path / ".feishu-token-cli_test.json").write_text(
            json.dumps({"token": "t-incomplete"})  # 缺 expire_at
        )
        with patch.object(feishu_token, "requests") as mock_requests:
            mock_requests.post.return_value = _mock_fetch_success("t-fresh")
            mock_requests.RequestException = Exception
            token = get_tenant_access_token()
            assert token == "t-fresh"
