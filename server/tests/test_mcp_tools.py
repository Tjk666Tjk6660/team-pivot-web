from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from server.mcp.tools import (
    MatterApiClient,
    ToolError,
    tool_list_matters,
    tool_resolve_context,
)
from server.mcp.schemas import (
    CategoryVisibilityIn,
    CreateMatterIn,
    VisibilityScopeIn,
)


def test_visibility_scope_in_defaults_public():
    v = VisibilityScopeIn()
    assert v.mode == "public"
    assert v.roles == []
    assert v.user_ids == []


def test_visibility_scope_in_restricted_roundtrip():
    v = VisibilityScopeIn(mode="restricted", roles=["dev"], user_ids=["u1"])
    assert v.model_dump() == {
        "mode": "restricted", "roles": ["dev"], "user_ids": ["u1"],
    }


def test_visibility_scope_in_rejects_unknown_mode():
    with pytest.raises(Exception):
        VisibilityScopeIn(mode="weird")


def test_category_visibility_in_defaults_public():
    c = CategoryVisibilityIn()
    assert c.mode == "public"
    assert c.authorized_roles == []


def test_category_visibility_in_restricted():
    c = CategoryVisibilityIn(mode="restricted", authorized_roles=["dev"])
    assert c.model_dump() == {
        "mode": "restricted", "authorized_roles": ["dev"],
    }


def test_create_matter_in_accepts_visibility_fields():
    payload = {
        "category": "Pivot", "title": "T", "type": "think",
        "summary": "s", "body": "b",
        "visibility": {"mode": "restricted", "roles": ["dev"], "user_ids": []},
        "new_category_visibility": {"mode": "public", "authorized_roles": []},
    }
    m = CreateMatterIn.model_validate(payload)
    assert m.visibility is not None
    assert m.visibility.mode == "restricted"
    assert m.visibility.roles == ["dev"]
    assert m.new_category_visibility is not None
    assert m.new_category_visibility.mode == "public"


def test_create_matter_in_visibility_default_is_none():
    m = CreateMatterIn.model_validate({
        "category": "Pivot", "title": "T", "type": "think",
        "summary": "s", "body": "b",
    })
    assert m.visibility is None
    assert m.new_category_visibility is None


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


def test_list_matters_surfaces_owner_and_summary():
    # Backend returns owner + last_summary; without these in the schema the AI
    # has to call get_matter per item just to judge relevance — N+1 fan-out.
    client = MagicMock(spec=MatterApiClient)
    client.list_matters.return_value = [
        {
            "id": "auth", "title": "Auth Redesign",
            "current_status": "executing",
            "updated_at": "2026-04-23T10:00:00+08:00", "file_count": 5,
            "owner": "zhouhang", "last_summary": "梳理重定向死循环",
        },
    ]
    out = tool_list_matters({}, client)
    assert out["items"][0]["owner"] == "zhouhang"
    assert out["items"][0]["summary"] == "梳理重定向死循环"


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


def test_get_matter_preserves_comments():
    # Backend renders comments[] with author_display / mentions_display per
    # item; the MCP schema must declare it or pydantic silently drops them
    # (extra='ignore' default), and the AI loses every conversational reply.
    client = MagicMock(spec=MatterApiClient)
    client.get_matter.return_value = {
        "matter": {"id": "a", "title": "T", "current_status": "x", "updated_at": ""},
        "timeline": [
            {
                "file": "001.md", "type": "think", "summary": "s1",
                "created_at": "", "creator": "u", "owner": "u",
                "comments": [
                    {
                        "author": "v", "author_display": "Victor",
                        "body": "解析已加",
                        "mentions": ["u"], "mentions_display": ["User"],
                        "created_at": "2026-04-23T10:00:00+08:00",
                    },
                ],
            },
        ],
    }
    out = tool_get_matter({"matter_id": "a"}, client)
    comments = out["timeline"][0]["comments"]
    assert len(comments) == 1
    assert comments[0]["author_display"] == "Victor"
    assert comments[0]["body"] == "解析已加"
    assert comments[0]["mentions_display"] == ["User"]


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


from server.mcp.tools import tool_create_matter


def test_create_matter_success_returns_summary_and_view_url():
    client = MagicMock(spec=MatterApiClient)
    client.post_matter.return_value = {
        "matter_id": "new-feature",
        "matter": {"id": "new-feature", "title": "New Feature",
                   "current_status": "planning"},
        "initial_timeline_item": {"file": "discussions/Pivot/new-feature/001_x_think_y.md",
                                  "type": "think"},
        "file": "discussions/Pivot/new-feature/001_x_think_y.md",
    }
    out = tool_create_matter(
        {
            "category": "Pivot",
            "title": "New Feature",
            "type": "think",
            "summary": "新需求",
            "body": "# New Feature\n\n正文",
        },
        client,
        "https://pivot.enclaws.ai",
    )
    assert out["ok"] is True
    assert out["matter_id"] == "new-feature"
    assert out["category"] == "Pivot"
    assert out["title"] == "New Feature"
    assert out["view_url"] == "https://pivot.enclaws.ai/m/new-feature"
    assert out["first_file"].endswith(".md")
    assert "New Feature" in out["summary_for_ai"]
    assert "Pivot" in out["summary_for_ai"]


def test_create_matter_flat_input_becomes_nested_api_body():
    """MCP exposes flat schema; backend wants {category, title, initial_file{...}}."""
    client = MagicMock(spec=MatterApiClient)
    client.post_matter.return_value = {
        "matter_id": "x", "matter": {"id": "x", "title": "X"},
        "file": "discussions/Pivot/x/001_a_think_b.md",
        "initial_timeline_item": {"file": "discussions/Pivot/x/001_a_think_b.md"},
    }
    tool_create_matter(
        {
            "category": "Pivot",
            "title": "X",
            "type": "think",
            "summary": "s",
            "body": "b",
            "owner": "alice",
        },
        client,
        "https://pivot",
    )
    sent_body = client.post_matter.call_args[0][0]
    assert sent_body["category"] == "Pivot"
    assert sent_body["title"] == "X"
    assert sent_body["initial_file"] == {
        "type": "think", "summary": "s", "body": "b", "owner": "alice",
    }


def test_create_matter_omits_owner_when_null():
    client = MagicMock(spec=MatterApiClient)
    client.post_matter.return_value = {
        "matter_id": "x", "matter": {"id": "x", "title": "X"},
        "file": "f.md", "initial_timeline_item": {"file": "f.md"},
    }
    tool_create_matter(
        {"category": "Pivot", "title": "X", "type": "think",
         "summary": "s", "body": "b"},
        client,
        "https://pivot",
    )
    sent_body = client.post_matter.call_args[0][0]
    assert "owner" not in sent_body["initial_file"]


def test_create_matter_validation_errors_returned_as_data():
    client = MagicMock(spec=MatterApiClient)
    client.post_matter.return_value = {
        "__validation_errors__": {"detail": {"code": "title_required"}},
    }
    out = tool_create_matter(
        {"category": "Pivot", "title": "", "type": "think",
         "summary": "s", "body": "b"},
        client,
        "https://pivot",
    )
    assert "errors" in out
    assert "ok" not in out


def test_create_matter_401_raises():
    client = MagicMock(spec=MatterApiClient)
    client.post_matter.side_effect = ToolError(401, "invalid_token")
    with pytest.raises(ToolError) as ei:
        tool_create_matter(
            {"category": "Pivot", "title": "X", "type": "think",
             "summary": "s", "body": "b"},
            client,
            "https://pivot",
        )
    assert ei.value.status == 401


def test_create_matter_403_raises():
    client = MagicMock(spec=MatterApiClient)
    client.post_matter.side_effect = ToolError(403, "forbidden")
    with pytest.raises(ToolError) as ei:
        tool_create_matter(
            {"category": "Pivot", "title": "X", "type": "think",
             "summary": "s", "body": "b"},
            client,
            "https://pivot",
        )
    assert ei.value.status == 403


# ---------- mentions ----------

def _ok_matter_response() -> dict:
    return {
        "matter_id": "x", "matter": {"id": "x", "title": "X"},
        "file": "discussions/Pivot/x/001_a_think_b.md",
        "initial_timeline_item": {"file": "discussions/Pivot/x/001_a_think_b.md"},
    }


def test_create_matter_mentions_translate_to_initial_file_comment():
    """Flat MCP `mentions` block becomes nested `initial_file.comments` for backend."""
    client = MagicMock(spec=MatterApiClient)
    client.post_matter.return_value = _ok_matter_response()
    tool_create_matter(
        {
            "category": "Pivot", "title": "X", "type": "think",
            "summary": "s", "body": "b",
            "mentions": {
                "targets": ["dengke", "yzy"],
                "say": "请帮我 review 这个方案",
            },
        },
        client,
        "https://pivot",
    )
    sent_body = client.post_matter.call_args[0][0]
    assert sent_body["initial_file"]["comments"] == [{
        "body": "请帮我 review 这个方案",
        "mentions": ["dengke", "yzy"],
    }]


def test_create_matter_no_mentions_means_no_comments_field():
    """Avoid sending an empty/null comments field that the backend might reject."""
    client = MagicMock(spec=MatterApiClient)
    client.post_matter.return_value = _ok_matter_response()
    tool_create_matter(
        {"category": "Pivot", "title": "X", "type": "think",
         "summary": "s", "body": "b"},
        client,
        "https://pivot",
    )
    sent_body = client.post_matter.call_args[0][0]
    assert "comments" not in sent_body["initial_file"]


def test_create_matter_mentions_empty_targets_rejected():
    """Pydantic guards against `targets: []` so AI can't ship an empty mention."""
    client = MagicMock(spec=MatterApiClient)
    with pytest.raises(Exception):  # pydantic ValidationError
        tool_create_matter(
            {
                "category": "Pivot", "title": "X", "type": "think",
                "summary": "s", "body": "b",
                "mentions": {"targets": [], "say": "hi"},
            },
            client,
            "https://pivot",
        )


def test_create_matter_mentions_empty_say_rejected():
    """When targets are present, `say` is required (non-empty)."""
    client = MagicMock(spec=MatterApiClient)
    with pytest.raises(Exception):  # pydantic ValidationError
        tool_create_matter(
            {
                "category": "Pivot", "title": "X", "type": "think",
                "summary": "s", "body": "b",
                "mentions": {"targets": ["dengke"], "say": ""},
            },
            client,
            "https://pivot",
        )


def test_create_matter_visibility_passthrough():
    """Restricted visibility object lands in the api body verbatim."""
    client = MagicMock(spec=MatterApiClient)
    client.post_matter.return_value = {
        "matter": {"id": "m1", "title": "T"},
        "matter_id": "m1",
        "initial_timeline_item": {"file": "001.md"},
        "file": "001.md",
    }
    out = tool_create_matter(
        {
            "category": "Pivot", "title": "T", "type": "think",
            "summary": "s", "body": "b",
            "visibility": {
                "mode": "restricted", "roles": ["dev"], "user_ids": ["u1"],
            },
        },
        client,
        "https://pivot.enclaws.ai",
    )
    sent_body = client.post_matter.call_args[0][0]
    assert sent_body["visibility"] == {
        "mode": "restricted", "roles": ["dev"], "user_ids": ["u1"],
    }
    assert "new_category_visibility" not in sent_body
    assert out["ok"] is True


def test_create_matter_new_category_visibility_passthrough():
    """Both visibility and new_category_visibility ride along when both set."""
    client = MagicMock(spec=MatterApiClient)
    client.post_matter.return_value = {
        "matter": {"id": "m1", "title": "T"},
        "matter_id": "m1",
        "initial_timeline_item": {"file": "001.md"},
        "file": "001.md",
    }
    tool_create_matter(
        {
            "category": "NewCat", "title": "T", "type": "think",
            "summary": "s", "body": "b",
            "visibility": {
                "mode": "restricted", "roles": ["dev"], "user_ids": [],
            },
            "new_category_visibility": {
                "mode": "restricted", "authorized_roles": ["dev"],
            },
        },
        client,
        "https://pivot.enclaws.ai",
    )
    sent_body = client.post_matter.call_args[0][0]
    assert sent_body["visibility"] == {
        "mode": "restricted", "roles": ["dev"], "user_ids": [],
    }
    assert sent_body["new_category_visibility"] == {
        "mode": "restricted", "authorized_roles": ["dev"],
    }


def test_create_matter_omits_visibility_keys_when_unset():
    """No visibility key is sent when caller doesn't set it — backend defaults to public."""
    client = MagicMock(spec=MatterApiClient)
    client.post_matter.return_value = {
        "matter": {"id": "m1", "title": "T"},
        "matter_id": "m1",
        "initial_timeline_item": {"file": "001.md"},
        "file": "001.md",
    }
    tool_create_matter(
        {
            "category": "Pivot", "title": "T", "type": "think",
            "summary": "s", "body": "b",
        },
        client,
        "https://pivot.enclaws.ai",
    )
    sent_body = client.post_matter.call_args[0][0]
    assert "visibility" not in sent_body
    assert "new_category_visibility" not in sent_body


def test_create_matter_surfaces_missing_category_visibility_422():
    """Backend's missing_category_visibility flows through as `errors` payload."""
    client = MagicMock(spec=MatterApiClient)
    client.post_matter.return_value = {
        "__validation_errors__": {
            "detail": {"code": "missing_category_visibility"},
        },
    }
    out = tool_create_matter(
        {
            "category": "NewCat", "title": "T", "type": "think",
            "summary": "s", "body": "b",
            "visibility": {
                "mode": "restricted", "roles": ["dev"], "user_ids": [],
            },
        },
        client,
        "https://pivot.enclaws.ai",
    )
    assert "errors" in out
    assert out["errors"]["detail"]["code"] == "missing_category_visibility"


def test_create_file_mentions_translate_to_top_level_comments():
    """For create_file the comments list is at the request body root, not nested."""
    client = MagicMock(spec=MatterApiClient)
    client.post_file.return_value = {
        "item": {"file": "discussions/Pivot/x/002_a_think_c.md"},
        "matter": {"title": "X", "file_count": 2},
    }
    tool_create_file(
        {
            "matter_id": "x", "type": "think", "summary": "s",
            "mentions": {
                "targets": ["dengke"],
                "say": "想听听你的意见",
            },
        },
        client,
        "https://pivot",
    )
    sent_body = client.post_file.call_args[0][1]
    assert sent_body["comments"] == [{
        "body": "想听听你的意见",
        "mentions": ["dengke"],
    }]


# ---------- add_comment ----------

from server.mcp.tools import tool_add_comment


def _ok_comment_response() -> dict:
    return {
        "matter_id": "x",
        "target_file": "discussions/Pivot/x/001_a_think_b.md",
        "at": "2026-04-28T10:00:00Z",
    }


def test_add_comment_with_mention_passes_through_to_api():
    """`mentions` in input becomes `mentions` in api_body, and body is the comment."""
    client = MagicMock(spec=MatterApiClient)
    client.post_comment.return_value = _ok_comment_response()
    tool_add_comment(
        {
            "matter_id": "x",
            "target_file": "discussions/Pivot/x/001_a_think_b.md",
            "body": "请帮我 review 这条",
            "mentions": ["dengke", "yzy"],
        },
        client,
        "https://pivot",
    )
    sent_matter_id = client.post_comment.call_args[0][0]
    sent_body = client.post_comment.call_args[0][1]
    assert sent_matter_id == "x"
    assert sent_body == {
        "target_file": "discussions/Pivot/x/001_a_think_b.md",
        "body": "请帮我 review 这条",
        "mentions": ["dengke", "yzy"],
    }


def test_add_comment_without_mentions_omits_field():
    """A plain note must not ship a `mentions` key (avoids backend confusion)."""
    client = MagicMock(spec=MatterApiClient)
    client.post_comment.return_value = _ok_comment_response()
    tool_add_comment(
        {
            "matter_id": "x",
            "target_file": "discussions/Pivot/x/001_a_think_b.md",
            "body": "记一笔",
        },
        client,
        "https://pivot",
    )
    sent_body = client.post_comment.call_args[0][1]
    assert "mentions" not in sent_body


def test_add_comment_success_returns_view_url_and_summary():
    """Output exposes a view_url for the file and a relay-able Chinese summary."""
    client = MagicMock(spec=MatterApiClient)
    client.post_comment.return_value = _ok_comment_response()
    out = tool_add_comment(
        {
            "matter_id": "x",
            "target_file": "discussions/Pivot/x/001_a_think_b.md",
            "body": "请 review",
            "mentions": ["dengke"],
        },
        client,
        "https://pivot.enclaws.ai",
    )
    assert out["ok"] is True
    assert out["matter_id"] == "x"
    assert out["target_file"] == "discussions/Pivot/x/001_a_think_b.md"
    assert out["view_url"] == (
        "https://pivot.enclaws.ai/m/x/f/"
        "discussions/Pivot/x/001_a_think_b.md"
    )
    # With mentions, the summary mentions "@ 提及"; without it, just "评论".
    assert "@ 提及" in out["summary_for_ai"]
    assert out["view_url"] in out["summary_for_ai"]


def test_add_comment_validation_errors_returned_as_data():
    """422 surfaces as `{errors: ...}` so AI can iterate, not raise ToolError."""
    client = MagicMock(spec=MatterApiClient)
    client.post_comment.return_value = {
        "__validation_errors__": {"detail": {"code": "body_required"}},
    }
    out = tool_add_comment(
        {
            "matter_id": "x",
            "target_file": "discussions/Pivot/x/001_a_think_b.md",
            "body": "x",
        },
        client,
        "https://pivot",
    )
    assert "errors" in out
    assert "ok" not in out


def test_add_comment_404_raises_with_specific_code():
    """The matter / target-file 404 distinction is preserved for the AI."""
    client = MagicMock(spec=MatterApiClient)
    client.post_comment.side_effect = ToolError(404, "comment_target_not_found")
    with pytest.raises(ToolError) as ei:
        tool_add_comment(
            {
                "matter_id": "x",
                "target_file": "missing.md",
                "body": "hi",
            },
            client,
            "https://pivot",
        )
    assert ei.value.status == 404
    assert ei.value.detail == "comment_target_not_found"
