import pytest

from server.auth.auto_pinyin import assign_pinyin
from server.db import Database
from server.pivot_users import PivotUserRepo


def _repo(tmp_path) -> PivotUserRepo:
    return PivotUserRepo(Database(tmp_path / "test.db"))


def test_assign_pinyin_from_chinese_name(tmp_path):
    repo = _repo(tmp_path)
    assert assign_pinyin(name="张三", open_id="ou_abc", repo=repo) == "zhangsan"


def test_assign_pinyin_pass_through_english(tmp_path):
    repo = _repo(tmp_path)
    assert assign_pinyin(name="Alice", open_id="ou_abc", repo=repo) == "alice"


def test_assign_pinyin_appends_suffix_on_collision(tmp_path):
    repo = _repo(tmp_path)
    repo.create(
        display_name="Existing", pinyin="alice", email=None,
        avatar_url="", role="member",
    )
    assert assign_pinyin(name="Alice", open_id="ou_xyz", repo=repo) == "alice_2"


def test_assign_pinyin_skips_taken_suffixes(tmp_path):
    repo = _repo(tmp_path)
    for p in ("alice", "alice_2", "alice_3"):
        repo.create(
            display_name=p, pinyin=p, email=None, avatar_url="", role="member",
        )
    assert assign_pinyin(name="Alice", open_id="ou_xyz", repo=repo) == "alice_4"


def test_assign_pinyin_falls_back_for_invalid_name(tmp_path):
    repo = _repo(tmp_path)
    # Empty / whitespace / chars that produce empty pinyin → fallback to user_<openid8>
    assert assign_pinyin(name="", open_id="ou_abc12345", repo=repo) == "user_ou_abc12"


def test_assign_pinyin_falls_back_when_pinyin_starts_with_digit(tmp_path):
    repo = _repo(tmp_path)
    # PINYIN_RE_PATTERN requires first char a-z; "100" → fallback
    result = assign_pinyin(name="100号", open_id="ou_abcdefgh", repo=repo)
    assert result.startswith("user_")
