"""Backfill scanner test for the actual `测试文章已读.index.yaml`.

Mirrors the on-disk shape the user shared verbatim: matter.owner = tangkun,
10 timeline items spanning 3 authors (zhangbo, huang, tangkun) with a mix
of file-level owner overrides, quote chains, and intra-comment mentions.

Asserts the full row-set the scanner should produce for each user — useful
both as a regression check on rule priorities and as a worked-example of
how rule 6 (`in_my_owned_matter`) interacts with the existing rules 1-5.

Quick sketch of expected reasons:

  zhangbo: i8 reply_to_my_file (quote=i7 zhangbo's) ;
           i9 in_my_matter      (zhangbo authored timeline[0]) ;
           i10 reply_to_my_file (quote=i1 zhangbo's)
  huang:   i6 owner_assigned    (item.owner=huang) ;
           i7 owner_assigned    (item.owner=huang) ;
           i8 reply_to_my_owned (quote=i7 huang's)
  tangkun: i1..i7 + i10 in_my_owned_matter (matter.owner=tangkun) — i8/i9
           are tangkun's own so self-exclusion bails

Mentions: only comments with both `created_at` and `author` make rows.
Two of the user's comments are missing created_at (i2.c "信息" and
i6.c "11") — the scanner skips them, matching production behavior.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from server.relevance_events import (
    KIND_FILE,
    KIND_MENTION,
    RelevanceEventsRepo,
)
from server.relevance_scanner import scan_all
from server.users import UserRepo


# ---------- fixtures ----------


class _StubWorkspace:
    def __init__(self, root: Path) -> None:
        self.path = root
        (root / "index").mkdir(parents=True, exist_ok=True)

    @property
    def index_dir(self) -> Path:
        return self.path / "index"


@pytest.fixture
def workspace(tmp_path):
    return _StubWorkspace(tmp_path)


@pytest.fixture
def relevance_repo(db):
    return RelevanceEventsRepo(db)


def _register_user(users: UserRepo, *, pinyin: str) -> str:
    open_id = f"ou_{pinyin}"
    users.upsert_from_feishu(
        open_id=open_id, union_id=None, name=pinyin, avatar_url="",
    )
    users.update_profile(open_id, pinyin=pinyin)
    return open_id


# ---------- the real YAML, transcribed verbatim ----------


_REAL_INDEX_YAML = """\
version: 1
matter:
  id: 测试文章已读
  title: 测试文章已读
  current_status: planning
  owner: tangkun
  created_at: '2026-04-29T11:23:24+08:00'
  updated_at: '2026-04-29T15:26:16+08:00'
timeline:
- file: discussions/testv2/测试文章已读/001_zhangbo_think_34d7af.md
  created_at: '2026-04-29T11:23:24+08:00'
  creator: zhangbo
  owner: zhangbo
  type: think
  summary: 本文梳理了智谱、通义千问等主流大模型API的传图方法。
  comments:
  - created_at: '2026-04-29T14:21:27+08:00'
    body: '111'
    mentions: [tangkun]
    author: zhangbo
  - created_at: '2026-04-29T14:22:32+08:00'
    body: '123'
    mentions: [tangkun]
    author: zhangbo
  - created_at: '2026-04-29T14:43:18+08:00'
    body: '111'
    mentions: [zhangbo]
    author: tangkun
- file: discussions/testv2/测试文章已读/002_zhangbo_think_c52dd9.md
  created_at: '2026-04-29T11:35:18+08:00'
  creator: zhangbo
  owner: zhangbo
  type: think
  summary: 系统提示发帖过程中有人提及了该用户。
  quote: discussions/testv2/测试文章已读/001_zhangbo_think_34d7af.md
  comments:
  - body: 信息
    mentions: [huang]
    author: zhangbo
  - created_at: '2026-04-29T14:40:02+08:00'
    body: '11'
    mentions: [zhangbo]
    author: tangkun
  - created_at: '2026-04-29T14:41:12+08:00'
    body: '22'
    mentions: [zhangbo]
    author: tangkun
- file: discussions/testv2/测试文章已读/003_zhangbo_think_b2bbe7.md
  created_at: '2026-04-29T11:36:16+08:00'
  creator: zhangbo
  owner: zhangbo
  type: think
  summary: 指出该发帖与用户无关。
  quote: discussions/testv2/测试文章已读/002_zhangbo_think_c52dd9.md
- file: discussions/testv2/测试文章已读/004_zhangbo_think_98ae8a.md
  created_at: '2026-04-29T11:38:20+08:00'
  creator: zhangbo
  owner: zhangbo
  type: think
  summary: 发帖人声明该帖子内容与接收者无关。
  quote: discussions/testv2/测试文章已读/003_zhangbo_think_b2bbe7.md
  comments:
  - created_at: '2026-04-29T11:39:11+08:00'
    body: '11'
    mentions: [huang]
    author: zhangbo
  - created_at: '2026-04-29T11:39:46+08:00'
    body: '22'
    mentions: [tangkun]
    author: zhangbo
  - created_at: '2026-04-29T11:51:16+08:00'
    body: '22222'
    mentions: [huang]
    author: zhangbo
  - created_at: '2026-04-29T13:36:22+08:00'
    body: '1'
    mentions: [tangkun]
    author: zhangbo
- file: discussions/testv2/测试文章已读/005_zhangbo_think_724c98.md
  created_at: '2026-04-29T13:37:10+08:00'
  creator: zhangbo
  owner: zhangbo
  type: think
  summary: 测试占位符。
  quote: discussions/testv2/测试文章已读/004_zhangbo_think_98ae8a.md
- file: discussions/testv2/测试文章已读/006_zhangbo_act_2a2cf0.md
  created_at: '2026-04-29T13:40:59+08:00'
  creator: zhangbo
  owner: huang
  type: act
  summary: 明确该事项负责人。
  quote: discussions/testv2/测试文章已读/005_zhangbo_think_724c98.md
  comments:
  - body: '11'
    mentions: [huang]
    author: zhangbo
- file: discussions/testv2/测试文章已读/007_zhangbo_act_50c94c.md
  created_at: '2026-04-29T13:43:37+08:00'
  creator: zhangbo
  owner: huang
  type: act
  summary: 指定了该事项的负责人。
  quote: discussions/testv2/测试文章已读/006_zhangbo_act_2a2cf0.md
- file: discussions/testv2/测试文章已读/008_tangkun_think_015274.md
  created_at: '2026-04-29T13:58:31+08:00'
  creator: tangkun
  owner: tangkun
  type: think
  summary: 该文件仅表达了作者希望休息放松的意愿。
  quote: discussions/testv2/测试文章已读/007_zhangbo_act_50c94c.md
- file: discussions/testv2/测试文章已读/009_tangkun_think_39d2f4.md
  created_at: '2026-04-29T14:00:41+08:00'
  creator: tangkun
  owner: tangkun
  type: think
  summary: 该文件仅包含无意义的重复数字。
  quote: discussions/testv2/测试文章已读/008_tangkun_think_015274.md
  comments:
  - created_at: '2026-04-29T14:09:15+08:00'
    body: '111'
    mentions: [tangkun]
    author: zhangbo
  - created_at: '2026-04-29T14:12:14+08:00'
    body: '222'
    mentions: [zhangbo]
    author: zhangbo
  - created_at: '2026-04-29T14:14:06+08:00'
    body: '11'
    mentions: [tangkun]
    author: zhangbo
- file: discussions/testv2/测试文章已读/010_huang_think_ec54e6.md
  created_at: '2026-04-29T15:26:16+08:00'
  creator: huang
  owner: huang
  type: think
  summary: 验证 tank 是否能正常接收消息。
  quote: discussions/testv2/测试文章已读/001_zhangbo_think_34d7af.md
"""


def _write_real_index(workspace: _StubWorkspace) -> None:
    p = workspace.index_dir / "测试文章已读.index.yaml"
    p.write_text(_REAL_INDEX_YAML, encoding="utf-8")
    # Sanity-parse it so a yaml typo in the fixture fails the test up front
    # rather than as a confusing scan_all empty result.
    parsed = yaml.safe_load(_REAL_INDEX_YAML)
    assert (parsed.get("matter") or {}).get("owner") == "tangkun"
    assert len(parsed.get("timeline") or []) == 10


# ---------- the scenario ----------


def test_real_测试文章已读_scan_writes_expected_rows(
    workspace, users, relevance_repo,
):
    _register_user(users, pinyin="zhangbo")
    _register_user(users, pinyin="huang")
    _register_user(users, pinyin="tangkun")
    _write_real_index(workspace)

    report = scan_all(
        workspace=workspace, users_repo=users, repo=relevance_repo,
    )

    assert report.matters == 1
    # 25 expected: 8 file rows for tangkun + 6 mention rows for tangkun
    #            + 3 file rows for huang   + 2 mention rows for huang
    #            + 3 file rows for zhangbo + 3 mention rows for zhangbo
    assert report.inserted == 25, (
        f"expected 25 inserts but got {report.inserted}"
    )

    # ---- tangkun: 8 file rows, all in_my_owned_matter ----
    # i8 + i9 are tangkun's own → self-exclusion
    tangkun_files = relevance_repo.file_reasons_for_matter(
        "ou_tangkun", "测试文章已读",
    )
    assert tangkun_files == {
        "001_zhangbo_think_34d7af.md": "in_my_owned_matter",
        "002_zhangbo_think_c52dd9.md": "in_my_owned_matter",
        "003_zhangbo_think_b2bbe7.md": "in_my_owned_matter",
        "004_zhangbo_think_98ae8a.md": "in_my_owned_matter",
        "005_zhangbo_think_724c98.md": "in_my_owned_matter",
        "006_zhangbo_act_2a2cf0.md":   "in_my_owned_matter",
        "007_zhangbo_act_50c94c.md":   "in_my_owned_matter",
        "010_huang_think_ec54e6.md":   "in_my_owned_matter",
    }
    assert "008_tangkun_think_015274.md" not in tangkun_files
    assert "009_tangkun_think_39d2f4.md" not in tangkun_files

    # ---- tangkun: 6 mention rows ----
    # zhangbo @ tangkun (i1.c1, i1.c2, i4.c8, i4.c10, i9.c12, i9.c14)
    tangkun_mentions = relevance_repo.unread_mention_keys_for_matter(
        "ou_tangkun", "测试文章已读",
    )
    assert tangkun_mentions == {
        ("001_zhangbo_think_34d7af.md", "2026-04-29T14:21:27+08:00", "zhangbo"),
        ("001_zhangbo_think_34d7af.md", "2026-04-29T14:22:32+08:00", "zhangbo"),
        ("004_zhangbo_think_98ae8a.md", "2026-04-29T11:39:46+08:00", "zhangbo"),
        ("004_zhangbo_think_98ae8a.md", "2026-04-29T13:36:22+08:00", "zhangbo"),
        ("009_tangkun_think_39d2f4.md", "2026-04-29T14:09:15+08:00", "zhangbo"),
        ("009_tangkun_think_39d2f4.md", "2026-04-29T14:14:06+08:00", "zhangbo"),
    }

    # ---- huang: 3 file rows ----
    # i6/i7 owner=huang → owner_assigned ; i8 quote=i7 owner=huang → reply_to_my_owned
    huang_files = relevance_repo.file_reasons_for_matter(
        "ou_huang", "测试文章已读",
    )
    assert huang_files == {
        "006_zhangbo_act_2a2cf0.md":     "owner_assigned",
        "007_zhangbo_act_50c94c.md":     "owner_assigned",
        "008_tangkun_think_015274.md":   "reply_to_my_owned",
    }

    # ---- huang: 2 mention rows ----
    # zhangbo @ huang in i4.c7 + i4.c9. (i2.c4 and i6.c11 missing created_at →
    # scanner skips them, matching prod's `if not comment_at: continue`.)
    huang_mentions = relevance_repo.unread_mention_keys_for_matter(
        "ou_huang", "测试文章已读",
    )
    assert huang_mentions == {
        ("004_zhangbo_think_98ae8a.md", "2026-04-29T11:39:11+08:00", "zhangbo"),
        ("004_zhangbo_think_98ae8a.md", "2026-04-29T11:51:16+08:00", "zhangbo"),
    }

    # ---- zhangbo: 3 file rows ----
    # i8 quote=i7 zhangbo's → reply_to_my_file
    # i9 zhangbo authored timeline[0] → in_my_matter
    # i10 quote=i1 zhangbo's → reply_to_my_file
    zhangbo_files = relevance_repo.file_reasons_for_matter(
        "ou_zhangbo", "测试文章已读",
    )
    assert zhangbo_files == {
        "008_tangkun_think_015274.md":   "reply_to_my_file",
        "009_tangkun_think_39d2f4.md":   "in_my_matter",
        "010_huang_think_ec54e6.md":     "reply_to_my_file",
    }

    # ---- zhangbo: 3 mention rows ----
    # tangkun @ zhangbo in i1.c3, i2.c5, i2.c6
    # (i9.c13 is zhangbo @ zhangbo → self-exclusion)
    zhangbo_mentions = relevance_repo.unread_mention_keys_for_matter(
        "ou_zhangbo", "测试文章已读",
    )
    assert zhangbo_mentions == {
        ("001_zhangbo_think_34d7af.md", "2026-04-29T14:43:18+08:00", "tangkun"),
        ("002_zhangbo_think_c52dd9.md", "2026-04-29T14:40:02+08:00", "tangkun"),
        ("002_zhangbo_think_c52dd9.md", "2026-04-29T14:41:12+08:00", "tangkun"),
    }

    # ---- breakdown sanity ----
    assert relevance_repo.unread_breakdown_per_matter("ou_tangkun") == {
        "测试文章已读": (8, 6),
    }
    assert relevance_repo.unread_breakdown_per_matter("ou_huang") == {
        "测试文章已读": (3, 2),
    }
    assert relevance_repo.unread_breakdown_per_matter("ou_zhangbo") == {
        "测试文章已读": (3, 3),
    }


def test_real_测试文章已读_idempotent_on_second_scan(
    workspace, users, relevance_repo,
):
    """Second scan over the same data inserts zero rows; everything skips."""
    _register_user(users, pinyin="zhangbo")
    _register_user(users, pinyin="huang")
    _register_user(users, pinyin="tangkun")
    _write_real_index(workspace)

    first = scan_all(
        workspace=workspace, users_repo=users, repo=relevance_repo,
    )
    second = scan_all(
        workspace=workspace, users_repo=users, repo=relevance_repo,
    )

    assert first.inserted == 25
    assert second.inserted == 0
    assert second.skipped >= first.inserted

    # Breakdowns unchanged.
    assert relevance_repo.unread_breakdown_per_matter("ou_tangkun") == {
        "测试文章已读": (8, 6),
    }
    assert relevance_repo.unread_breakdown_per_matter("ou_huang") == {
        "测试文章已读": (3, 2),
    }
    assert relevance_repo.unread_breakdown_per_matter("ou_zhangbo") == {
        "测试文章已读": (3, 3),
    }


def test_real_测试文章已读_dump_table_for_inspection(
    workspace, users, relevance_repo, capsys,
):
    """Diagnostic: dump every row written by scan_all so a human can sanity
    check what landed. Run with `pytest -s` to see the output."""
    _register_user(users, pinyin="zhangbo")
    _register_user(users, pinyin="huang")
    _register_user(users, pinyin="tangkun")
    _write_real_index(workspace)

    scan_all(workspace=workspace, users_repo=users, repo=relevance_repo)

    with relevance_repo._db.connect() as conn:
        rows = conn.execute(
            "SELECT user_open_id, filename, kind, reason, event_at,"
            "       actor_pinyin, read_at"
            "  FROM relevance_events"
            " WHERE matter_id = '测试文章已读'"
            " ORDER BY user_open_id, kind, event_at",
        ).fetchall()

    by_user_kind: dict[tuple[str, str], list[str]] = {}
    for r in rows:
        by_user_kind.setdefault((r["user_open_id"], r["kind"]), []).append(
            f"  {r['filename']:<40s} reason={r['reason']:<20s} "
            f"event_at={r['event_at']:<28s} actor={r['actor_pinyin']}"
        )

    print("\n[scan_all output — 测试文章已读]")
    for (uid, kind), lines in sorted(by_user_kind.items()):
        print(f"\nuser={uid} kind={kind}  ({len(lines)} rows)")
        for line in lines:
            print(line)

    # Sanity: at minimum each user has both kinds of rows.
    file_rows = sum(
        1 for r in rows if r["kind"] == KIND_FILE
    )
    mention_rows = sum(
        1 for r in rows if r["kind"] == KIND_MENTION
    )
    assert file_rows == 14   # 8 tangkun + 3 huang + 3 zhangbo
    assert mention_rows == 11  # 6 tangkun + 2 huang + 3 zhangbo
