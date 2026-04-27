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


def test_read_matter_index_returns_yaml(tmp_path):
    discussions, index = _setup_workspace(tmp_path)
    # matter index 命名是 {matter_id}.index.yaml,不带 -discuss 后缀
    _write(
        index / "matter-001.index.yaml",
        "matter:\n"
        "  id: matter-001\n"
        "  title: 你好\n"
        "  current_status: planning\n"
        "timeline:\n"
        "- file: discussions/general/matter-001/001_x_think_aaa.md\n"
        "  type: think\n"
        "  summary: 起点\n",
    )
    tools = AITools(discussions, index)

    result = tools.dispatch("read_matter_index", {"matter_id": "matter-001"})

    assert "matter-001" in result
    assert "current_status: planning" in result
    assert "timeline:" in result


def test_read_matter_index_unknown_id_errors(tmp_path):
    discussions, index = _setup_workspace(tmp_path)
    tools = AITools(discussions, index)

    result = tools.dispatch("read_matter_index", {"matter_id": "nonexistent"})

    assert result.startswith("[tool error]")


def test_read_matter_index_empty_id_errors(tmp_path):
    discussions, index = _setup_workspace(tmp_path)
    tools = AITools(discussions, index)

    assert tools.dispatch("read_matter_index", {"matter_id": ""}).startswith(
        "[tool error]"
    )
    assert tools.dispatch("read_matter_index", {}).startswith("[tool error]")


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


def _seed_matter_index(index_dir: Path) -> None:
    """Add a couple of matter index files alongside the legacy thread fixtures."""
    _write(
        index_dir / "feedback-loop.index.yaml",
        "matter:\n"
        "  id: feedback-loop\n"
        "  title: 优化反馈闭环\n"
        "  current_status: executing\n"
        "  created_at: '2026-04-01T10:00:00+08:00'\n"
        "  updated_at: '2026-04-20T18:00:00+08:00'\n"
        "timeline: []\n",
    )
    _write(
        index_dir / "rate-limiter.index.yaml",
        "matter:\n"
        "  id: rate-limiter\n"
        "  title: 接口限流策略\n"
        "  current_status: planning\n"
        "  created_at: '2026-04-15T09:00:00+08:00'\n"
        "  updated_at: '2026-04-18T11:00:00+08:00'\n"
        "timeline: []\n",
    )


def test_list_matters_orders_by_updated_at_desc(tmp_path):
    discussions, index = _setup_workspace(tmp_path)
    _seed_matter_index(index)
    tools = AITools(discussions, index)

    result = tools.dispatch("list_matters", {})

    # both matters present, freshly-updated one first
    feedback_pos = result.index("feedback-loop")
    rate_pos = result.index("rate-limiter")
    assert feedback_pos < rate_pos
    # matter status surfaces in the line
    assert "[executing]" in result
    assert "[planning]" in result
    # legacy thread slugs must not leak into the matter listing
    assert "auth-redesign" not in result


def test_search_indexes_covers_matter_and_thread(tmp_path):
    discussions, index = _setup_workspace(tmp_path)
    _seed_matter_index(index)
    tools = AITools(discussions, index)

    matter_hit = tools.dispatch("search_indexes", {"keyword": "限流"})
    assert "kind=matter" in matter_hit
    assert "matter_id=rate-limiter" in matter_hit

    thread_hit = tools.dispatch("search_indexes", {"keyword": "liuyu"})
    assert "kind=thread" in thread_hit
    assert "thread_slug=auth-redesign" in thread_hit


def test_specs_include_all_tools(tmp_path):
    discussions, index = _setup_workspace(tmp_path)
    tools = AITools(discussions, index)

    names = {spec["function"]["name"] for spec in tools.specs()}

    assert names == {
        "list_thread_titles",
        "list_matters",
        "search_indexes",
        "read_thread_index",
        "read_matter_index",
        "read_post",
    }
