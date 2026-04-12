"""Smoke test for the mock_feishu_server conftest fixture."""
import requests


def test_mock_feishu_server_captures_post(mock_feishu_server):
    url = mock_feishu_server["url"]
    received = mock_feishu_server["received"]

    resp = requests.post(url, json={"hello": "world"}, timeout=3)
    assert resp.status_code == 200
    assert resp.json() == {"code": 0}
    assert len(received) == 1
    assert received[0] == {"hello": "world"}
