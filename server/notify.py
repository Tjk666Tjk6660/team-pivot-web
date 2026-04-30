from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Callable, Protocol

import httpx

from server.feishu_token import FeishuTokenManager

if TYPE_CHECKING:
    from server.workspace import Workspace

log = logging.getLogger(__name__)

_LIST_CHATS_ENDPOINT = "https://open.feishu.cn/open-apis/im/v1/chats"
_SEND_MESSAGE_ENDPOINT = "https://open.feishu.cn/open-apis/im/v1/messages"
_TIMEOUT = 10.0

# 偶发的 CN 网络冷连接 SSL 握手超时(`_ssl.c:993: handshake timed out`)
# 在飞书 API 上不算少见。一次重试就能让 80%+ 的抖动通过,所以集中
# 在两个 HTTP 调用包一层。
_TRANSIENT_HTTP_ERRORS = (
    httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError,
)


def _http_get_with_retry(url: str, **kwargs) -> httpx.Response:
    """One retry on transient connection errors."""
    try:
        return httpx.get(url, **kwargs)
    except _TRANSIENT_HTTP_ERRORS as e:
        log.warning("notify GET transient %s, retrying once: %s",
                    type(e).__name__, e)
        return httpx.get(url, **kwargs)


def _http_post_with_retry(url: str, **kwargs) -> httpx.Response:
    """One retry on transient connection errors."""
    try:
        return httpx.post(url, **kwargs)
    except _TRANSIENT_HTTP_ERRORS as e:
        log.warning("notify POST transient %s, retrying once: %s",
                    type(e).__name__, e)
        return httpx.post(url, **kwargs)


class Notifier(Protocol):
    def notify_new_thread(
        self,
        *,
        category: str,
        slug: str,
        title: str,
        author_name: str,
        filename: str,
        body: str | None = None,
        owner_open_id: str | None = None,
        mention_open_ids: list[str] | None = None,
        mention_comments: str | None = None,
    ) -> None: ...

    def notify_new_reply(
        self,
        *,
        category: str,
        slug: str,
        thread_title: str,
        author_name: str,
        filename: str,
        body: str | None = None,
        mention_open_ids: list[str] | None = None,
        mention_comments: str | None = None,
    ) -> None: ...

    def notify_status_change(
        self,
        *,
        category: str,
        slug: str,
        thread_title: str,
        from_state: str,
        to_state: str,
        author_name: str,
        reason: str | None,
        # P4.5 G 补遗：matter 路径把"触发文件"三件套透传进来，
        # 渲染端据此拼出"触发：<type> — <summary>"行、生成 matter URL。
        # 老 thread 调用方不传，行为不变。
        trigger_type: str | None = None,
        trigger_summary: str | None = None,
        trigger_filename: str | None = None,
    ) -> None: ...

    def notify_owner_change(
        self,
        *,
        category: str,
        slug: str,
        thread_title: str,
        actor_name: str,
        from_owner_name: str | None,
        to_owner_name: str,
        to_owner_open_id: str,
        reason: str,
        status_change: dict | None = None,
    ) -> None: ...

    def notify_standalone_mention(
        self,
        *,
        category: str,
        slug: str,
        thread_title: str,
        target_filename: str,
        author_name: str,
        mention_open_ids: list[str],
        mention_comments: str,
    ) -> None: ...

    def notify_application_created(
        self,
        *,
        applicant_name: str,
        provider: str,
        admin_open_ids: list[str],
    ) -> None: ...

    def notify_application_approved(
        self,
        *,
        applicant_open_id: str,
        merged: bool,
    ) -> None: ...

    def notify_application_rejected(
        self,
        *,
        applicant_open_id: str,
    ) -> None: ...


class NoOpNotifier:
    def notify_new_thread(self, **_: object) -> None: pass
    def notify_new_reply(self, **_: object) -> None: pass
    def notify_status_change(self, **_: object) -> None: pass
    def notify_owner_change(self, **_: object) -> None: pass
    def notify_standalone_mention(self, **_: object) -> None: pass
    def notify_application_created(self, **_: object) -> None: pass
    def notify_application_approved(self, **_: object) -> None: pass
    def notify_application_rejected(self, **_: object) -> None: pass


class FeishuNotifier:
    def __init__(
        self,
        *,
        tokens: FeishuTokenManager,
        web_base_url: str,
        workspace: "Workspace | None" = None,
    ) -> None:
        self._tokens = tokens
        self._web_base_url = web_base_url.rstrip("/")
        self._workspace = workspace

    def notify_new_thread(
        self,
        *,
        category: str,
        slug: str,
        title: str,
        author_name: str,
        filename: str,
        body: str | None = None,
        owner_open_id: str | None = None,
        mention_open_ids: list[str] | None = None,
        mention_comments: str | None = None,
    ) -> None:
        post_url = self._post_url(category, slug, filename)
        directory_content, post_count = self._build_directory(category, slug, filename)
        card = build_thread_card(
            category=category,
            thread_slug=slug,
            title=title,
            author_name=author_name,
            filename=filename,
            body=body,
            thread_url=post_url,
            owner_open_id=owner_open_id,
            mention_open_ids=mention_open_ids or [],
            mention_comments=mention_comments,
            directory_content=directory_content,
            directory_post_count=post_count,
        )
        self._broadcast(card, event=f"new_thread slug={slug}")
        if mention_open_ids:
            dm = build_mention_dm_card(
                author_name=author_name,
                thread_title=title,
                thread_slug=slug,
                target_filename=filename,
                kind="发起讨论",
                comments=mention_comments,
                post_url=post_url,
            )
            self._dm_many(mention_open_ids, dm, event=f"new_thread slug={slug}")

    def notify_new_reply(
        self,
        *,
        category: str,
        slug: str,
        thread_title: str,
        author_name: str,
        filename: str,
        body: str | None = None,
        mention_open_ids: list[str] | None = None,
        mention_comments: str | None = None,
    ) -> None:
        post_url = self._post_url(category, slug, filename)
        directory_content, post_count = self._build_directory(category, slug, filename)
        card = build_reply_card(
            category=category,
            thread_slug=slug,
            thread_title=thread_title,
            author_name=author_name,
            filename=filename,
            body=body,
            thread_url=post_url,
            mention_open_ids=mention_open_ids or [],
            mention_comments=mention_comments,
            directory_content=directory_content,
            directory_post_count=post_count,
        )
        self._broadcast(card, event=f"new_reply slug={slug}")
        if mention_open_ids:
            dm = build_mention_dm_card(
                author_name=author_name,
                thread_title=thread_title,
                thread_slug=slug,
                target_filename=filename,
                kind="回复讨论",
                comments=mention_comments,
                post_url=post_url,
            )
            self._dm_many(mention_open_ids, dm, event=f"new_reply slug={slug}")

    def notify_application_created(
        self,
        *,
        applicant_name: str,
        provider: str,
        admin_open_ids: list[str],
    ) -> None:
        # TODO(Task 21): real card builder — send DM to each admin open_id
        pass

    def notify_application_approved(
        self,
        *,
        applicant_open_id: str,
        merged: bool,
    ) -> None:
        # TODO(Task 21): DM the applicant via feishu open_id with approval card
        pass

    def notify_application_rejected(
        self,
        *,
        applicant_open_id: str,
    ) -> None:
        # TODO(Task 21): DM the applicant via feishu open_id with rejection card
        pass

    def notify_standalone_mention(
        self, *, category, slug, thread_title, target_filename,
        author_name, mention_open_ids, mention_comments,
    ) -> None:
        post_url = self._post_url(category, slug, target_filename)
        card = build_standalone_mention_card(
            category=category,
            thread_slug=slug,
            thread_title=thread_title,
            author_name=author_name,
            target_filename=target_filename,
            mention_open_ids=mention_open_ids,
            mention_comments=mention_comments,
            post_url=post_url,
        )
        self._broadcast(card, event=f"mention slug={slug} file={target_filename}")

    def notify_status_change(
        self, *, category, slug, thread_title, from_state, to_state, author_name, reason,
        trigger_type: str | None = None,
        trigger_summary: str | None = None,
        trigger_filename: str | None = None,
    ) -> None:
        # matter 路径的触发三件套齐全时，按 matter URL 指回详情页；否则走老
        # thread URL（同事 P3 已不用，但保留兼容 PAT / VS Code 客户端调用）。
        is_matter = trigger_filename is not None
        detail_url = (
            self._matter_url(slug)
            if is_matter
            else self._thread_url(category, slug)
        )
        card = build_status_change_card(
            thread_title=thread_title,
            author_name=author_name,
            from_state=from_state,
            to_state=to_state,
            reason=reason,
            thread_url=detail_url,
            trigger_type=trigger_type,
            trigger_summary=trigger_summary,
        )
        self._broadcast(card, event=f"status_change slug={slug} {from_state}->{to_state}")

    def notify_owner_change(
        self,
        *,
        category: str,
        slug: str,
        thread_title: str,
        actor_name: str,
        from_owner_name: str | None,
        to_owner_name: str,
        to_owner_open_id: str,
        reason: str,
        status_change: dict | None = None,
    ) -> None:
        detail_url = self._matter_url(slug)
        card = build_owner_change_card(
            thread_title=thread_title,
            actor_name=actor_name,
            from_owner_name=from_owner_name,
            to_owner_name=to_owner_name,
            to_owner_open_id=to_owner_open_id,
            reason=reason,
            thread_url=detail_url,
            status_change=status_change,
        )
        self._dm_many([to_owner_open_id], card, event=f"owner_change slug={slug}")

    def _thread_url(self, category: str, slug: str) -> str:
        from urllib.parse import urlencode

        next_path = f"/t/{category}/{slug}"
        return f"{self._web_base_url}/auth/entry?{urlencode({'next': next_path})}"

    def _matter_url(self, matter_id: str) -> str:
        """P4.5 G 补遗：前端 matter 详情页路由为 /m/:matter_id，
        通知卡片的跳转按钮在 matter 场景下用这个 URL。"""
        from urllib.parse import urlencode

        next_path = f"/m/{matter_id}"
        return f"{self._web_base_url}/auth/entry?{urlencode({'next': next_path})}"

    def _post_url(self, category: str, slug: str, filename: str) -> str:
        """Post-migration: the old /t/<cat>/<slug>?post=<anchor>#post-<anchor>
        route is gone; the matter detail page lives at /m/<matter_id>
        (matter_id == slug per migration plan §5). Land users on the matter
        detail; per-file deep-link anchoring is deferred to a future
        enhancement (would require MatterDetailPane to scroll-to-file).

        `category` and `filename` are now unused but kept for caller compat
        (notify_*, build_thread_directory's post_url_builder hook).
        """
        del category, filename
        return self._matter_url(slug)

    def _build_directory(
        self, category: str, slug: str, current_filename: str,
    ) -> tuple[str, int]:
        """Return (content, post_count) for the thread-directory panel.

        Returns ("", 0) if there is no workspace reference or the thread
        can't be read — callers skip adding the panel in that case.
        """
        if self._workspace is None:
            return "", 0
        return build_thread_directory(
            self._workspace,
            category=category,
            slug=slug,
            current_filename=current_filename,
            post_url_builder=self._post_url,
        )

    def broadcast_card(self, card: dict, *, event: str) -> None:
        """Public hook for "send any card to all chats the bot is in".
        Used by daily-report (and future periodic jobs like weekly digest)
        that don't fit one of the existing notify_* shapes. Internally
        delegates to `_broadcast`; failures are swallowed + logged inside."""
        self._broadcast(card, event=event)

    def _broadcast(self, card: dict, *, event: str) -> None:
        try:
            token = self._tokens.get()
            chats = self._list_chats(token)
            if not chats:
                log.warning("notify skipped (bot in no chats): %s", event)
                return
            sent = sum(1 for cid in chats if self._send(token, cid, "chat_id", card))
            log.info("notify sent to %d/%d chats: %s", sent, len(chats), event)
        except Exception:
            log.warning("notify broadcast failed: %s", event, exc_info=True)

    def _dm_many(self, open_ids: list[str], card: dict, *, event: str) -> None:
        try:
            token = self._tokens.get()
            sent = sum(1 for oid in open_ids if self._send(token, oid, "open_id", card))
            log.info("notify DM sent to %d/%d users: %s", sent, len(open_ids), event)
        except Exception:
            log.warning("notify dm failed: %s", event, exc_info=True)

    def _list_chats(self, token: str) -> list[str]:
        chats: list[str] = []
        page_token = ""
        while True:
            params: dict[str, object] = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            resp = _http_get_with_retry(
                _LIST_CHATS_ENDPOINT, params=params,
                headers={"Authorization": f"Bearer {token}"}, timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"list chats error: {data}")
            for item in data.get("data", {}).get("items", []):
                if item.get("chat_id"):
                    chats.append(item["chat_id"])
            if not data.get("data", {}).get("has_more"):
                break
            page_token = data.get("data", {}).get("page_token", "")
            if not page_token:
                break
        return chats

    def _send(self, token: str, receive_id: str, receive_id_type: str, card: dict) -> bool:
        try:
            resp = _http_post_with_retry(
                _SEND_MESSAGE_ENDPOINT,
                params={"receive_id_type": receive_id_type},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "receive_id": receive_id,
                    "msg_type": "interactive",
                    "content": json.dumps(card, ensure_ascii=False),
                },
                timeout=_TIMEOUT,
            )
            if resp.status_code != 200:
                log.warning("send non-200 to=%s status=%d", receive_id, resp.status_code)
                return False
            data = resp.json()
            if data.get("code") != 0:
                log.warning("send error to=%s code=%s msg=%s",
                            receive_id, data.get("code"), data.get("msg"))
                return False
            return True
        except Exception:
            log.warning("send exception to=%s", receive_id, exc_info=True)
            return False


def build_thread_card(
    *,
    category: str,
    thread_slug: str,
    title: str,
    author_name: str,
    filename: str,
    thread_url: str,
    body: str | None = None,
    owner_open_id: str | None = None,
    mention_open_ids: list[str] | None = None,
    mention_comments: str | None = None,
    directory_content: str | None = None,
    directory_post_count: int | None = None,
) -> dict:
    return _build_card_6fields(
        header=f"📨 来自 {author_name} 的新讨论主题通知：{title}",
        template="blue",
        category=category,
        thread_title=title,
        action_text="发起了新讨论",
        author_name=author_name,
        filename=filename,
        body=body,
        thread_url=thread_url,
        button_text="去 Web 查看",
        owner_open_id=owner_open_id,
        mention_open_ids=mention_open_ids or [],
        mention_comments=mention_comments,
        directory_content=directory_content,
        directory_post_count=directory_post_count,
    )


def build_reply_card(
    *,
    category: str,
    thread_slug: str,
    thread_title: str,
    author_name: str,
    filename: str,
    thread_url: str,
    body: str | None = None,
    mention_open_ids: list[str] | None = None,
    mention_comments: str | None = None,
    directory_content: str | None = None,
    directory_post_count: int | None = None,
) -> dict:
    return _build_card_6fields(
        header=f"📩 来自 {author_name} 的新回复通知：{thread_title}",
        template="green",
        category=category,
        thread_title=thread_title,
        action_text="发布了新回复",
        author_name=author_name,
        filename=filename,
        body=body,
        thread_url=thread_url,
        button_text="查看讨论",
        mention_open_ids=mention_open_ids or [],
        mention_comments=mention_comments,
        directory_content=directory_content,
        directory_post_count=directory_post_count,
    )


_STATUS_LABEL = {
    "planning": "计划中",
    "executing": "执行中",
    "paused": "已暂停",
    "finished": "已完成",
    "cancelled": "已取消",
    "reviewed": "已复盘",
}


def build_status_change_card(
    *, thread_title, author_name, from_state, to_state, reason, thread_url,
    trigger_type: str | None = None,
    trigger_summary: str | None = None,
) -> dict:
    md_parts = [
        f"**操作**：{author_name}",
        f"**状态**：{_STATUS_LABEL.get(from_state, from_state)} → "
        f"{_STATUS_LABEL.get(to_state, to_state)}",
    ]
    # matter 场景：触发文件 type + summary 给出"为什么"——比老 thread
    # 的 reason 字段密度更高，也更忠于 matter "文件承载事实" 的设计。
    if trigger_type and trigger_summary:
        md_parts.append(f"**触发**：{trigger_type} — {trigger_summary}")
    if reason:
        md_parts.append(f"**原因**：{reason}")
    return _card_shell(
        header=f"状态变更：{thread_title}",
        template="purple",
        markdown="\n\n".join(md_parts),
        button_text="查看讨论",
        thread_url=thread_url,
    )


def build_owner_change_card(
    *,
    thread_title: str,
    actor_name: str,
    from_owner_name: str | None,
    to_owner_name: str,
    to_owner_open_id: str,
    reason: str,
    thread_url: str,
    status_change: dict | None = None,
) -> dict:
    to_at = f'<at id="{to_owner_open_id}"></at>'
    from_label = from_owner_name or "未分配"
    rows: list[tuple[str, str]] = [
        ("操作", f"{actor_name} 更改负责人"),
        ("负责人", f"{from_label} → {to_at}"),
        ("新负责人", to_owner_name),
        ("原因", _oneline(reason)),
    ]
    if status_change:
        rows.append((
            "状态",
            f"{_STATUS_LABEL.get(str(status_change.get('from') or ''), str(status_change.get('from') or ''))}"
            f" → {_STATUS_LABEL.get(str(status_change.get('to') or ''), str(status_change.get('to') or ''))}"
        ))
    markdown_rows = [f"**{label}**：{value}" for label, value in rows]
    return _card_shell(
        header=f"负责人变更：{thread_title}",
        template="yellow",
        markdown="<br>".join(markdown_rows),
        button_text="查看讨论",
        thread_url=thread_url,
    )


def build_standalone_mention_card(
    *,
    category: str,
    thread_slug: str,
    thread_title: str,
    author_name: str,
    target_filename: str,
    mention_open_ids: list[str],
    mention_comments: str,
    post_url: str,
) -> dict:
    """Standalone mention 群卡片（邮件式评论体）。

    评论行布局：
      **评论**：<橙色主评论人> <at><at>… 说：<br>{comment}

    每个 <at id="ou_xxx"></at> 的 content 留空，由飞书自动拉取最新中文名 + 头像，
    并触发被 @ 人的红点 + 推送（schema 2.0 markdown tag 行为）。

    元信息块固定顺序：时间 → 项目 → 主题 → 被评文件。被评人不在卡片上显式出现，
    读者要看是谁的帖子可以看 target_filename（含作者 pinyin）或点按钮跳进 Web。
    """
    from datetime import datetime

    at_tags = " ".join(f'<at id="{oid}"></at>' for oid in mention_open_ids)
    comment_line = (
        f"**评论**：<font color='orange'>**{author_name}**</font> "
        f"{at_tags} 说：<br>{_oneline(mention_comments)}"
    )

    info_rows = [
        f"**时间**：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**项目**：{category}",
        f"**主题**：{thread_title}",
        f"**被评文件**：{target_filename}",
    ]
    info_block = "<br>".join(info_rows)

    return _card_shell(
        header=f"📣 提及：{thread_title}",
        template="orange",
        markdown="\n\n".join([comment_line, info_block]),
        button_text="查看该帖子",
        thread_url=post_url,
    )


def build_mention_dm_card(
    *,
    author_name: str,
    thread_title: str,
    thread_slug: str,
    target_filename: str,
    kind: str,
    comments: str | None,
    post_url: str,
    post_excerpt: str | None = None,
) -> dict:
    lines = [f"**{author_name}** 在「{thread_title}」的 {kind} 中 @ 了你"]
    lines.append(f"**帖子**：{target_filename}")
    clean_comments = _oneline(comments)
    if clean_comments:
        lines.append(f"**说明**：{clean_comments}")

    sections = ["<br>".join(lines)]
    if post_excerpt:
        sections.append(f"**相关内容**：{_truncate(post_excerpt, 150)}")
    return _card_shell(
        header="有人 @ 了你",
        template="orange",
        markdown="\n\n".join(sections),
        button_text="去查看",
        thread_url=post_url,
    )


def _build_card_6fields(
    *,
    header: str,
    template: str,
    category: str,
    thread_title: str,
    action_text: str,
    author_name: str,
    filename: str | None,
    thread_url: str,
    button_text: str,
    owner_open_id: str | None = None,
    mention_open_ids: list[str],
    mention_comments: str | None,
    body: str | None = None,
    directory_content: str | None = None,
    directory_post_count: int | None = None,
) -> dict:
    """Build the 6-field info card (project / thread / action / file / time).

    @mention block, 说明, and the 5 info rows all live in a single paragraph
    joined with <br> so Feishu's markdown tag does not insert paragraph
    spacing between rows.

    Note: this is the v2 card layout. v1 included a 7th row (摘要) sourced
    from summary frontmatter; summary ability is deferred to the next phase
    so this version omits that row entirely. If summary comes back later,
    append one more paragraph section here.
    """
    from datetime import datetime

    info_rows: list[str] = []
    info_rows.append(f"**项目**：{category}")
    info_rows.append(f"**主题**：{thread_title}")
    info_rows.append(f"**操作**：{author_name} {action_text}")
    if owner_open_id:
        info_rows.append(f"**负责人**：{_at_tags([owner_open_id])}")
    if mention_open_ids:
        # Schema 2.0 markdown tag uses `<at id="...">`. The legacy `user_id`
        # attribute is silently ignored by Feishu — the @-tag never fires red
        # dots / pushes. Keep this aligned with build_standalone_mention_card.
        info_rows.append(f"**圈人**：{_at_tags(mention_open_ids)}")
    if filename:
        info_rows.append(f"**文件**：{filename}")
    info_rows.append(f"**时间**：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    clean_comments = _oneline(mention_comments)
    if clean_comments:
        info_rows.append(f"**说明**：{clean_comments}")
    preview = _preview_body(body)
    if preview:
        info_rows.append(f"**内容**：{preview}")

    return _card_shell(
        header=header, template=template,
        markdown="<br>".join(info_rows),
        button_text=button_text, thread_url=thread_url,
        directory_content=directory_content,
        directory_post_count=directory_post_count,
    )


def build_thread_directory(
    workspace: "Workspace",
    *,
    category: str,
    slug: str,
    current_filename: str,
    post_url_builder: Callable[[str, str, str], str] | None = None,
) -> tuple[str, int]:
    """Build a lark_md-formatted listing of every post in the thread.

    Mirrors appv2's 讨论目录 block but without per-post summaries (summary
    ability is deferred to the next phase). Each post is one entry showing
    filename (optionally linked), author, and date. The current post is
    highlighted in blue with a 🔷 marker; others use 📄.

    Returns ``(content, post_count)``; ``("", 0)`` on any failure so the
    caller can skip rendering the panel.
    """
    try:
        from server.threads import get_thread
        detail = get_thread(
            workspace.discussions_dir, workspace.index_dir, category, slug,
        )
    except Exception:
        log.warning(
            "build_thread_directory failed category=%s slug=%s",
            category, slug, exc_info=True,
        )
        return "", 0
    if detail is None:
        return "", 0

    entries: list[str] = []
    for post in detail.posts:
        fname = post.filename
        fm = post.frontmatter or {}
        author = str(fm.get("author") or "unknown")
        created = str(fm.get("created") or "")
        date_short = created[:10] if created else ""

        if post_url_builder is not None:
            label = f"[{fname}]({post_url_builder(category, slug, fname)})"
        else:
            label = fname
        header_bits = [f"**{label}**", author]
        if date_short:
            header_bits.append(date_short)
        head = " · ".join(header_bits)

        if fname == current_filename:
            head = f"<font color='blue'>🔷 {head}</font>"
        else:
            head = f"📄 {head}"

        entries.append(head)

    return "\n\n".join(entries), len(detail.posts)


def _card_shell(
    *,
    header: str,
    template: str,
    markdown: str,
    button_text: str | None = None,
    thread_url: str | None = None,
    directory_content: str | None = None,
    directory_post_count: int | None = None,
) -> dict:
    """Build a Feishu interactive card (schema 2.0). Pass `button_text` and
    `thread_url` together for a CTA button at the bottom; pass neither for
    a button-less card (used by daily-report — that flow has no in-product
    page worth deep-linking to)."""
    elements: list[dict] = [{"tag": "markdown", "content": markdown}]
    if directory_content:
        elements.append(_card_directory_panel(directory_content, directory_post_count))
    if button_text and thread_url:
        elements.append(_card_button(button_text, thread_url))
    return _card_payload(header, template, elements)


def _card_shell_elements(
    *,
    header: str,
    template: str,
    elements: list[dict],
    button_text: str,
    thread_url: str,
    directory_content: str | None = None,
    directory_post_count: int | None = None,
) -> dict:
    out = list(elements)
    if directory_content:
        out.append(_card_directory_panel(directory_content, directory_post_count))
    out.append(_card_button(button_text, thread_url))
    return _card_payload(header, template, out)


def _card_field_row(label: str, value: str) -> dict:
    return {
        "tag": "column_set",
        "flex_mode": "none",
        "background_style": "default",
        "columns": [
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "vertical_align": "top",
                "elements": [
                    {
                        "tag": "markdown",
                        "content": f"**{label}**：",
                        "text_align": "left",
                    },
                ],
            },
            {
                "tag": "column",
                "width": "weighted",
                "weight": 8,
                "vertical_align": "top",
                "elements": [
                    {
                        "tag": "markdown",
                        "content": value,
                        "text_align": "left",
                    },
                ],
            },
        ],
    }


def _card_button(button_text: str, thread_url: str) -> dict:
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": button_text},
        "type": "primary",
        "multi_url": {"url": thread_url, "pc_url": "", "android_url": "", "ios_url": ""},
    }


def _card_directory_panel(
    directory_content: str,
    directory_post_count: int | None = None,
) -> dict:
    post_count = directory_post_count or 0
    title = (
        f"<font color='orange'>**📂 讨论目录（{post_count} 篇帖子）**</font>"
        if post_count
        else "<font color='orange'>**📂 讨论目录**</font>"
    )
    return {
        "tag": "collapsible_panel",
        "expanded": False,
        "header": {
            "title": {"tag": "markdown", "content": title},
            "vertical_align": "center",
            "padding": "4px 0 4px 8px",
        },
        "elements": [
            {"tag": "markdown", "content": directory_content},
        ],
    }


def _card_payload(header: str, template: str, elements: list[dict]) -> dict:
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": header},
            "template": template,
        },
        "body": {
            "padding": "4px 16px 12px 16px",
            "elements": elements,
        },
    }


def _truncate(s: str, n: int) -> str:
    s = s.strip()
    return s if len(s) <= n else s[:n].rstrip() + "…"


def _oneline(s: str | None) -> str:
    """Collapse to a single line so the field stays on one row and doesn't
    introduce paragraph breaks that Feishu's markdown tag pads with extra
    vertical margin.
    """
    if not s:
        return ""
    return " ".join(s.split())


def _at_tags(open_ids: list[str]) -> str:
    return " ".join(f'<at id="{oid}"></at>' for oid in open_ids)


def _strip_markdown(s: str) -> str:
    """Strip common markdown syntax so the preview reads as plain text.

    Handles code fences / inline code, images, links, headings, blockquotes,
    list markers, horizontal rules, bold / italic / strikethrough, and HTML
    tags. Collapses all whitespace into single spaces.
    """
    s = re.sub(r"```[\s\S]*?```", " ", s)
    s = re.sub(r"`([^`]*)`", r"\1", s)
    s = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"\[([^\]]*)\]\[[^\]]*\]", r"\1", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", s)
    s = re.sub(r"(?m)^\s*>\s?", "", s)
    s = re.sub(r"(?m)^\s*[-*+]\s+", "", s)
    s = re.sub(r"(?m)^\s*\d+\.\s+", "", s)
    s = re.sub(r"(?m)^\s*[-*_]{3,}\s*$", "", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"__([^_]+)__", r"\1", s)
    s = re.sub(r"\*([^*\n]+)\*", r"\1", s)
    s = re.sub(r"(?<!\w)_([^_\n]+)_(?!\w)", r"\1", s)
    s = re.sub(r"~~([^~]+)~~", r"\1", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _preview_body(body: str | None, limit: int = 200) -> str:
    if not body:
        return ""
    cleaned = _strip_markdown(body)
    if not cleaned:
        return ""
    return cleaned if len(cleaned) <= limit else cleaned[:limit].rstrip() + "..."
