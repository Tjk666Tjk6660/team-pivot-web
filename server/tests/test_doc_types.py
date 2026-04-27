from __future__ import annotations

import pytest

from server.doc_types import (
    ALLOWED_TYPES_BY_STATUS,
    VALID_DOC_TYPES,
    VALID_JUDGEMENTS,
    VALID_OUTCOMES,
    is_doc_type,
    is_type_allowed_in_status,
)


def test_doc_types_are_five():
    assert VALID_DOC_TYPES == {"think", "act", "verify", "result", "insight"}


def test_judgements():
    assert VALID_JUDGEMENTS == {"passed", "failed", "cancelled"}


def test_outcomes():
    assert VALID_OUTCOMES == {"finished", "cancelled"}


@pytest.mark.parametrize("status,allowed", [
    ("planning", {"think", "act", "verify"}),
    ("executing", {"think", "act", "verify", "result"}),
    ("paused", {"think"}),
    ("finished", {"insight"}),
    ("cancelled", {"insight"}),
    ("reviewed", set()),
])
def test_allowed_types_by_status(status, allowed):
    assert set(ALLOWED_TYPES_BY_STATUS[status]) == allowed


def test_is_doc_type():
    for t in ("think", "act", "verify", "result", "insight"):
        assert is_doc_type(t)
    assert not is_doc_type("proposal")
    assert not is_doc_type("reply")
    assert not is_doc_type("")


def test_is_type_allowed_in_status_positive():
    assert is_type_allowed_in_status("result", "executing")
    assert is_type_allowed_in_status("insight", "finished")
    assert is_type_allowed_in_status("insight", "cancelled")
    assert is_type_allowed_in_status("think", "paused")


def test_is_type_allowed_in_status_negative():
    assert not is_type_allowed_in_status("result", "planning")  # deviation: still banned in planning
    assert not is_type_allowed_in_status("act", "paused")
    assert not is_type_allowed_in_status("result", "finished")


def test_reviewed_strict_deny():
    # Deviation: "原则上不再新增" resolved to strict deny
    for t in VALID_DOC_TYPES:
        assert not is_type_allowed_in_status(t, "reviewed")


def test_executing_allows_result_unconditionally():
    # Deviation: no "准备结束时" gating
    assert is_type_allowed_in_status("result", "executing")


def test_unknown_status_returns_false():
    assert not is_type_allowed_in_status("think", "garbage")
