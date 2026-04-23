from __future__ import annotations

import pytest

from server.matter_validator import OK, validate_append


def _matter(status: str) -> dict:
    return {"matter": {"current_status": status}, "timeline": []}


# ---------- happy paths ----------

def test_think_in_planning_ok():
    assert validate_append(_matter("planning"), {"type": "think"}) == OK


def test_act_in_planning_ok():
    assert validate_append(_matter("planning"), {"type": "act"}) == OK


def test_verify_in_planning_ok():
    item = {
        "type": "verify",
        "verifications": [{"target": "f.md", "judgement": "passed", "comment": ""}],
    }
    assert validate_append(_matter("planning"), item) == OK


def test_result_in_executing_ok():
    item = {
        "type": "result",
        "outcome": "finished",
        "status_change": {"from": "executing", "to": "finished"},
    }
    assert validate_append(_matter("executing"), item) == OK


def test_insight_in_finished_ok():
    assert validate_append(_matter("finished"), {"type": "insight"}) == OK


def test_insight_triggers_reviewed_from_finished_ok():
    item = {
        "type": "insight",
        "status_change": {"from": "finished", "to": "reviewed"},
    }
    assert validate_append(_matter("finished"), item) == OK


def test_think_triggers_paused_from_executing_ok():
    item = {
        "type": "think",
        "status_change": {"from": "executing", "to": "paused"},
    }
    assert validate_append(_matter("executing"), item) == OK


def test_act_triggers_planning_to_executing_ok():
    item = {
        "type": "act",
        "status_change": {"from": "planning", "to": "executing"},
    }
    assert validate_append(_matter("planning"), item) == OK


# ---------- type × status matrix violations ----------

def test_result_in_planning_rejected():
    item = {"type": "result", "outcome": "finished"}
    r = validate_append(_matter("planning"), item)
    assert not r.ok and r.code == "type_not_allowed"


def test_act_in_paused_rejected():
    r = validate_append(_matter("paused"), {"type": "act"})
    assert not r.ok and r.code == "type_not_allowed"


def test_insight_in_planning_rejected():
    r = validate_append(_matter("planning"), {"type": "insight"})
    assert not r.ok and r.code == "type_not_allowed"


def test_reviewed_strict_deny_any_type():
    for t in ("think", "act", "verify", "result", "insight"):
        r = validate_append(_matter("reviewed"), {"type": t})
        assert not r.ok and r.code == "type_not_allowed"


def test_think_in_finished_rejected():
    r = validate_append(_matter("finished"), {"type": "think"})
    assert not r.ok and r.code == "type_not_allowed"


# ---------- structural rejections ----------

def test_missing_type_rejected():
    r = validate_append(_matter("planning"), {})
    assert not r.ok and r.code == "type_missing"


def test_unknown_type_rejected():
    r = validate_append(_matter("planning"), {"type": "proposal"})
    assert not r.ok and r.code == "unknown_type"


def test_unknown_matter_status_rejected():
    r = validate_append(
        {"matter": {"current_status": "garbage"}, "timeline": []},
        {"type": "think"},
    )
    assert not r.ok and r.code == "unknown_matter_status"


# ---------- status_change rejections ----------

def test_status_change_from_mismatch():
    item = {
        "type": "result",
        "outcome": "finished",
        "status_change": {"from": "planning", "to": "finished"},
    }
    r = validate_append(_matter("executing"), item)
    assert not r.ok and r.code == "status_change_from_mismatch"


def test_status_change_not_allowed():
    # executing -> planning is not a legal transition at all
    item = {
        "type": "think",
        "status_change": {"from": "executing", "to": "planning"},
    }
    r = validate_append(_matter("executing"), item)
    assert not r.ok and r.code == "status_change_not_allowed"


def test_status_change_trigger_mismatch_verify_cant_finish():
    # verify cannot trigger executing -> finished (only result can)
    item = {
        "type": "verify",
        "verifications": [{"target": "x.md", "judgement": "passed", "comment": ""}],
        "status_change": {"from": "executing", "to": "finished"},
    }
    r = validate_append(_matter("executing"), item)
    assert not r.ok and r.code == "status_change_trigger_mismatch"


def test_status_change_trigger_mismatch_act_cant_pause():
    # Only think can trigger paused; act can't
    item = {
        "type": "act",
        "status_change": {"from": "executing", "to": "paused"},
    }
    r = validate_append(_matter("executing"), item)
    assert not r.ok and r.code == "status_change_trigger_mismatch"


# ---------- verify shape rejections ----------

def test_verify_missing_verifications():
    r = validate_append(_matter("planning"), {"type": "verify"})
    assert not r.ok and r.code == "verifications_required"


def test_verify_empty_verifications():
    r = validate_append(_matter("planning"), {"type": "verify", "verifications": []})
    assert not r.ok and r.code == "verifications_empty"


def test_verify_missing_target():
    item = {
        "type": "verify",
        "verifications": [{"judgement": "passed", "comment": ""}],
    }
    r = validate_append(_matter("planning"), item)
    assert not r.ok and r.code == "verification_target_required"


def test_verify_bad_judgement():
    item = {
        "type": "verify",
        "verifications": [{"target": "x.md", "judgement": "maybe"}],
    }
    r = validate_append(_matter("planning"), item)
    assert not r.ok and r.code == "invalid_judgement"


def test_verify_all_three_judgements_accepted():
    for j in ("passed", "failed", "cancelled"):
        item = {
            "type": "verify",
            "verifications": [{"target": "x.md", "judgement": j}],
        }
        assert validate_append(_matter("planning"), item).ok


# ---------- result shape rejections ----------

def test_result_without_outcome():
    item = {"type": "result", "status_change": {"from": "executing", "to": "finished"}}
    r = validate_append(_matter("executing"), item)
    assert not r.ok and r.code == "outcome_required"


def test_result_bad_outcome():
    item = {
        "type": "result",
        "outcome": "done",
        "status_change": {"from": "executing", "to": "finished"},
    }
    r = validate_append(_matter("executing"), item)
    assert not r.ok and r.code == "invalid_outcome"


def test_result_without_status_change_rejected():
    item = {"type": "result", "outcome": "finished"}
    r = validate_append(_matter("executing"), item)
    assert not r.ok and r.code == "result_without_status_change"


def test_result_cancelled_ok():
    item = {
        "type": "result",
        "outcome": "cancelled",
        "status_change": {"from": "executing", "to": "cancelled"},
    }
    assert validate_append(_matter("executing"), item) == OK
