"""End-to-end tests for publish_matter_annotation (Phase 6.1).

Covers the slice from public function call → matter index disk write →
event emit → notifier dispatch. Stakeholder resolution itself is unit-
tested in test_publish_helpers.py; here we verify the wiring.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from server.events import (
    TOPIC_ANNOTATION_APPENDED,
    Event,
    clear_subscribers,
    subscribe,
)
from server.external_bindings import ExternalBindingRepo
from server.matter_index import (
    create_matter_index,
    matter_index_path,
    read_matter_index,
)
from server.matter_index import ValidationError
from server.pivot_users import PivotUserRepo
from server.publish import publish_matter_annotation


# ---------- fixtures ----------


class _WorkspaceStub:
    def __init__(self, root: Path) -> None:
        self.path = root
        self.discussions_dir = root / "discussions"
        self.index_dir = root / "index"

    @contextmanager
    def write_session(self, **_: object):
        self.discussions_dir.mkdir(parents=True, exist_ok=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        yield


class _RecordingNotifier:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def notify_annotation(self, **kwargs: object) -> None:
        self.calls.append(("annotation", dict(kwargs)))

    # Other Notifier methods need to exist for type-compat with code paths
    # that *might* be triggered. Annotation publish doesn't call them, but
    # keep stubs to avoid AttributeError if implementation drifts.
    def __getattr__(self, _name: str):
        return lambda **kw: None


@pytest.fixture(autouse=True)
def _isolate_event_bus():
    clear_subscribers()
    yield
    clear_subscribers()


@pytest.fixture
def event_bucket() -> list[Event]:
    bucket: list[Event] = []
    subscribe(bucket.append)
    return bucket


@pytest.fixture
def workspace(tmp_path):
    return _WorkspaceStub(tmp_path)


@pytest.fixture
def repos(db):
    return PivotUserRepo(db), ExternalBindingRepo(db)


def _make_user(pivot_users, bindings, *, pinyin: str, with_feishu: bool = True):
    u = pivot_users.create(
        display_name=pinyin, pinyin=pinyin, email=None, avatar_url="",
        role="member",
    )
    if with_feishu:
        oid = f"ou_{pinyin}_000000000000"
        bindings.bind(
            pivot_user_id=u.id, provider="feishu",
            external_id=oid, external_union_id=None, raw_profile_json=None,
        )
        return u, oid
    return u, u.id


def _seed_matter(workspace: _WorkspaceStub) -> tuple[str, str]:
    """Bootstrap a matter with one think file. Returns (matter_id, target_file).

    matter.creator = "alice", matter.owner = "bob", file.creator = "alice".
    Distinct roles so stakeholder resolution test surfaces all three slots.
    """
    matter_id = "m-x"
    target_file = "discussions/cat/m-x/001_alice_think.md"
    path = matter_index_path(workspace.index_dir, matter_id)
    create_matter_index(
        path,
        matter_id=matter_id,
        title="Annotation Test Matter",
        initial_item={
            "file": target_file,
            "creator": "alice",
            "type": "think",
            "summary": "the file under evaluation",
        },
        now_iso="2026-04-23T10:00:00+08:00",
        matter_owner="bob",
    )
    return matter_id, target_file


# ---------- happy path ----------


def test_publish_annotation_writes_yaml_and_emits_event(
    workspace, repos, event_bucket,
):
    pivot_users, bindings = repos
    actor, _ = _make_user(pivot_users, bindings, pinyin="actor_zz")
    matter_id, target_file = _seed_matter(workspace)

    notifier = _RecordingNotifier()
    publish_matter_annotation(
        workspace, actor,
        matter_id=matter_id, target_file=target_file,
        type="evaluation", body="结构清楚",
        notifier=notifier, pivot_users=pivot_users, bindings=bindings,
    )

    # ---- yaml: annotation in canonical shape, author + created_at injected ----
    data = read_matter_index(matter_index_path(workspace.index_dir, matter_id))
    annotations = data["timeline"][0]["annotations"]
    assert len(annotations) == 1
    a = annotations[0]
    assert a["type"] == "evaluation"
    assert a["body"] == "结构清楚"
    assert a["author"] == "actor_zz"
    assert "created_at" in a

    # ---- emit: payload carries stakeholder_open_ids resolved upstream ----
    annotation_events = [e for e in event_bucket if e.topic == TOPIC_ANNOTATION_APPENDED]
    assert len(annotation_events) == 1
    payload = annotation_events[0].payload or {}
    assert payload["target_file"] == target_file
    assert payload["type"] == "evaluation"
    assert payload["body"] == "结构清楚"
    assert "stakeholder_open_ids" in payload


def test_publish_annotation_resolves_three_role_stakeholders(
    workspace, repos, event_bucket,
):
    """Distinct file.creator / matter.owner / matter.creator → all three
    show up in stakeholder_open_ids (ordered + deduped per Phase 3 helper)."""
    pivot_users, bindings = repos
    _alice, alice_oid = _make_user(pivot_users, bindings, pinyin="alice")  # file.creator + matter.creator
    _bob, bob_oid = _make_user(pivot_users, bindings, pinyin="bob")        # matter.owner
    actor, _ = _make_user(pivot_users, bindings, pinyin="actor_zz")
    matter_id, target_file = _seed_matter(workspace)

    publish_matter_annotation(
        workspace, actor,
        matter_id=matter_id, target_file=target_file,
        type="evaluation", body="ok",
        pivot_users=pivot_users, bindings=bindings,
    )

    payload = next(
        e for e in event_bucket if e.topic == TOPIC_ANNOTATION_APPENDED
    ).payload
    stakeholders = payload["stakeholder_open_ids"]
    # alice plays both file.creator and matter.creator → dedup to one entry.
    # Order is helper-deterministic: file.creator, matter.owner, matter.creator.
    assert stakeholders == [alice_oid, bob_oid]


def test_publish_annotation_excludes_actor_from_stakeholders(
    workspace, repos, event_bucket,
):
    """Actor == matter.owner → matter.owner slot drops; only the other
    two roles (deduped) remain."""
    pivot_users, bindings = repos
    _alice, alice_oid = _make_user(pivot_users, bindings, pinyin="alice")  # creator + matter.creator
    bob, _bob_oid = _make_user(pivot_users, bindings, pinyin="bob")        # actor + matter.owner
    matter_id, target_file = _seed_matter(workspace)

    publish_matter_annotation(
        workspace, bob,
        matter_id=matter_id, target_file=target_file,
        type="evaluation", body="self-eval scenario",
        pivot_users=pivot_users, bindings=bindings,
    )

    payload = next(
        e for e in event_bucket if e.topic == TOPIC_ANNOTATION_APPENDED
    ).payload
    assert payload["stakeholder_open_ids"] == [alice_oid]


# ---------- notifier wiring ----------


def test_publish_annotation_calls_notifier_with_stakeholders(
    workspace, repos,
):
    pivot_users, bindings = repos
    _alice, alice_oid = _make_user(pivot_users, bindings, pinyin="alice")
    _bob, bob_oid = _make_user(pivot_users, bindings, pinyin="bob")
    actor, _ = _make_user(pivot_users, bindings, pinyin="actor_zz")
    matter_id, target_file = _seed_matter(workspace)

    notifier = _RecordingNotifier()
    publish_matter_annotation(
        workspace, actor,
        matter_id=matter_id, target_file=target_file,
        type="evaluation", body="去看一下",
        notifier=notifier, pivot_users=pivot_users, bindings=bindings,
    )

    assert len(notifier.calls) == 1
    name, kw = notifier.calls[0]
    assert name == "annotation"
    # DM-only path: stakeholders flow as the only recipient list (no group
    # broadcast / no @-target list).
    assert set(kw["stakeholder_open_ids"]) == {alice_oid, bob_oid}
    assert kw["author_name"] == actor.name
    assert kw["annotation_body"] == "去看一下"
    assert kw["annotation_type"] == "evaluation"


def test_publish_annotation_skips_notifier_when_no_stakeholders(
    workspace, repos,
):
    """Solo author = file.creator = matter.owner = matter.creator (and
    actor). All four slots collapse to actor → stakeholder list is empty
    → notifier.notify_annotation MUST NOT fire (avoid empty DMs)."""
    pivot_users, bindings = repos
    actor, _ = _make_user(pivot_users, bindings, pinyin="alice")
    # Seed a matter where alice is the sole human in every role.
    matter_id = "m-solo"
    target_file = "discussions/cat/m-solo/001_alice_think.md"
    path = matter_index_path(workspace.index_dir, matter_id)
    create_matter_index(
        path,
        matter_id=matter_id, title="Solo",
        initial_item={
            "file": target_file, "creator": "alice",
            "type": "think", "summary": "x",
        },
        now_iso="2026-04-23T10:00:00+08:00",
        matter_owner="alice",
    )

    notifier = _RecordingNotifier()
    publish_matter_annotation(
        workspace, actor,
        matter_id=matter_id, target_file=target_file,
        type="evaluation", body="self-eval",
        notifier=notifier, pivot_users=pivot_users, bindings=bindings,
    )

    assert notifier.calls == []


# ---------- validator gate ----------


def test_publish_annotation_writer_rejects_unknown_type(
    workspace, repos,
):
    """publish-side validator gate triggers BEFORE any disk write —
    rejecting an out-of-whitelist ``type`` raises ValidationError and
    leaves the matter index untouched (no half-written entry)."""
    pivot_users, bindings = repos
    actor, _ = _make_user(pivot_users, bindings, pinyin="actor_zz")
    matter_id, target_file = _seed_matter(workspace)

    with pytest.raises(ValidationError):
        publish_matter_annotation(
            workspace, actor,
            matter_id=matter_id, target_file=target_file,
            type="follow_up_question",  # not in v1 whitelist
            body="x",
            pivot_users=pivot_users, bindings=bindings,
        )

    data = read_matter_index(matter_index_path(workspace.index_dir, matter_id))
    assert "annotations" not in data["timeline"][0]


def test_publish_annotation_writer_rejects_empty_body(
    workspace, repos,
):
    """Empty body is gated on the publish side (Pydantic mirrors this on
    the API side; both are real because direct callers can bypass the
    HTTP layer)."""
    pivot_users, bindings = repos
    actor, _ = _make_user(pivot_users, bindings, pinyin="actor_zz")
    matter_id, target_file = _seed_matter(workspace)

    with pytest.raises(ValidationError):
        publish_matter_annotation(
            workspace, actor,
            matter_id=matter_id, target_file=target_file,
            type="evaluation", body="",
            pivot_users=pivot_users, bindings=bindings,
        )
