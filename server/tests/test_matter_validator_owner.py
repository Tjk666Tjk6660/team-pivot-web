from __future__ import annotations

from server.matter_validator import OWNER_CHANGE_REASON_MAX, validate_append


def _index(*, owner: str | None = None, status: str = "planning", timeline: list | None = None) -> dict:
    matter: dict = {"current_status": status}
    if owner is not None:
        matter["owner"] = owner
    return {"matter": matter, "timeline": timeline or []}


def _oc(**overrides) -> dict:
    base = {
        "type": "owner_change",
        "actor": "alice",
        "from_owner": "alice",
        "to_owner": "bob",
        "reason": "transfer",
    }
    base.update(overrides)
    return base


# ── Basic shape ────────────────────────────────────────────────────


def test_owner_change_happy_path():
    r = validate_append(_index(owner="alice"), _oc())
    assert r.ok, r


def test_owner_change_actor_required():
    r = validate_append(_index(owner="alice"), _oc(actor=""))
    assert not r.ok and r.code == "actor_required"


def test_owner_change_reason_required():
    r = validate_append(_index(owner="alice"), _oc(reason=""))
    assert not r.ok and r.code == "reason_required"


def test_owner_change_reason_whitespace_only():
    r = validate_append(_index(owner="alice"), _oc(reason="   "))
    assert not r.ok and r.code == "reason_required"


def test_owner_change_reason_too_long():
    r = validate_append(_index(owner="alice"), _oc(reason="x" * (OWNER_CHANGE_REASON_MAX + 1)))
    assert not r.ok and r.code == "reason_too_long"


def test_owner_change_reason_at_max_ok():
    r = validate_append(_index(owner="alice"), _oc(reason="x" * OWNER_CHANGE_REASON_MAX))
    assert r.ok


def test_owner_change_to_owner_required():
    r = validate_append(_index(owner="alice"), _oc(to_owner=""))
    assert not r.ok and r.code == "to_owner_required"


def test_owner_change_to_owner_equals_from_owner():
    r = validate_append(_index(owner="alice"), _oc(from_owner="alice", to_owner="alice"))
    assert not r.ok and r.code == "owner_unchanged"


def test_owner_change_from_owner_mismatch_stale():
    r = validate_append(_index(owner="alice"), _oc(from_owner="charlie", to_owner="bob"))
    assert not r.ok and r.code == "owner_stale"


# ── Unassigned matter (design §6.1) ─────────────────────────────────


def test_owner_change_when_matter_unassigned_from_null_ok():
    # matter.owner is None; from_owner=None should be valid.
    r = validate_append(_index(owner=None), _oc(from_owner=None, to_owner="bob"))
    assert r.ok, r


def test_owner_change_when_matter_unassigned_from_not_null_stale():
    # matter.owner is None but client thinks it's "alice" → stale.
    r = validate_append(_index(owner=None), _oc(from_owner="alice", to_owner="bob"))
    assert not r.ok and r.code == "owner_stale"


def test_owner_change_when_matter_owner_set_from_null_stale():
    # matter.owner is "alice" but client sends from_owner=None → stale.
    r = validate_append(_index(owner="alice"), _oc(from_owner=None, to_owner="bob"))
    assert not r.ok and r.code == "owner_stale"


def test_owner_change_unassigned_to_owner_required():
    # Even with from_owner=None, to_owner is required.
    r = validate_append(_index(owner=None), _oc(from_owner=None, to_owner=""))
    assert not r.ok and r.code == "to_owner_required"


# ── Combined status_change (design §6.2 / §2.5) ────────────────────


def test_owner_change_with_status_planning_to_executing_ok():
    r = validate_append(
        _index(owner="alice", status="planning"),
        _oc(status_change={"from": "planning", "to": "executing"}),
    )
    assert r.ok, r


def test_owner_change_unassigned_with_status_planning_to_executing_ok():
    r = validate_append(
        _index(owner=None, status="planning"),
        _oc(from_owner=None, status_change={"from": "planning", "to": "executing"}),
    )
    assert r.ok, r


def test_owner_change_with_status_executing_to_paused_rejected():
    r = validate_append(
        _index(owner="alice", status="executing"),
        _oc(status_change={"from": "executing", "to": "paused"}),
    )
    assert not r.ok and r.code == "status_change_not_allowed_by_event"


def test_owner_change_with_status_executing_to_finished_rejected():
    r = validate_append(
        _index(owner="alice", status="executing"),
        _oc(status_change={"from": "executing", "to": "finished"}),
    )
    assert not r.ok and r.code == "status_change_not_allowed_by_event"


def test_owner_change_with_status_finished_to_reviewed_rejected():
    r = validate_append(
        _index(owner="alice", status="finished"),
        _oc(status_change={"from": "finished", "to": "reviewed"}),
    )
    assert not r.ok and r.code == "status_change_not_allowed_by_event"


def test_owner_change_with_status_paused_to_executing_rejected():
    r = validate_append(
        _index(owner="alice", status="paused"),
        _oc(status_change={"from": "paused", "to": "executing"}),
    )
    assert not r.ok and r.code == "status_change_not_allowed_by_event"


def test_owner_change_with_status_from_mismatch_stale():
    # current_status is planning but client claims executing
    r = validate_append(
        _index(owner="alice", status="planning"),
        _oc(status_change={"from": "executing", "to": "paused"}),
    )
    assert not r.ok and r.code == "status_stale"


def test_owner_change_with_invalid_transition():
    # planning → reviewed is not in ALLOWED_TRANSITIONS
    r = validate_append(
        _index(owner="alice", status="planning"),
        _oc(status_change={"from": "planning", "to": "reviewed"}),
    )
    assert not r.ok and r.code == "status_change_not_allowed"


# ── Reviewed / cancelled state (design §4.1: allowed without status_change) ─


def test_owner_change_in_reviewed_state_without_status_change_ok():
    r = validate_append(_index(owner="alice", status="reviewed"), _oc())
    assert r.ok, r


def test_owner_change_in_cancelled_state_without_status_change_ok():
    r = validate_append(_index(owner="alice", status="cancelled"), _oc())
    assert r.ok, r


def test_owner_change_in_reviewed_with_status_change_rejected():
    # reviewed has no allowed outgoing transitions
    r = validate_append(
        _index(owner="alice", status="reviewed"),
        _oc(status_change={"from": "reviewed", "to": "planning"}),
    )
    assert not r.ok and r.code == "status_change_not_allowed"


# ── Existing file-type validation must still work (no regression) ──


def test_existing_think_validation_unaffected():
    item = {"type": "think", "summary": "x"}
    r = validate_append(_index(owner="alice", status="planning"), item)
    assert r.ok, r


def test_existing_unknown_type_still_rejected():
    item = {"type": "totally_made_up", "summary": "x"}
    r = validate_append(_index(owner="alice", status="planning"), item)
    assert not r.ok and r.code == "unknown_type"
