from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from server.mcp.tools import (
    MatterApiClient,
    ToolError,
    tool_list_matters,
    tool_resolve_context,
)


def _make_client(matter: dict, timeline: list[dict]) -> MatterApiClient:
    client = MagicMock(spec=MatterApiClient)
    client.get_matter.return_value = {"matter": matter, "timeline": timeline}
    return client


def test_resolve_context_matter_only():
    client = _make_client(
        {"id": "auth", "title": "Auth Redesign", "current_status": "executing",
         "updated_at": "2026-04-23T10:00:00+08:00"},
        [],
    )
    out = tool_resolve_context(
        {"url": "https://pivot.enclaws.ai/m/auth"},
        client,
    )
    assert out["matter_id"] == "auth"
    assert out["file_path"] is None
    assert "Auth Redesign" in out["user_facing_summary"]
    assert "executing" in out["user_facing_summary"]


def test_resolve_context_with_file():
    client = _make_client(
        {"id": "auth", "title": "Auth", "current_status": "executing",
         "updated_at": "2026-04-23T10:00:00+08:00"},
        [{"file": "005.md", "type": "think", "summary": "梳理问题",
          "created_at": "", "creator": "a", "owner": "a"}],
    )
    out = tool_resolve_context(
        {"url": "https://pivot.enclaws.ai/m/auth/f/005.md"},
        client,
    )
    assert out["file_path"] == "005.md"
    assert "think" in out["user_facing_summary"]
    assert "梳理问题" in out["user_facing_summary"]


def test_resolve_context_bad_url():
    client = _make_client({}, [])
    with pytest.raises(ToolError) as ei:
        tool_resolve_context({"url": "not a url"}, client)
    assert ei.value.status == 400


def test_resolve_context_file_not_in_matter():
    client = _make_client(
        {"id": "auth", "title": "T", "current_status": "x", "updated_at": ""},
        [{"file": "001.md", "type": "think", "summary": "", "created_at": "",
          "creator": "a", "owner": "a"}],
    )
    with pytest.raises(ToolError) as ei:
        tool_resolve_context(
            {"url": "https://pivot.enclaws.ai/m/auth/f/999.md"},
            client,
        )
    assert ei.value.status == 404
    assert ei.value.detail == "file_not_in_matter"


def test_list_matters_passes_filters():
    client = MagicMock(spec=MatterApiClient)
    client.list_matters.return_value = [
        {
            "id": "a", "title": "A", "current_status": "executing",
            "updated_at": "2026-04-23T10:00:00+08:00", "file_count": 3,
        },
    ]
    out = tool_list_matters(
        {"status": "executing", "q": "auth"},
        client,
    )
    client.list_matters.assert_called_once_with(
        status="executing", owner=None, q="auth",
    )
    assert len(out["items"]) == 1
    assert out["items"][0]["id"] == "a"


def test_list_matters_no_filters():
    client = MagicMock(spec=MatterApiClient)
    client.list_matters.return_value = []
    out = tool_list_matters({}, client)
    assert out["items"] == []
    client.list_matters.assert_called_once_with(
        status=None, owner=None, q=None,
    )


from server.mcp.tools import tool_get_matter, tool_read_files


def test_get_matter_strips_bodies():
    client = MagicMock(spec=MatterApiClient)
    client.get_matter.return_value = {
        "matter": {"id": "a", "title": "T", "current_status": "x", "updated_at": ""},
        "timeline": [
            {"file": "001.md", "type": "think", "summary": "s1",
             "created_at": "", "creator": "u", "owner": "u",
             "body": "这是正文不应该出现", "refer": []},
        ],
    }
    out = tool_get_matter({"matter_id": "a"}, client)
    assert "body" not in out["timeline"][0]
    assert out["timeline"][0]["file"] == "001.md"


def test_get_matter_accepts_owner_change_event():
    client = MagicMock(spec=MatterApiClient)
    client.get_matter.return_value = {
        "matter": {"id": "a", "title": "T", "current_status": "planning", "updated_at": ""},
        "timeline": [
            {"file": "001.md", "type": "think", "summary": "s1",
             "created_at": "", "creator": "u", "owner": "u", "body": "hidden"},
            {"type": "owner_change", "created_at": "", "actor": "u",
             "from_owner": "u", "to_owner": "v", "reason": "handoff",
             "status_change": {"from": "planning", "to": "executing"}},
        ],
    }

    out = tool_get_matter({"matter_id": "a"}, client)

    event = out["timeline"][1]
    assert event["type"] == "owner_change"
    assert event["file"] is None
    assert event["actor"] == "u"
    assert event["to_owner"] == "v"
    assert event["reason"] == "handoff"


def test_read_files_returns_selected_bodies():
    client = MagicMock(spec=MatterApiClient)
    client.get_matter.return_value = {
        "matter": {"id": "a", "title": "T", "current_status": "x", "updated_at": ""},
        "timeline": [
            {"file": "001.md", "type": "think", "summary": "s1",
             "body": "正文1", "created_at": "", "creator": "u", "owner": "u"},
            {"file": "002.md", "type": "act", "summary": "s2",
             "body": "正文2", "created_at": "", "creator": "u", "owner": "u"},
        ],
    }
    out = tool_read_files({"matter_id": "a", "paths": ["002.md"]}, client)
    assert len(out["files"]) == 1
    assert out["files"][0]["body"] == "正文2"
    assert out["files"][0]["truncated"] is False


def test_read_files_rejects_unknown_path():
    client = MagicMock(spec=MatterApiClient)
    client.get_matter.return_value = {
        "matter": {"id": "a"}, "timeline": [],
    }
    with pytest.raises(ToolError) as ei:
        tool_read_files({"matter_id": "a", "paths": ["xxx.md"]}, client)
    assert ei.value.status == 404


def test_read_files_truncates_long_body():
    client = MagicMock(spec=MatterApiClient)
    client.get_matter.return_value = {
        "matter": {"id": "a"},
        "timeline": [
            {"file": "001.md", "type": "think", "summary": "",
             "body": "x" * 30000, "created_at": "", "creator": "u", "owner": "u"},
        ],
    }
    out = tool_read_files({"matter_id": "a", "paths": ["001.md"]}, client)
    assert out["files"][0]["truncated"] is True
    assert len(out["files"][0]["body"]) == 20000


def test_read_files_rejects_too_many_files():
    client = MagicMock(spec=MatterApiClient)
    with pytest.raises(ToolError) as ei:
        tool_read_files(
            {"matter_id": "a", "paths": [f"{i}.md" for i in range(10)]},
            client,
        )
    assert ei.value.status == 400
    assert "too_many_files" in ei.value.detail


def test_read_files_rejects_body_too_large():
    client = MagicMock(spec=MatterApiClient)
    # 5 files each 15K chars = 75K total > 50K cap
    timeline = [
        {"file": f"{i}.md", "type": "think", "summary": "",
         "body": "x" * 15000, "created_at": "", "creator": "u", "owner": "u"}
        for i in range(5)
    ]
    client.get_matter.return_value = {"matter": {"id": "a"}, "timeline": timeline}
    with pytest.raises(ToolError) as ei:
        tool_read_files(
            {"matter_id": "a", "paths": [f"{i}.md" for i in range(5)]},
            client,
        )
    assert ei.value.status == 400
    assert "body_too_large" in ei.value.detail


from server.mcp.tools import tool_create_file


def test_create_file_success_returns_summary():
    client = MagicMock(spec=MatterApiClient)
    client.post_file.return_value = {
        "item": {"file": "007_x_verify_abc.md", "type": "verify"},
        "matter": {
            "id": "a", "title": "Auth", "file_count": 7,
            "current_status": "executing",
        },
    }
    out = tool_create_file(
        {
            "matter_id": "a",
            "type": "verify",
            "summary": "验证 003/004",
            "body": "# Verify",
            "verifications": [
                {"target": "003.md", "judgement": "passed", "comment": "ok"},
            ],
        },
        client,
        "https://pivot.enclaws.ai",
    )
    assert out["ok"] is True
    assert out["file_path"].endswith(".md")
    assert "Auth" in out["summary_for_ai"]
    assert out["view_url"].startswith("https://pivot.enclaws.ai/m/a/f/")


def test_create_file_validation_errors_returned_as_data():
    client = MagicMock(spec=MatterApiClient)
    client.post_file.return_value = {
        "__validation_errors__": {"detail": {"code": "invalid_quote"}},
    }
    out = tool_create_file(
        {
            "matter_id": "a", "type": "verify", "summary": "x",
            "verifications": [
                {"target": "x", "judgement": "passed", "comment": "y"},
            ],
        },
        client,
        "https://pivot.enclaws.ai",
    )
    assert "errors" in out
    assert "ok" not in out


def test_create_file_404_raises():
    client = MagicMock(spec=MatterApiClient)
    client.post_file.side_effect = ToolError(404, "matter_not_found")
    with pytest.raises(ToolError):
        tool_create_file(
            {"matter_id": "missing", "type": "think", "summary": "x"},
            client,
            "https://pivot.enclaws.ai",
        )


def test_create_file_serializes_status_change_from_field():
    """StatusChangeIn uses 'from' as alias. Ensure we pass 'from' to API, not 'from_'."""
    client = MagicMock(spec=MatterApiClient)
    client.post_file.return_value = {
        "item": {"file": "x.md"},
        "matter": {"id": "a", "title": "A", "file_count": 1},
    }
    tool_create_file(
        {
            "matter_id": "a", "type": "result", "summary": "done",
            "outcome": "finished",
            "status_change": {"from": "executing", "to": "finished"},
        },
        client,
        "https://x",
    )
    sent_body = client.post_file.call_args[0][1]
    assert sent_body["status_change"] == {"from": "executing", "to": "finished"}
