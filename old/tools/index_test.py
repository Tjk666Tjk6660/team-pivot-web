"""Tests for INDEX file CRUD and state machine."""
from pathlib import Path

import pytest

from tools import index


class TestIndexFile:
    def test_create_new_index_for_thread(self, tmp_path: Path):
        idx_path = tmp_path / "index" / "auth-redesign-discuss.index.yaml"
        idx = index.create(
            index_path=str(idx_path),
            origin_path="discussions/enclaws/auth-redesign/",
            created="2026-04-11T10:00:00+08:00",
        )
        assert idx_path.exists()
        assert idx.origin_path == "discussions/enclaws/auth-redesign/"
        assert idx.discussions == []
        assert idx.timeline == []

    def test_load_existing_index(self, tmp_path: Path):
        idx_path = tmp_path / "index" / "x-discuss.index.yaml"
        idx_path.parent.mkdir(parents=True)
        idx_path.write_text(
            """origin_path: discussions/x/y/
created: 2026-04-11T10:00:00+08:00
last_updated: 2026-04-11T10:00:00+08:00
discussions:
  - path: discussions/x/y/
    status: open
    files:
      - path: 001_ken_proposal.md
        summary: initial proposal
        refs: []
timeline:
  - time: 2026-04-11T10:00:00+08:00
    event: ken created thread
    file: discussions/x/y/001_ken_proposal.md
""",
            encoding="utf-8",
        )
        idx = index.load(str(idx_path))
        assert idx.origin_path == "discussions/x/y/"
        assert len(idx.discussions) == 1
        assert idx.discussions[0].status == "open"

    def test_add_file_to_thread(self, tmp_path: Path):
        idx_path = tmp_path / "index" / "t-discuss.index.yaml"
        idx = index.create(
            index_path=str(idx_path),
            origin_path="discussions/t/t/",
            created="2026-04-11T10:00:00+08:00",
        )
        idx = index.add_discussion_entry(
            idx,
            discussion_path="discussions/t/t/",
            status="open",
        )
        idx = index.add_file_to_discussion(
            idx,
            discussion_path="discussions/t/t/",
            file_path="001_ken_proposal.md",
            summary="first post",
            refs=[],
        )
        assert len(idx.discussions[0].files) == 1
        assert idx.discussions[0].files[0].path == "001_ken_proposal.md"

    def test_add_timeline_entry(self, tmp_path: Path):
        idx_path = tmp_path / "index" / "t-discuss.index.yaml"
        idx = index.create(
            index_path=str(idx_path),
            origin_path="discussions/t/t/",
            created="2026-04-11T10:00:00+08:00",
        )
        idx = index.add_timeline_entry(
            idx,
            time="2026-04-11T10:05:00+08:00",
            event="ken posted proposal",
            file="discussions/t/t/001_ken_proposal.md",
            mentions=[{"user": "huangshengli", "comments": "please review"}],
        )
        assert len(idx.timeline) == 1
        assert idx.timeline[0].event == "ken posted proposal"
        assert idx.timeline[0].mentions[0]["user"] == "huangshengli"

    def test_save_roundtrip(self, tmp_path: Path):
        idx_path = tmp_path / "index" / "t-discuss.index.yaml"
        idx = index.create(
            index_path=str(idx_path),
            origin_path="discussions/t/t/",
            created="2026-04-11T10:00:00+08:00",
        )
        idx = index.add_discussion_entry(idx, "discussions/t/t/", "open")
        idx = index.add_file_to_discussion(
            idx, "discussions/t/t/", "001_ken_proposal.md", "test", []
        )
        index.save(idx)

        loaded = index.load(str(idx_path))
        assert loaded.discussions[0].files[0].path == "001_ken_proposal.md"


class TestStateMachine:
    @pytest.mark.parametrize(
        "from_state,to_state,allowed",
        [
            ("open", "concluded", True),
            ("concluded", "produced", True),
            ("open", "closed", True),
            ("open", "pending", True),
            ("pending", "open", True),
            ("concluded", "open", True),
            ("closed", "open", True),
            ("produced", "open", False),
            ("produced", "concluded", False),
            ("closed", "concluded", False),
        ],
    )
    def test_transitions(self, from_state: str, to_state: str, allowed: bool):
        assert index.can_transition(from_state, to_state) is allowed

    def test_update_status_writes_to_discussion_entry(self, tmp_path: Path):
        idx_path = tmp_path / "index" / "t-discuss.index.yaml"
        idx = index.create(str(idx_path), "discussions/t/t/", "2026-04-11T10:00:00+08:00")
        idx = index.add_discussion_entry(idx, "discussions/t/t/", "open")
        idx = index.set_status(idx, "discussions/t/t/", "concluded")
        assert idx.discussions[0].status == "concluded"

    def test_update_status_rejects_illegal_transition(self, tmp_path: Path):
        idx_path = tmp_path / "index" / "t-discuss.index.yaml"
        idx = index.create(str(idx_path), "discussions/t/t/", "2026-04-11T10:00:00+08:00")
        idx = index.add_discussion_entry(idx, "discussions/t/t/", "produced")
        with pytest.raises(index.StateTransitionError):
            index.set_status(idx, "discussions/t/t/", "open")
