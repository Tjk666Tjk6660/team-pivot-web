from __future__ import annotations

from pathlib import Path

from server.ai.tools import AITools


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _setup_workspace(tmp_path: Path) -> tuple[Path, Path]:
    """Build a tiny workspace with two threads and their indexes."""
    discussions = tmp_path / "discussions"
    index = tmp_path / "index"

    _write(
        discussions / "Pivot" / "auth-redesign" / "001_dengke_proposal_aaa.md",
        "---\ntype: proposal\nauthor: dengke\n---\n# 登录改造\n背景：重写登录。\n",
    )
    _write(
        discussions / "Pivot" / "auth-redesign" / "002_liuyu_reply_bbb.md",
        "---\ntype: reply\nauthor: liuyu\n---\n回复内容。\n",
    )
    _write(
        discussions / "Pivot" / "ui-refresh" / "001_yue_proposal_ccc.md",
        "---\ntype: proposal\nauthor: yue\n---\nUI 焕新提议。\n",
    )

    _write(
        index / "auth-redesign-discuss.index.yaml",
        "origin_path: discussions/Pivot/auth-redesign/\n"
        "discussions:\n"
        "- path: discussions/Pivot/auth-redesign/\n"
        "  status: open\n"
        "  files:\n"
        "  - path: 001_dengke_proposal_aaa.md\n"
        "    refs: []\n"
        "  - path: 002_liuyu_reply_bbb.md\n"
        "    refs:\n"
        "    - type: from\n"
        "      path: discussions/Pivot/auth-redesign/001_dengke_proposal_aaa.md\n"
        "timeline: []\n",
    )
    _write(
        index / "ui-refresh-discuss.index.yaml",
        "origin_path: discussions/Pivot/ui-refresh/\n"
        "discussions:\n"
        "- path: discussions/Pivot/ui-refresh/\n"
        "  status: open\n"
        "  files:\n"
        "  - path: 001_yue_proposal_ccc.md\n"
        "    refs: []\n"
        "timeline: []\n",
    )
    return discussions, index


def test_list_thread_titles_lists_every_index(tmp_path):
    discussions, index = _setup_workspace(tmp_path)
    tools = AITools(discussions, index)

    result = tools.dispatch("list_thread_titles", {})

    assert "auth-redesign" in result
    assert "ui-refresh" in result


def test_search_indexes_finds_matching_thread(tmp_path):
    discussions, index = _setup_workspace(tmp_path)
    tools = AITools(discussions, index)

    result = tools.dispatch("search_indexes", {"keyword": "liuyu"})

    assert "auth-redesign" in result
    assert "ui-refresh" not in result


def test_search_indexes_empty_keyword_errors(tmp_path):
    discussions, index = _setup_workspace(tmp_path)
    tools = AITools(discussions, index)

    result = tools.dispatch("search_indexes", {"keyword": ""})

    assert result.startswith("[tool error]")


def test_read_thread_index_returns_yaml(tmp_path):
    discussions, index = _setup_workspace(tmp_path)
    tools = AITools(discussions, index)

    result = tools.dispatch("read_thread_index", {"thread_slug": "auth-redesign"})

    assert "002_liuyu_reply_bbb.md" in result
    assert "discussions:" in result


def test_read_thread_index_unknown_slug_errors(tmp_path):
    discussions, index = _setup_workspace(tmp_path)
    tools = AITools(discussions, index)

    result = tools.dispatch("read_thread_index", {"thread_slug": "nonexistent"})

    assert result.startswith("[tool error]")


def test_read_post_happy_path_returns_body(tmp_path):
    discussions, index = _setup_workspace(tmp_path)
    tools = AITools(discussions, index)

    result = tools.dispatch(
        "read_post",
        {"path": "discussions/Pivot/auth-redesign/001_dengke_proposal_aaa.md"},
    )

    assert "登录改造" in result
    assert "背景" in result


def test_read_post_accepts_path_without_discussions_prefix(tmp_path):
    discussions, index = _setup_workspace(tmp_path)
    tools = AITools(discussions, index)

    result = tools.dispatch(
        "read_post", {"path": "Pivot/auth-redesign/001_dengke_proposal_aaa.md"}
    )

    assert "登录改造" in result


def test_read_post_rejects_path_not_in_any_index(tmp_path):
    discussions, index = _setup_workspace(tmp_path)
    # Create a stray file that does NOT have a matching index entry.
    # It still lives under discussions_dir so filesystem-discovery would
    # normally accept it; we ensure index-absence doesn't matter because
    # filesystem discovery also allow-lists it. This test verifies the
    # "not even on disk" case.
    tools = AITools(discussions, index)

    result = tools.dispatch(
        "read_post", {"path": "discussions/Pivot/ghost/999_nope.md"}
    )

    assert result.startswith("[tool error]")


def test_read_post_rejects_traversal(tmp_path):
    discussions, index = _setup_workspace(tmp_path)
    secret = tmp_path / "secret.md"
    secret.write_text("secret contents", encoding="utf-8")

    tools = AITools(discussions, index)
    result = tools.dispatch(
        "read_post", {"path": "Pivot/auth-redesign/../../../secret.md"}
    )

    assert result.startswith("[tool error]")
    assert "secret contents" not in result


def test_read_post_rejects_bad_shape(tmp_path):
    discussions, index = _setup_workspace(tmp_path)
    tools = AITools(discussions, index)

    assert tools.dispatch("read_post", {"path": ""}).startswith("[tool error]")
    assert tools.dispatch("read_post", {"path": "only-one-segment"}).startswith(
        "[tool error]"
    )
    assert tools.dispatch(
        "read_post", {"path": "Pivot/auth-redesign/not-a-markdown.txt"}
    ).startswith("[tool error]")


def test_unknown_tool_name_errors(tmp_path):
    discussions, index = _setup_workspace(tmp_path)
    tools = AITools(discussions, index)

    result = tools.dispatch("nope", {})

    assert result.startswith("[tool error]")


def test_specs_include_all_four_tools(tmp_path):
    discussions, index = _setup_workspace(tmp_path)
    tools = AITools(discussions, index)

    names = {spec["function"]["name"] for spec in tools.specs()}

    assert names == {
        "list_thread_titles",
        "search_indexes",
        "read_thread_index",
        "read_post",
    }
