from __future__ import annotations

import pytest

from server.read_state import ReadStateRepo


@pytest.fixture
def read_states(db):
    return ReadStateRepo(db)


def test_get_missing_returns_none(read_states):
    assert read_states.get("ou_1", "c/t") is None


def test_set_and_get_roundtrip(read_states):
    s = read_states.set("ou_1", "c/t", "003_x.md")
    assert s.last_read_post_filename == "003_x.md"
    got = read_states.get("ou_1", "c/t")
    assert got is not None and got.last_read_post_filename == "003_x.md"


def test_set_upserts(read_states):
    read_states.set("ou_1", "c/t", "001_a.md")
    read_states.set("ou_1", "c/t", "005_b.md")
    got = read_states.get("ou_1", "c/t")
    assert got is not None and got.last_read_post_filename == "005_b.md"


def test_isolation_per_user_and_thread(read_states):
    read_states.set("ou_1", "c/t", "001.md")
    read_states.set("ou_2", "c/t", "002.md")
    read_states.set("ou_1", "c/u", "003.md")
    assert read_states.get("ou_1", "c/t").last_read_post_filename == "001.md"
    assert read_states.get("ou_2", "c/t").last_read_post_filename == "002.md"
    assert read_states.get("ou_1", "c/u").last_read_post_filename == "003.md"


def test_all_for_user(read_states):
    read_states.set("ou_1", "c/t", "001.md")
    read_states.set("ou_1", "c/u", "002.md")
    read_states.set("ou_2", "c/x", "999.md")
    out = read_states.all_for_user("ou_1")
    assert out == {"c/t": "001.md", "c/u": "002.md"}
