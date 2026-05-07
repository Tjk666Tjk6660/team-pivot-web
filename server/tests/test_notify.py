from __future__ import annotations

import json
from pathlib import Path

from server.notify import (
    FeishuNotifier,
    NoOpNotifier,
    build_annotation_dm_card,
    build_application_card,
    build_matter_event_card,
    build_mention_dm_card,
    build_owner_change_card,
    build_reply_card,
    build_standalone_mention_card,
    build_status_change_card,
    build_thread_card,
    build_thread_directory,
)


# ─── 6 字段卡片 ─────────────────────────────────────────────────────────────


def test_thread_card_shape_6_fields():
    card = build_thread_card(
        category="general",
        thread_slug="hello",
        title="Hello",
        author_name="邓柯",
        filename="001_deng_proposal_xxx.md",
        thread_url="http://localhost:5173/auth/entry?next=%2Ft%2Fgeneral%2Fhello",
    )
    assert card["schema"] == "2.0"
    assert card["header"]["template"] == "blue"
    assert card["header"]["title"]["content"] == "📨 来自 邓柯 的新讨论主题通知：Hello"

    md = card["body"]["elements"][0]["content"]
    # 6 字段都在
    assert "**项目**：general" in md
    assert "**主题**：Hello" in md
    assert "**操作**：邓柯 发起了新讨论" in md
    assert "**文件**：001_deng_proposal_xxx.md" in md
    assert "**时间**：" in md
    # 不再有摘要行
    assert "**摘要**" not in md
    # 行间用 <br>
    assert "<br>" in md

    button = card["body"]["elements"][-1]
    assert button["tag"] == "button"


def test_reply_card_header_carries_author():
    card = build_reply_card(
        category="general",
        thread_slug="parent",
        thread_title="Parent",
        author_name="Ken",
        filename="002_ken_reply_xxx.md",
        thread_url="http://x/y",
    )
    assert card["header"]["template"] == "green"
    assert card["header"]["title"]["content"] == "📩 来自 Ken 的新回复通知：Parent"

    md = card["body"]["elements"][0]["content"]
    assert "**主题**：Parent" in md
    assert "**操作**：Ken 发布了新回复" in md
    assert "**文件**：002_ken_reply_xxx.md" in md


def test_thread_card_uses_schema2_at_tag_for_mentions():
    """Regression: 6-field thread/reply card must use schema 2.0 `<at id=...>`,
    not legacy `<at user_id=...>`. Feishu silently ignores user_id, so the
    @-tag never lights up red dots / pushes — i.e. 圈人 → 收不到通知。
    """
    card = build_thread_card(
        category="c",
        thread_slug="s",
        title="T",
        author_name="a",
        filename="f.md",
        thread_url="http://x",
        mention_open_ids=["ou_alice00000000000", "ou_bob000000000000000"],
    )
    md = card["body"]["elements"][0]["content"]
    assert "**圈人**：" in md
    assert '<at id="ou_alice00000000000"></at>' in md
    assert '<at id="ou_bob000000000000000"></at>' in md
    assert "user_id=" not in md, (
        "schema 1.0 `user_id` attribute leaked back in — Feishu will "
        "silently drop the @-tag and the mention notification will fail."
    )


def test_reply_card_uses_schema2_at_tag_for_mentions():
    card = build_reply_card(
        category="c",
        thread_slug="s",
        thread_title="T",
        author_name="a",
        filename="002_a_reply.md",
        thread_url="http://x",
        mention_open_ids=["ou_carol0000000000000"],
    )
    md = card["body"]["elements"][0]["content"]
    assert "**圈人**：" in md
    assert '<at id="ou_carol0000000000000"></at>' in md
    assert "user_id=" not in md


def test_new_thread_card_renders_owner_as_labeled_at():
    card = build_thread_card(
        category="abc",
        thread_slug="s",
        title="T",
        author_name="李帅",
        filename="001_lishuai_think_x.md",
        thread_url="http://x",
        owner_open_id="ou_zhangsan00000000",
    )
    md = card["body"]["elements"][0]["content"]
    assert card["body"]["elements"][0]["tag"] == "markdown"
    assert "**负责人**：<at id=\"ou_zhangsan00000000\"></at>" in md
    assert md.index("**负责人**：") < md.index("<at id=\"ou_zhangsan00000000\"></at>")


def test_owner_change_card_mentions_new_owner():
    card = build_owner_change_card(
        thread_title="Pivot 优化",
        actor_name="李帅",
        from_owner_name="张三",
        to_owner_name="李四",
        to_owner_open_id="ou_lisi000000000000",
        reason="后续由李四推进",
        thread_url="http://x/m/pivot",
        status_change={"from": "planning", "to": "executing"},
    )
    body = json.dumps(card["body"], ensure_ascii=False)
    md = card["body"]["elements"][0]["content"]
    assert card["header"]["title"]["content"] == "负责人变更：Pivot 优化"
    assert card["body"]["elements"][0]["tag"] == "markdown"
    assert "ou_lisi000000000000" in body
    assert "**操作**：李帅 更改负责人" in md
    assert "**负责人**：张三 → <at id=\"ou_lisi000000000000\"></at>" in md
    assert "**原因**：后续由李四推进" in md
    assert "**状态**：计划中 → 执行中" in md


def test_card_no_author_row():
    """No **作者** row — author lives in header / 操作."""
    card = build_thread_card(
        category="c",
        thread_slug="s",
        title="T",
        author_name="a",
        filename="f.md",
        thread_url="http://x",
    )
    md = card["body"]["elements"][0]["content"]
    assert "**作者**：" not in md


def test_card_omits_body_preview_when_no_body():
    card = build_thread_card(
        category="c",
        thread_slug="s",
        title="T",
        author_name="a",
        filename="f.md",
        thread_url="http://x",
    )
    md = card["body"]["elements"][0]["content"]
    assert "**内容**" not in md


def test_thread_card_body_preview_strips_markdown():
    body = (
        "# Hello\n\n"
        "This is **bold** and *italic* text with `inline code`.\n\n"
        "- item one\n- item two\n\n"
        "See [link](http://x) and ![img](http://y)."
    )
    card = build_thread_card(
        category="c",
        thread_slug="s",
        title="T",
        author_name="a",
        filename="f.md",
        thread_url="http://x",
        body=body,
    )
    md = card["body"]["elements"][0]["content"]
    assert "**内容**：" in md
    # Extract the 内容 row
    preview_row = next(
        r for r in md.split("<br>") if r.startswith("**内容**：")
    )
    preview = preview_row[len("**内容**："):]
    # No raw markdown left
    for junk in ("**", "*", "`", "#", "[", "]", "(http", "!["):
        assert junk not in preview, f"found {junk!r} in {preview!r}"
    assert "bold" in preview
    assert "italic" in preview
    assert "link" in preview
    assert "img" in preview
    assert "inline code" in preview


def test_mention_comments_collapsed_to_single_line():
    """Multi-line mention_comments must not introduce paragraph breaks."""
    card = build_thread_card(
        category="c",
        thread_slug="s",
        title="T",
        author_name="a",
        filename="f.md",
        thread_url="http://x",
        mention_open_ids=["ou_abc"],
        mention_comments="请看\n\n\n   一下   \n重要事项",
    )
    md = card["body"]["elements"][0]["content"]
    assert "**说明**：请看 一下 重要事项" in md
    # No paragraph-break sequence inside the info block
    assert "\n\n" not in md


def test_mention_comments_rendered_below_time_row():
    """说明 must sit below 时间 (not at top) so the first row of the card
    is always a compact meta field, avoiding the Feishu first-paragraph
    top-margin gap when a 说明 is present."""
    card = build_thread_card(
        category="c",
        thread_slug="s",
        title="T",
        author_name="a",
        filename="f.md",
        thread_url="http://x",
        mention_comments="重要说明",
    )
    md = card["body"]["elements"][0]["content"]
    rows = md.split("<br>")
    time_idx = next(i for i, r in enumerate(rows) if r.startswith("**时间**"))
    说明_idx = next(i for i, r in enumerate(rows) if r.startswith("**说明**"))
    assert 说明_idx > time_idx


def test_card_body_has_tight_top_padding():
    card = build_thread_card(
        category="c",
        thread_slug="s",
        title="T",
        author_name="a",
        filename="f.md",
        thread_url="http://x",
    )
    assert card["body"]["padding"].startswith("4px ")


def test_reply_card_body_preview_truncates_at_200():
    body = "一" * 300
    card = build_reply_card(
        category="c",
        thread_slug="s",
        thread_title="T",
        author_name="a",
        filename="f.md",
        thread_url="http://x",
        body=body,
    )
    md = card["body"]["elements"][0]["content"]
    preview_row = next(
        r for r in md.split("<br>") if r.startswith("**内容**：")
    )
    preview = preview_row[len("**内容**："):]
    assert preview.endswith("...")
    # 200 chars + "..."
    assert len(preview) == 203


# ─── Mention 卡片 ───────────────────────────────────────────────────────────


def test_standalone_mention_card_structure():
    card = build_standalone_mention_card(
        category="enclaws",
        thread_slug="hello",
        thread_title="EnClaws 内容营销推广方案",
        author_name="邓柯",
        target_filename="003_daisy_reply_bac194.md",
        mention_open_ids=["ou_aaa", "ou_bbb", "ou_ccc"],
        mention_comments="我觉得Daisy文档里面提的问题都挺不错，欢迎大家一起来发表意见。头脑风暴",
        post_url="http://x/deep-link",
    )
    md = card["body"]["elements"][0]["content"]

    # 1. 真 @ 语法：schema 2.0 用 id=，content 留空
    assert '<at id="ou_aaa"></at>' in md
    assert '<at id="ou_bbb"></at>' in md
    assert '<at id="ou_ccc"></at>' in md
    assert "user_id=" not in md  # 旧 schema 1.0 写法必须全部清除

    # 2. 提醒行：**提醒**：<橙色邓柯> @标签 说：<br> message
    assert "**提醒**：" in md
    assert "<font color='orange'>**邓柯**</font>" in md
    assert "说：" in md
    assert "我觉得Daisy文档里面提的问题都挺不错" in md

    # 3. 提醒行结构：发起人 → @ 标签 → 说：→ <br> → message
    i_author = md.index("<font color='orange'>**邓柯**</font>")
    i_ats = md.index('<at id="ou_aaa"></at>')
    i_say = md.index("说：")
    i_br = md.index("<br>")
    assert i_author < i_ats < i_say < i_br

    # 4. 不再出现被评人相关字段（target_author_name 已从签名移除）
    assert "<font color='blue'>" not in md
    assert "进行了回复" not in md
    assert "并提及" not in md

    # 5. 元信息块 4 个字段齐全且顺序正确：时间 → 项目 → 主题 → 涉及文件
    i_time = md.index("**时间**：")
    i_proj = md.index("**项目**：enclaws")
    i_topic = md.index("**主题**：EnClaws 内容营销推广方案")
    i_file = md.index("**涉及文件**：003_daisy_reply_bac194.md")
    assert i_time < i_proj < i_topic < i_file

    # 6. 已去掉的字段/短语
    assert "提及了以上成员" not in md
    assert "**说明**：" not in md   # 合并进提醒行
    assert "**帖子**：" not in md   # 改叫"涉及文件"
    assert "**相关内容**：" not in md  # post_excerpt 段已废弃
    assert "**评论**：" not in md   # 重命名为"提醒"
    assert "**被评文件**：" not in md  # 重命名为"涉及文件"

    # 7. 按钮保持 post 级深链
    button = card["body"]["elements"][-1]
    assert button["tag"] == "button"
    assert button["multi_url"]["url"] == "http://x/deep-link"
    assert button["text"]["content"] == "查看该帖子"

    # 8. header 和模板
    assert card["header"]["template"] == "orange"
    assert "📣 提及：EnClaws 内容营销推广方案" in card["header"]["title"]["content"]


def test_mention_dm_card_structure():
    card = build_mention_dm_card(
        author_name="Alice",
        thread_title="Hello",
        thread_slug="hello",
        target_filename="002_bob_reply_zzz.md",
        kind="提及",
        comments="帮忙看一下",
        post_url="http://x/deep-link",
        post_excerpt="这是 bob 的回复正文",
    )
    md = card["body"]["elements"][0]["content"]
    assert "Alice" in md
    assert "Hello" in md
    assert "提及" in md
    assert "**帖子**：002_bob_reply_zzz.md" in md
    assert "**说明**：帮忙看一下" in md
    assert "**相关内容**：" in md
    assert card["body"]["elements"][-1]["multi_url"]["url"] == "http://x/deep-link"


# ─── Post-level deep link URL ──────────────────────────────────────────────


def test_feishu_notifier_uses_auth_entry_thread_url():
    notifier = FeishuNotifier(tokens=None, web_base_url="https://pivot.enclaws.ai")  # type: ignore[arg-type]
    url = notifier._thread_url("产品", "讨论")
    assert (
        url
        == "https://pivot.enclaws.ai/auth/entry?next=%2Ft%2F%E4%BA%A7%E5%93%81%2F%E8%AE%A8%E8%AE%BA"
    )


def test_feishu_notifier_broadcast_card_delegates_to_broadcast(monkeypatch):
    """`broadcast_card` is the public hook for periodic-job callers (daily
    report etc). It must forward to `_broadcast` 1:1 without modifying the
    card or the event tag."""
    from server.notify import FeishuNotifier

    class _StubTokens:
        def get(self) -> str:
            return "token"

    captured: list[tuple[dict, str]] = []
    n = FeishuNotifier(
        tokens=_StubTokens(),
        web_base_url="http://localhost:5173",
        workspace=None,
    )
    monkeypatch.setattr(n, "_broadcast",
                        lambda card, *, event: captured.append((card, event)))

    card = {"schema": "2.0", "header": {"title": {"content": "test"}}}
    n.broadcast_card(card, event="daily_report 2026-04-26")
    assert captured == [(card, "daily_report 2026-04-26")]


def test_feishu_notifier_post_url_lands_on_matter_detail():
    """Post-migration: per-post deep-link URL lands on /m/<matter_id>.
    The old /t/<cat>/<slug>?post=<anchor> route is gone (frontend has no
    such route after the matter migration), so all notify cards (new
    thread, new reply, standalone mention, plus directory entries via
    build_thread_directory) land users on the matter detail page.

    Per-file scroll-to-anchor is a future enhancement requiring
    MatterDetailPane to consume a `?file=` param or hash."""
    notifier = FeishuNotifier(tokens=None, web_base_url="https://pivot.enclaws.ai")  # type: ignore[arg-type]
    url = notifier._post_url("general", "hello", "001_user_proposal_abc.md")
    # New: /m/<slug>, URL-encoded as /m/hello
    assert "%2Fm%2Fhello" in url
    # Old artifacts must be gone — no /t/, no ?post=, no #post-
    assert "%2Ft%2F" not in url
    assert "post%3D" not in url
    assert "%23post-" not in url


# ─── Discussion directory ──────────────────────────────────────────────────


def _write_post(path: Path, *, type_: str, author: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = (
        f"type: {type_}\n"
        f"author: {author}\n"
        "created: 2026-04-23T10:00:00+08:00\n"
        "index_state: indexed\n"
    )
    path.write_text(f"---\n{fm}---\n# body\n", encoding="utf-8")


class _WorkspaceStub:
    def __init__(self, discussions_dir: Path, index_dir: Path) -> None:
        self.discussions_dir = discussions_dir
        self.index_dir = index_dir


def test_build_thread_directory_highlights_current_post(tmp_path):
    discussions = tmp_path / "discussions"
    index_dir = tmp_path / "index"
    _write_post(
        discussions / "general" / "hello" / "001_alice_proposal_abc.md",
        type_="proposal", author="alice",
    )
    _write_post(
        discussions / "general" / "hello" / "002_bob_reply_def.md",
        type_="reply", author="bob",
    )

    content, count = build_thread_directory(
        _WorkspaceStub(discussions, index_dir),  # type: ignore[arg-type]
        category="general",
        slug="hello",
        current_filename="002_bob_reply_def.md",
    )
    assert count == 2
    assert "001_alice_proposal_abc.md" in content
    assert "002_bob_reply_def.md" in content
    # current post highlighted with blue font + 🔷
    assert "<font color='blue'>🔷" in content
    # non-current entry prefixed with 📄
    assert "📄 " in content
    # No per-post summary in v2 (summary deferred)
    assert "**摘要**" not in content


def test_thread_card_includes_directory_panel():
    card = build_thread_card(
        category="general",
        thread_slug="hello",
        title="Hello",
        author_name="Ken",
        filename="001_ken_proposal_xxx.md",
        thread_url="http://x/y",
        directory_content="📄 **001_ken_proposal_xxx.md** · Ken · 2026-04-23",
        directory_post_count=1,
    )
    tags = [e.get("tag") for e in card["body"]["elements"]]
    assert "collapsible_panel" in tags
    panel = next(e for e in card["body"]["elements"] if e.get("tag") == "collapsible_panel")
    assert "讨论目录" in panel["header"]["title"]["content"]


def test_thread_card_omits_directory_panel_when_empty():
    card = build_thread_card(
        category="c",
        thread_slug="s",
        title="T",
        author_name="a",
        filename="f.md",
        thread_url="http://x",
    )
    tags = [e.get("tag") for e in card["body"]["elements"]]
    assert "collapsible_panel" not in tags
    assert tags == ["markdown", "button"]


# ─── NoOpNotifier accepts v2 signature ─────────────────────────────────────


def test_noop_notifier_silent():
    n = NoOpNotifier()
    n.notify_new_thread(
        category="c", slug="s", title="t", author_name="a",
        filename="f.md",
    )
    n.notify_new_reply(
        category="c", slug="s", thread_title="t", author_name="a",
        filename="f.md",
    )
    n.notify_standalone_mention(
        category="c", slug="s", thread_title="t", target_filename="f.md",
        author_name="a", mention_open_ids=["ou_x"], mention_comments="hi",
    )


# ─── status_change 卡片（P4.5 G 补遗） ────────────────────────────────────


def test_status_change_card_matter_labels():
    """_STATUS_LABEL 现在覆盖 matter 6 态，从/到的中文映射应生效。"""
    card = build_status_change_card(
        thread_title="Auth Redesign",
        author_name="邓柯",
        from_state="executing",
        to_state="finished",
        reason=None,
        thread_url="http://localhost:5173/auth/entry?next=%2Fm%2Fauth-redesign",
    )
    md = card["body"]["elements"][0]["content"]
    assert "执行中" in md and "已完成" in md, md
    # 没传触发文件时不渲染"触发"行
    assert "**触发**" not in md
    assert card["header"]["title"]["content"] == "状态变更：Auth Redesign"


def test_status_change_card_with_trigger_file():
    """matter 路径带触发三件套时，卡片出"触发：<type> — <summary>"行。"""
    card = build_status_change_card(
        thread_title="Auth Redesign",
        author_name="邓柯",
        from_state="executing",
        to_state="finished",
        reason=None,
        thread_url="http://x/auth/entry",
        trigger_type="result",
        trigger_summary="主链路完成，结果可接受",
    )
    md = card["body"]["elements"][0]["content"]
    assert "**触发**：result — 主链路完成，结果可接受" in md


def test_status_change_card_without_matter_labels_fallback_to_raw():
    """unknown state (旧 thread 残留调用、或非标值) fallback 到原字符串，不炸。"""
    card = build_status_change_card(
        thread_title="Legacy",
        author_name="u",
        from_state="open",  # 老 thread 态，不在新 _STATUS_LABEL 里
        to_state="concluded",
        reason=None,
        thread_url="http://x/auth/entry",
    )
    md = card["body"]["elements"][0]["content"]
    assert "open" in md and "concluded" in md


def test_feishu_notifier_matter_status_change_uses_matter_url(monkeypatch):
    """trigger_filename 提供时，按钮跳转应走 /m/:matter_id，而非 /t/:cat/:slug。"""
    captured: list[dict] = []

    class _StubTokens:
        def get(self) -> str:
            return "token"

    n = FeishuNotifier(
        tokens=_StubTokens(),
        web_base_url="http://localhost:5173",
        workspace=None,
    )

    def _fake_broadcast(card, *, event):
        captured.append({"card": card, "event": event})

    monkeypatch.setattr(n, "_broadcast", _fake_broadcast)

    n.notify_status_change(
        category="Pivot", slug="auth-redesign", thread_title="Auth Redesign",
        from_state="executing", to_state="finished",
        author_name="邓柯", reason=None,
        trigger_type="result",
        trigger_summary="完成",
        trigger_filename="004_dengke_result_abc.md",
    )

    assert len(captured) == 1
    card = captured[0]["card"]
    # 按钮链接走 /m/<matter_id>（matter 路由）；next= 参数是 URL-encoded
    btn_url = _extract_button_url(card)
    assert "%2Fm%2Fauth-redesign" in btn_url, btn_url
    assert "%2Ft%2F" not in btn_url, btn_url


def test_feishu_notifier_thread_status_change_uses_thread_url(monkeypatch):
    """未提供 trigger_filename 时按老 thread 路径走 /t/:cat/:slug，兼容老客户端。"""
    captured: list[dict] = []

    class _StubTokens:
        def get(self) -> str:
            return "token"

    n = FeishuNotifier(
        tokens=_StubTokens(),
        web_base_url="http://localhost:5173",
        workspace=None,
    )
    monkeypatch.setattr(n, "_broadcast", lambda card, *, event: captured.append(card))

    n.notify_status_change(
        category="general", slug="legacy-thread", thread_title="Legacy",
        from_state="open", to_state="concluded",
        author_name="u", reason="some reason",
    )

    btn_url = _extract_button_url(captured[0])
    assert "%2Ft%2Fgeneral%2Flegacy-thread" in btn_url


def test_feishu_notifier_owner_change_sends_dm_only(monkeypatch):
    notifier = FeishuNotifier(tokens=None, web_base_url="https://x")  # type: ignore[arg-type]
    calls: dict[str, object] = {"broadcast": 0, "dm_open_ids": []}

    def fake_broadcast(self, card, *, event):
        calls["broadcast"] = int(calls["broadcast"]) + 1

    def fake_dm_many(self, open_ids, card, *, event):
        calls["dm_open_ids"] = list(open_ids)

    monkeypatch.setattr(FeishuNotifier, "_broadcast", fake_broadcast)
    monkeypatch.setattr(FeishuNotifier, "_dm_many", fake_dm_many)

    notifier.notify_owner_change(
        category="c",
        slug="m1",
        thread_title="T",
        actor_name="Alice",
        from_owner_name="Bob",
        to_owner_name="Carol",
        to_owner_open_id="ou_carol",
        reason="换人跟进",
    )

    assert calls["broadcast"] == 0
    assert calls["dm_open_ids"] == ["ou_carol"]


def _extract_button_url(card: dict) -> str:
    """Pull the action URL out of a card (schema 2.0)."""
    import json as _json
    raw = _json.dumps(card, ensure_ascii=False)
    return raw


def test_feishu_notifier_standalone_mention_does_not_dm(monkeypatch):
    """群卡片里 <at id=…> 已能触发推送，不再额外发 DM（避免双通知）。"""
    notifier = FeishuNotifier(tokens=None, web_base_url="https://x")  # type: ignore[arg-type]

    calls: dict[str, int] = {"broadcast": 0, "dm": 0}

    def fake_broadcast(self, card, *, event):
        calls["broadcast"] += 1

    def fake_dm_many(self, open_ids, card, *, event):
        calls["dm"] += 1

    monkeypatch.setattr(FeishuNotifier, "_broadcast", fake_broadcast)
    monkeypatch.setattr(FeishuNotifier, "_dm_many", fake_dm_many)

    notifier.notify_standalone_mention(
        category="c", slug="s", thread_title="t",
        target_filename="001_a.md",
        author_name="Alice",
        mention_open_ids=["ou_x"],
        mention_comments="hi",
    )

    assert calls["broadcast"] == 1
    assert calls["dm"] == 0


# ─── application 卡片（Task 21） ───────────────────────────────────────────


def test_build_application_card_with_button():
    card = build_application_card(
        title="📥 新加入申请：Alice",
        body="**来源**：feishu",
        button_text="去后台审批",
        url="https://pivot.x/admin/applications",
        template="orange",
    )
    assert card["schema"] == "2.0"
    assert card["header"]["template"] == "orange"
    assert card["header"]["title"]["content"] == "📥 新加入申请：Alice"
    md = card["body"]["elements"][0]["content"]
    assert "**来源**：feishu" in md
    button = card["body"]["elements"][-1]
    assert button["tag"] == "button"
    assert button["text"]["content"] == "去后台审批"


def test_build_application_card_button_optional():
    """Reject card has no CTA — caller passes empty button_text/url."""
    card = build_application_card(
        title="🚫 加入申请未通过",
        body="如有疑问请联系管理员",
        button_text="",
        url="",
        template="red",
    )
    assert card["header"]["template"] == "red"
    elements = card["body"]["elements"]
    assert len(elements) == 1
    assert elements[0]["tag"] == "markdown"


def test_feishu_notifier_application_created_dms_admins(monkeypatch):
    class _StubTokens:
        def get(self) -> str:
            return "tok"

    n = FeishuNotifier(tokens=_StubTokens(), web_base_url="https://pivot.x")
    captured: list[dict] = []

    def fake_dm_many(self, open_ids, card, *, event):
        captured.append({"open_ids": list(open_ids), "card": card, "event": event})

    monkeypatch.setattr(FeishuNotifier, "_dm_many", fake_dm_many)

    n.notify_application_created(
        applicant_name="Alice", provider="feishu",
        admin_open_ids=["ou_admin1", "ou_admin2"],
    )
    assert len(captured) == 1
    assert captured[0]["open_ids"] == ["ou_admin1", "ou_admin2"]
    assert "Alice" in captured[0]["card"]["header"]["title"]["content"]
    assert captured[0]["event"].startswith("application_created")


def test_feishu_notifier_application_created_skips_when_no_admins(monkeypatch):
    class _StubTokens:
        def get(self) -> str:
            return "tok"

    n = FeishuNotifier(tokens=_StubTokens(), web_base_url="https://pivot.x")
    calls = {"n": 0}

    def fake_dm_many(self, *_a, **_kw):
        calls["n"] += 1

    monkeypatch.setattr(FeishuNotifier, "_dm_many", fake_dm_many)

    n.notify_application_created(
        applicant_name="Alice", provider="feishu", admin_open_ids=[],
    )
    assert calls["n"] == 0


def test_feishu_notifier_application_approved_merge_path(monkeypatch):
    class _StubTokens:
        def get(self) -> str:
            return "tok"

    n = FeishuNotifier(tokens=_StubTokens(), web_base_url="https://pivot.x")
    captured: list[dict] = []

    def fake_dm_many(self, open_ids, card, *, event):
        captured.append({"open_ids": list(open_ids), "card": card})

    monkeypatch.setattr(FeishuNotifier, "_dm_many", fake_dm_many)

    n.notify_application_approved(applicant_open_id="ou_eve", merged=True)
    assert len(captured) == 1
    assert captured[0]["open_ids"] == ["ou_eve"]
    md = captured[0]["card"]["body"]["elements"][0]["content"]
    assert "并入现有账号" in md
    assert captured[0]["card"]["header"]["template"] == "green"


def test_feishu_notifier_application_approved_new_user_path(monkeypatch):
    class _StubTokens:
        def get(self) -> str:
            return "tok"

    n = FeishuNotifier(tokens=_StubTokens(), web_base_url="https://pivot.x")
    captured: list[dict] = []

    def fake_dm_many(self, open_ids, card, *, event):
        captured.append({"card": card})

    monkeypatch.setattr(FeishuNotifier, "_dm_many", fake_dm_many)

    n.notify_application_approved(applicant_open_id="ou_new", merged=False)
    md = captured[0]["card"]["body"]["elements"][0]["content"]
    assert "欢迎使用" in md


def test_feishu_notifier_application_approved_skips_empty_open_id(monkeypatch):
    class _StubTokens:
        def get(self) -> str:
            return "tok"

    n = FeishuNotifier(tokens=_StubTokens(), web_base_url="https://pivot.x")
    calls = {"n": 0}

    def fake_dm_many(self, *_a, **_kw):
        calls["n"] += 1

    monkeypatch.setattr(FeishuNotifier, "_dm_many", fake_dm_many)

    n.notify_application_approved(applicant_open_id="", merged=False)
    assert calls["n"] == 0


def test_feishu_notifier_application_rejected_uses_red_template(monkeypatch):
    class _StubTokens:
        def get(self) -> str:
            return "tok"

    n = FeishuNotifier(tokens=_StubTokens(), web_base_url="https://pivot.x")
    captured: list[dict] = []

    def fake_dm_many(self, open_ids, card, *, event):
        captured.append({"card": card, "event": event})

    monkeypatch.setattr(FeishuNotifier, "_dm_many", fake_dm_many)

    n.notify_application_rejected(applicant_open_id="ou_reject")
    assert len(captured) == 1
    assert captured[0]["card"]["header"]["template"] == "red"
    assert captured[0]["event"] == "application_rejected"
    elements = captured[0]["card"]["body"]["elements"]
    # No CTA button on rejection — only the markdown body element.
    assert all(e.get("tag") != "button" for e in elements)


def test_noop_notifier_application_methods_silent():
    n = NoOpNotifier()
    n.notify_application_created(
        applicant_name="x", provider="feishu", admin_open_ids=["ou"],
    )
    n.notify_application_approved(applicant_open_id="ou", merged=False)
    n.notify_application_rejected(applicant_open_id="ou")


# ─── annotation DM card (Phase 6) ───────────────────────────────────────────


def test_annotation_dm_card_structure():
    card = build_annotation_dm_card(
        author_name="邓柯",
        thread_title="客户验收流程改造",
        target_filename="003_alice_act_xx.md",
        annotation_type="evaluation",
        annotation_body="结构清楚，不过缺少边界条件",
        post_url="http://x/m/auth-redesign",
    )
    md = card["body"]["elements"][0]["content"]

    # 评价语气而非提醒/评论 — 让 stakeholder 一眼看出是"评价"类反馈
    assert "评价了" in md
    assert "**评价**：结构清楚，不过缺少边界条件" in md
    # 主题 + 文件名都呈现
    assert "**主题**：客户验收流程改造" in md
    assert "邓柯" in md
    assert "003_alice_act_xx.md" in md

    # purple 模板区分于 mention 的 orange — DM 列表里能视觉区分
    assert card["header"]["template"] == "purple"
    assert card["header"]["title"]["content"] == "有人评价了你关注的文件"

    # 按钮跳详情页
    button = card["body"]["elements"][-1]
    assert button["tag"] == "button"
    assert button["multi_url"]["url"] == "http://x/m/auth-redesign"


def test_annotation_dm_card_drops_body_row_when_empty():
    """body 校验在 publish 侧已强制非空, 但渲染层防御性允许空字符串
    并跳过该行而不是输出 '**评价**：'。"""
    card = build_annotation_dm_card(
        author_name="X",
        thread_title="T",
        target_filename="f.md",
        annotation_type="evaluation",
        annotation_body="",
        post_url="http://x",
    )
    md = card["body"]["elements"][0]["content"]
    assert "**评价**：" not in md


def test_feishu_notifier_annotation_sends_dm_only(monkeypatch):
    """关键产品决策: annotation 不发群卡片。落地时确保 _broadcast 不被调用,
    只调 _dm_many。如果未来误加群广播这个用例会抓住。"""
    notifier = FeishuNotifier(tokens=None, web_base_url="https://x")  # type: ignore[arg-type]
    calls: dict[str, object] = {"broadcast": 0, "dm_recipients": []}

    def fake_broadcast(self, card, *, event):
        calls["broadcast"] = int(calls["broadcast"]) + 1

    def fake_dm_many(self, open_ids, card, *, event):
        calls["dm_recipients"] = list(open_ids)

    monkeypatch.setattr(FeishuNotifier, "_broadcast", fake_broadcast)
    monkeypatch.setattr(FeishuNotifier, "_dm_many", fake_dm_many)

    notifier.notify_annotation(
        category="cat", slug="m1", thread_title="T",
        target_filename="003_alice_act.md",
        author_name="邓柯",
        annotation_type="evaluation",
        annotation_body="可以再想想性能",
        stakeholder_open_ids=["ou_alice", "ou_bob"],
    )

    assert calls["broadcast"] == 0
    assert calls["dm_recipients"] == ["ou_alice", "ou_bob"]


def test_feishu_notifier_annotation_no_recipients_no_op(monkeypatch):
    """空 stakeholder 时不该发任何 DM (避免 _dm_many 拿空列表去 _send 0 次
    的 noisy log)。"""
    notifier = FeishuNotifier(tokens=None, web_base_url="https://x")  # type: ignore[arg-type]
    fired = {"dm": 0, "broadcast": 0}
    monkeypatch.setattr(
        FeishuNotifier, "_dm_many",
        lambda self, oids, card, *, event: fired.__setitem__("dm", fired["dm"] + 1),
    )
    monkeypatch.setattr(
        FeishuNotifier, "_broadcast",
        lambda self, card, *, event: fired.__setitem__("broadcast", fired["broadcast"] + 1),
    )

    notifier.notify_annotation(
        category="c", slug="s", thread_title="t",
        target_filename="f.md",
        author_name="a",
        annotation_type="evaluation",
        annotation_body="x",
        stakeholder_open_ids=[],
    )
    assert fired == {"dm": 0, "broadcast": 0}


def test_noop_notifier_annotation_silent():
    NoOpNotifier().notify_annotation(
        category="c", slug="s", thread_title="t",
        target_filename="f.md", author_name="a",
        annotation_type="evaluation", annotation_body="x",
        stakeholder_open_ids=["ou_x"],
    )


# ─── 失效/恢复事件卡(P3) ────────────────────────────────────────────────


def test_matter_event_card_invalidate_misposted():
    """misposted 失效:header 含'失效了文档',row 含 actor / 文件 / 说明。"""
    card = build_matter_event_card(
        thread_title="登录链路重构",
        target_filename="003_dengke_act_abc.md",
        actor_name="邓柯",
        reason="misposted",
        summary="误发,标记失效",
        thread_url="http://x/m/auth",
    )
    md = card["body"]["elements"][0]["content"]
    assert card["header"]["title"]["content"] == "作者失效了文档：登录链路重构"
    assert card["header"]["template"] == "yellow"
    assert "**操作**：邓柯（误发）" in md
    assert "**文件**：003_dengke_act_abc.md" in md
    assert "**说明**：误发,标记失效" in md


def test_matter_event_card_invalidate_inaccurate():
    """inaccurate 失效:理由标签是'信息有误'。"""
    card = build_matter_event_card(
        thread_title="X",
        target_filename="003.md",
        actor_name="A",
        reason="inaccurate",
        summary=None,
        thread_url="http://x/m/X",
    )
    md = card["body"]["elements"][0]["content"]
    assert "失效了文档" in card["header"]["title"]["content"]
    assert "**操作**：A（信息有误）" in md
    # summary 缺失时,**说明** 行不出现
    assert "**说明**" not in md


def test_matter_event_card_restore_uses_distinct_header_and_template():
    """restored 用不同的 header verb('恢复了文档') + 不同的 template。"""
    card = build_matter_event_card(
        thread_title="X",
        target_filename="003.md",
        actor_name="A",
        reason="restored",
        summary=None,
        thread_url="http://x/m/X",
    )
    md = card["body"]["elements"][0]["content"]
    assert card["header"]["title"]["content"] == "作者恢复了文档：X"
    assert card["header"]["template"] == "turquoise"
    assert "**操作**：A（恢复）" in md


def test_matter_event_card_button_links_to_matter_detail():
    card = build_matter_event_card(
        thread_title="X", target_filename="x.md", actor_name="A",
        reason="misposted", summary=None,
        thread_url="http://example/auth/entry?next=/m/foo",
    )
    body = json.dumps(card, ensure_ascii=False)
    assert "/m/foo" in body


def test_matter_event_card_summary_oneline_collapses_newlines():
    """summary 中的换行被 _oneline 折叠,卡片 markdown 不被破坏。"""
    card = build_matter_event_card(
        thread_title="X", target_filename="x.md", actor_name="A",
        reason="misposted",
        summary="第一行\n第二行\r\n第三行",
        thread_url="http://x/m/X",
    )
    md = card["body"]["elements"][0]["content"]
    # 折叠后单行,不含原始换行符
    assert "第一行" in md
    assert "第二行" in md
    assert "\n第二行" not in md  # _oneline 应该把内嵌换行去掉


def test_noop_notifier_matter_event_silent():
    """NoOpNotifier 收到 notify_matter_event 不报错(即便没参数)。"""
    n = NoOpNotifier()
    n.notify_matter_event(
        category="Pivot", slug="m", thread_title="t", target_filename="f.md",
        actor_name="a", reason="misposted", summary=None,
    )  # 不抛异常即通过
