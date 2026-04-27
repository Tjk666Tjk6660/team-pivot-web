import pytest

from server.mcp.context import (
    ContextUrlError,
    build_user_facing_summary,
    build_view_url,
    parse_context_url,
)


def test_parse_matter_only():
    m, f = parse_context_url("https://pivot.enclaws.ai/m/auth-redesign")
    assert m == "auth-redesign"
    assert f is None


def test_parse_matter_and_file():
    m, f = parse_context_url(
        "https://pivot.enclaws.ai/m/auth-redesign/f/005_dengke_think_xxx.md"
    )
    assert m == "auth-redesign"
    assert f == "005_dengke_think_xxx.md"


def test_parse_nested_file_path():
    m, f = parse_context_url(
        "https://pivot.enclaws.ai/m/foo/f/subdir/bar.md"
    )
    assert m == "foo"
    assert f == "subdir/bar.md"


def test_parse_urlencoded_chinese():
    m, f = parse_context_url(
        "https://pivot.enclaws.ai/m/%E4%BA%A7%E5%93%81/f/005.md"
    )
    assert m == "产品"
    assert f == "005.md"


def test_parse_rejects_wrong_path():
    with pytest.raises(ContextUrlError):
        parse_context_url("https://pivot.enclaws.ai/t/thread/foo")


def test_parse_rejects_non_http():
    with pytest.raises(ContextUrlError):
        parse_context_url("ftp://pivot.enclaws.ai/m/foo")


def test_summary_matter_only():
    s = build_user_facing_summary(
        {"title": "Auth Redesign", "current_status": "executing"},
        None, [],
    )
    assert "Auth Redesign" in s
    assert "executing" in s


def test_summary_with_file():
    s = build_user_facing_summary(
        {"title": "Auth", "current_status": "executing"},
        "005.md",
        [{"file": "005.md", "type": "think", "summary": "梳理问题"}],
    )
    assert "think" in s
    assert "梳理问题" in s


def test_view_url():
    assert (
        build_view_url("https://pivot.enclaws.ai", "auth", "005.md")
        == "https://pivot.enclaws.ai/m/auth/f/005.md"
    )
