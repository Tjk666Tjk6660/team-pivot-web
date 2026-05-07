from __future__ import annotations

import pytest

from server.matter_validator import (
    ANNOTATION_BODY_MAX,
    OK,
    validate_annotation,
    validate_append,
)


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


# ---------- annotations (Phase 6) ----------


def test_annotation_evaluation_ok():
    r = validate_annotation({"type": "evaluation", "body": "好"})
    assert r == OK


def test_annotation_unknown_type_rejected():
    r = validate_annotation({"type": "follow_up_question", "body": "good?"})
    assert not r.ok and r.code == "unknown_annotation_type"
    assert r.field == "type"


def test_annotation_missing_type_rejected():
    r = validate_annotation({"body": "good"})
    assert not r.ok and r.code == "type_missing"


def test_annotation_empty_body_rejected():
    r = validate_annotation({"type": "evaluation", "body": ""})
    assert not r.ok and r.code == "body_too_short"


def test_annotation_missing_body_rejected():
    r = validate_annotation({"type": "evaluation"})
    assert not r.ok and r.code == "body_required"


def test_annotation_overlong_body_rejected():
    r = validate_annotation({
        "type": "evaluation",
        "body": "x" * (ANNOTATION_BODY_MAX + 1),
    })
    assert not r.ok and r.code == "body_too_long"


@pytest.mark.parametrize(
    "field",
    ["weight", "rating", "dimension", "sentiment", "score_delta"],
)
def test_annotation_derived_field_rejected(field):
    """Each AI-derived field must surface as derived_field_not_allowed.
    These are intentionally NOT client-writable in v1 to prevent schema
    anchoring before the AI scoring layer is designed."""
    r = validate_annotation({"type": "evaluation", "body": "x", field: 1})
    assert not r.ok
    assert r.code == "derived_field_not_allowed"
    assert r.field == field


def test_annotation_non_dict_rejected():
    """Defensive belt for callers that hand us a non-dict (e.g. a list
    accidentally passed through MCP) — return a precise error instead of
    KeyError."""
    r = validate_annotation(["not", "a", "dict"])  # type: ignore[arg-type]
    assert not r.ok and r.code == "annotation_not_object"


# ---------- invalidation events (P1) ------------------------------------

# Helpers for event tests
def _matter_with_act(*, status: str = "executing", invalidated: bool = False,
                     creator: str = "dengke",
                     act_file: str = "discussions/m/002_d_act_b.md") -> dict:
    """Matter with one act file (creator = `creator`). Optionally pre-invalidated."""
    act_item = {"file": act_file, "creator": creator, "type": "act"}
    if invalidated:
        act_item["invalidated"] = True
        act_item["invalidated_at"] = "2026-04-26T10:00:00+08:00"
        act_item["invalidated_reason"] = "misposted"
        act_item["invalidated_by"] = creator
    return {
        "matter": {"current_status": status},
        "timeline": [act_item],
    }


def _event(*, creator: str = "dengke", quote: str = "discussions/m/002_d_act_b.md",
           reason: str = "misposted") -> dict:
    return {"creator": creator, "quote": quote, "reason": reason}


# Happy path
def test_invalidate_event_by_author_ok():
    index = _matter_with_act()
    assert validate_append(index, _event(reason="misposted")) == OK


def test_restore_event_when_invalidated_ok():
    index = _matter_with_act(invalidated=True)
    assert validate_append(index, _event(reason="restored")) == OK


# Rule 1: creator must equal target's creator
def test_event_creator_mismatch_rejected():
    index = _matter_with_act(creator="dengke")
    r = validate_append(index, _event(creator="alice"))
    assert not r.ok and r.code == "event_creator_mismatch"


# Rule 2: already invalidated cannot be invalidated again
def test_event_already_invalidated_rejected():
    index = _matter_with_act(invalidated=True)
    r = validate_append(index, _event(reason="misposted"))
    assert not r.ok and r.code == "target_already_invalidated"


# Rule 3: not invalidated cannot be restored
def test_event_target_not_invalidated_rejected():
    index = _matter_with_act(invalidated=False)
    r = validate_append(index, _event(reason="restored"))
    assert not r.ok and r.code == "target_not_invalidated"


# Rule 4: quote cannot point to another event item
# (Implicitly enforced: event items have no `file` field, so by-file lookup
# fails and falls through to target_not_found.)
def test_event_quote_to_event_item_rejected():
    """Events have no `file`, so quoting an event resolves to target_not_found."""
    index = {
        "matter": {"current_status": "executing"},
        "timeline": [
            {"file": "discussions/m/002_d_act_b.md", "creator": "dengke", "type": "act"},
            # An invalidation event entry (no `file`, has `reason`)
            {"creator": "dengke", "quote": "discussions/m/002_d_act_b.md",
             "reason": "misposted", "created_at": "2026-04-26T10:00:00+08:00"},
        ],
    }
    # Try to invalidate "the event" — there's no path to address it; we'd have
    # to fabricate one. Confirm any non-file path falls into target_not_found.
    r = validate_append(index, _event(quote="some/non-file/path.md"))
    assert not r.ok and r.code == "target_not_found"


# Rule 5: cross-matter quote rejected (target not in this matter's timeline)
def test_event_cross_matter_quote_rejected():
    index = _matter_with_act()
    r = validate_append(index, _event(quote="discussions/other-matter/001.md"))
    assert not r.ok and r.code == "target_not_found"


# Rule 6: comment cannot be invalidated (comments are nested, never top-level files)
def test_event_quote_to_comment_path_rejected():
    """Comments live inside file.comments[], never as top-level entries with
    a `file` field. Any comment-shaped path naturally fails by-file lookup."""
    index = _matter_with_act()
    r = validate_append(index, _event(quote="discussions/m/002_d_act_b.md#comment-1"))
    assert not r.ok and r.code == "target_not_found"


# Reason validation
def test_event_invalid_reason_rejected():
    index = _matter_with_act()
    r = validate_append(index, _event(reason="bogus"))
    assert not r.ok and r.code == "invalid_reason"


def test_event_missing_quote_rejected():
    index = _matter_with_act()
    item = {"creator": "dengke", "reason": "misposted"}  # no quote
    r = validate_append(index, item)
    assert not r.ok and r.code == "quote_required"


def test_event_missing_creator_rejected():
    index = _matter_with_act()
    item = {"quote": "discussions/m/002_d_act_b.md", "reason": "misposted"}
    r = validate_append(index, item)
    assert not r.ok and r.code == "creator_required"


# §5.3 reference block: file's quote/refer cannot target an invalidated file
def test_new_file_quoting_invalidated_file_rejected():
    """A new file item's `quote` cannot point to an already-invalidated file."""
    index = _matter_with_act(invalidated=True)
    new_act = {
        "type": "act",
        "summary": "继续推进",
        "quote": "discussions/m/002_d_act_b.md",  # 这条已失效
    }
    r = validate_append(index, new_act)
    assert not r.ok and r.code == "quote_target_invalidated"


def test_new_file_referring_invalidated_file_rejected():
    """A new file item's `refer` list cannot include an already-invalidated file."""
    index = _matter_with_act(invalidated=True)
    new_think = {
        "type": "think",
        "summary": "复盘",
        "refer": ["discussions/m/002_d_act_b.md"],  # 已失效
    }
    # Note: matter is executing → think allowed
    r = validate_append(index, new_think)
    assert not r.ok and r.code == "refer_target_invalidated"


def test_new_file_quoting_non_invalidated_file_ok():
    """Sanity: §5.3 only blocks invalidated targets; normal quote still OK."""
    index = _matter_with_act(invalidated=False)
    new_act = {
        "type": "act",
        "summary": "继续",
        "quote": "discussions/m/002_d_act_b.md",
    }
    assert validate_append(index, new_act) == OK
