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
    # Target whitelisted via refer (cross-matter); validator trusts client.
    item = {
        "type": "verify",
        "refer": ["discussions/other/001_u_act_a.md"],
        "verifications": [
            {"target": "discussions/other/001_u_act_a.md",
             "judgement": "passed", "comment": ""},
        ],
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
            "refer": ["x.md"],
            "verifications": [{"target": "x.md", "judgement": j}],
        }
        assert validate_append(_matter("planning"), item).ok


# ---------- verify.target whitelist (P4) ----------


def _matter_with_timeline(status: str, timeline: list[dict]) -> dict:
    return {"matter": {"current_status": status}, "timeline": timeline}


def test_verify_target_is_local_act_ok():
    index = _matter_with_timeline("planning", [
        {"file": "discussions/m/001_u_act_a.md", "type": "act"},
    ])
    item = {
        "type": "verify",
        "verifications": [{"target": "discussions/m/001_u_act_a.md",
                           "judgement": "passed", "comment": ""}],
    }
    assert validate_append(index, item) == OK


def test_verify_target_local_but_not_act_rejected():
    index = _matter_with_timeline("planning", [
        {"file": "discussions/m/001_u_think_a.md", "type": "think"},
    ])
    item = {
        "type": "verify",
        "verifications": [{"target": "discussions/m/001_u_think_a.md",
                           "judgement": "passed", "comment": ""}],
    }
    r = validate_append(index, item)
    assert not r.ok and r.code == "verification_target_not_act"


def test_verify_target_not_in_timeline_and_not_refer_rejected():
    index = _matter_with_timeline("planning", [
        {"file": "discussions/m/001_u_act_a.md", "type": "act"},
    ])
    item = {
        "type": "verify",
        "verifications": [{"target": "discussions/other/999_unknown.md",
                           "judgement": "passed", "comment": ""}],
    }
    r = validate_append(index, item)
    assert not r.ok and r.code == "verification_target_not_found"


def test_verify_target_via_refer_whitelist_ok():
    # Cross-matter target listed in refer is trusted by the pure validator.
    index = _matter_with_timeline("planning", [
        {"file": "discussions/m/001_u_act_a.md", "type": "act"},
    ])
    item = {
        "type": "verify",
        "refer": ["discussions/other/123_u_act_x.md"],
        "verifications": [{"target": "discussions/other/123_u_act_x.md",
                           "judgement": "passed", "comment": ""}],
    }
    assert validate_append(index, item) == OK


def test_verify_multiple_targets_one_bad_rejected():
    index = _matter_with_timeline("planning", [
        {"file": "discussions/m/001_u_act_a.md", "type": "act"},
        {"file": "discussions/m/002_u_think_b.md", "type": "think"},
    ])
    item = {
        "type": "verify",
        "verifications": [
            {"target": "discussions/m/001_u_act_a.md",
             "judgement": "passed", "comment": ""},
            {"target": "discussions/m/002_u_think_b.md",
             "judgement": "failed", "comment": ""},
        ],
    }
    r = validate_append(index, item)
    assert not r.ok and r.code == "verification_target_not_act"
    assert r.field == "verifications[1].target"


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


# ---------- P4.7 verifications_received: client cannot author ----------


def test_client_cannot_set_verifications_received_on_act():
    """I3: clients must never write verifications_received directly. The
    field is server-derived from verify items writing back to acts."""
    item = {
        "type": "act",
        "summary": "x",
        "verifications_received": [
            {
                "verify_file": "discussions/m/003_u_verify.md",
                "verified_at": "2026-04-23T11:00:00+08:00",
                "verified_by": "u",
                "judgement": "passed",
                "comment": "fake",
            }
        ],
    }
    r = validate_append(_matter("planning"), item)
    assert not r.ok
    assert r.code == "field_not_writable"
    assert r.field == "verifications_received"


def test_client_cannot_set_verifications_received_on_any_type():
    """I2/I3: even if the type would normally allow the field semantically,
    the validator rejects it because reverse-write is server-side only."""
    for doc_type in ("think", "act", "verify", "insight"):
        item: dict = {
            "type": doc_type,
            "summary": "x",
            "verifications_received": [],
        }
        if doc_type == "verify":
            item["verifications"] = [
                {"target": "discussions/m/001_u_act_a.md",
                 "judgement": "passed", "comment": ""}
            ]
            item["refer"] = ["discussions/m/001_u_act_a.md"]
        status = "planning" if doc_type != "insight" else "finished"
        r = validate_append(_matter(status), item)
        assert not r.ok and r.code == "field_not_writable", (
            f"type={doc_type} should be rejected for verifications_received, "
            f"got {r}"
        )
