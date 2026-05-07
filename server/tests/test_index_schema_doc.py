"""Guard: schema doc (`AI-docs/pivot-index-schema.md`) and on-disk schema
constants (`server/matter_index.py`) must stay in sync.

Why: the schema doc is the **single source of truth** consumed by every AI
application's prompt (daily report, AI chat, MCP, future AI apps). If a new
field gets added to `_ITEM_KEY_ORDER` etc. but the doc isn't updated in the
same commit, every AI app will silently miss the new field — they have no
way to know it exists.

This test scans the canonical key-order constants in matter_index.py and
verifies each non-trivial field name appears at least once in the schema
doc. Diff failures should be fixed by editing the doc, not by silencing
this test.

Tolerated noise:
- Field names that are obviously documented under a different surface form
  (e.g. timestamps "created_at" / "updated_at" appear many times — the test
  checks substring presence, not exact key match).
- Whitespace / heading style — only checks "field name string appears in
  doc raw text".
"""
from __future__ import annotations

from pathlib import Path

import pytest

from server.matter_index import (
    _ITEM_KEY_ORDER,
    _OWNER_CHANGE_KEY_ORDER,
    _INVALIDATION_EVENT_KEY_ORDER,
    _MATTER_KEY_ORDER,
)


SCHEMA_DOC_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "AI-docs" / "pivot-index-schema.md"
)


@pytest.fixture(scope="module")
def schema_doc_text() -> str:
    if not SCHEMA_DOC_PATH.exists():
        pytest.fail(
            f"schema doc missing at {SCHEMA_DOC_PATH}. "
            "This file is the single authoritative source consumed by every "
            "AI application's prompt — recreate it before continuing."
        )
    return SCHEMA_DOC_PATH.read_text(encoding="utf-8")


def _assert_fields_in_doc(
    doc_text: str, fields: tuple[str, ...], context: str,
) -> None:
    missing = [f for f in fields if f not in doc_text]
    if missing:
        pytest.fail(
            f"{context}: the following field name(s) appear in "
            f"server/matter_index.py constants but NOT in "
            f"AI-docs/pivot-index-schema.md:\n  - "
            + "\n  - ".join(missing)
            + "\n\nFix by adding them to the schema doc — this guards every "
            "AI application from silently missing new fields."
        )


def test_matter_top_level_fields_documented(schema_doc_text):
    """`_MATTER_KEY_ORDER` (matter 顶层字段) 全部要在 schema doc 出现。"""
    _assert_fields_in_doc(
        schema_doc_text, _MATTER_KEY_ORDER, "matter top-level"
    )


def test_file_item_fields_documented(schema_doc_text):
    """`_ITEM_KEY_ORDER` (文件项字段) 全部要在 schema doc 出现。"""
    _assert_fields_in_doc(
        schema_doc_text, _ITEM_KEY_ORDER, "file item"
    )


def test_owner_change_fields_documented(schema_doc_text):
    """`_OWNER_CHANGE_KEY_ORDER` (owner_change 事件) 全部要在 schema doc 出现。"""
    _assert_fields_in_doc(
        schema_doc_text, _OWNER_CHANGE_KEY_ORDER, "owner_change event"
    )


def test_invalidation_event_fields_documented(schema_doc_text):
    """`_INVALIDATION_EVENT_KEY_ORDER` (失效/恢复事件) 全部要在 schema doc 出现。"""
    _assert_fields_in_doc(
        schema_doc_text, _INVALIDATION_EVENT_KEY_ORDER, "invalidation event"
    )


def test_schema_doc_has_authoritative_preamble(schema_doc_text):
    """Schema doc 顶部必须含"权威源 + 改 index 必须同步"提示,提醒维护者
    本文件是合规层面的硬约束,不是普通文档。"""
    head = schema_doc_text[:1000]   # 前 1000 字符就该看到权威性表态
    required_signals = ["权威源", "matter_index.py", "test_index_schema_doc.py"]
    missing = [s for s in required_signals if s not in head]
    assert not missing, (
        f"schema doc preamble missing authority signals: {missing}. "
        "The first ~1000 chars should make clear this file is the single "
        "source of truth and that the test guards sync."
    )


def test_invalidation_semantics_documented(schema_doc_text):
    """invalidate 字段的语义解释必须写清楚 ——"声明式撤回,不是隐藏",
    AI 应能看到 invalidated 元数据。这两点是产品设计 §四 的核心。
    AI 应用的 prompt 业务规则会基于这两点写"如何使用 invalidated"。"""
    must_contain = [
        "声明式",
        "invalidated",
        "可见",            # AI 应可见的语义
    ]
    missing = [s for s in must_contain if s not in schema_doc_text]
    assert not missing, (
        f"invalidate semantics under-documented in schema doc: {missing}. "
        "Per product-design §四, the doc must convey: declarative invalidation "
        "(not hiding), AI should see invalidated_* metadata."
    )


def test_three_timeline_entry_forms_documented(schema_doc_text):
    """3 种 timeline entry 形态(文件项 / owner_change / 失效-恢复)的识别
    方法必须在 schema doc 显式说明,这是 AI 应用读 timeline 的基本判别能力。"""
    # 不强求精确措辞,只 sanity check 各种关键词都覆盖
    must_contain = [
        "文件项",
        "owner_change",
        "失效",
        "reason",
    ]
    missing = [s for s in must_contain if s not in schema_doc_text]
    assert not missing, (
        f"3-form timeline entry section missing keywords: {missing}"
    )
