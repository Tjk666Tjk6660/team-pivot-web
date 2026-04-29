from __future__ import annotations

import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from server.file_reads import FileReadRepo


@pytest.fixture
def file_reads(db):
    return FileReadRepo(db)


def test_mark_first_time_records_now(file_reads):
    before = time.time()
    entry = file_reads.mark("ou_a", "m-x", "01-decision.md")
    after = time.time()
    assert entry.open_id == "ou_a"
    assert before <= entry.first_read_at <= after


def test_mark_is_idempotent_keeps_first_time(file_reads):
    first = file_reads.mark("ou_a", "m-x", "01.md")
    time.sleep(0.01)
    second = file_reads.mark("ou_a", "m-x", "01.md")
    assert second.first_read_at == first.first_read_at


def test_mark_isolates_users(file_reads):
    a = file_reads.mark("ou_a", "m-x", "01.md")
    b = file_reads.mark("ou_b", "m-x", "01.md")
    readers = file_reads.list_for_matter("m-x")["01.md"]
    open_ids = {r.open_id for r in readers}
    assert open_ids == {"ou_a", "ou_b"}
    # both retain their own first_read_at (b later than a)
    by_id = {r.open_id: r.first_read_at for r in readers}
    assert by_id["ou_a"] == a.first_read_at
    assert by_id["ou_b"] == b.first_read_at


def test_mark_isolates_files(file_reads):
    file_reads.mark("ou_a", "m-x", "01.md")
    file_reads.mark("ou_a", "m-x", "02.md")
    out = file_reads.list_for_matter("m-x")
    assert set(out.keys()) == {"01.md", "02.md"}
    assert [r.open_id for r in out["01.md"]] == ["ou_a"]
    assert [r.open_id for r in out["02.md"]] == ["ou_a"]


def test_mark_isolates_matters(file_reads):
    file_reads.mark("ou_a", "m-x", "01.md")
    file_reads.mark("ou_a", "m-y", "01.md")
    x = file_reads.list_for_matter("m-x")
    y = file_reads.list_for_matter("m-y")
    assert "01.md" in x and "01.md" in y
    # different matters tracked independently — list_for_matter never crosses
    assert len(x["01.md"]) == 1
    assert len(y["01.md"]) == 1


def test_list_for_matter_orders_by_first_read_at(file_reads):
    file_reads.mark("ou_a", "m-x", "01.md")
    time.sleep(0.01)
    file_reads.mark("ou_b", "m-x", "01.md")
    time.sleep(0.01)
    file_reads.mark("ou_c", "m-x", "01.md")
    readers = file_reads.list_for_matter("m-x")["01.md"]
    assert [r.open_id for r in readers] == ["ou_a", "ou_b", "ou_c"]


def test_list_for_matter_empty(file_reads):
    assert file_reads.list_for_matter("nonexistent") == {}


# ---------- concurrency / atomicity ----------


def test_concurrent_mark_same_key_yields_one_row_and_consistent_timestamp(
    file_reads,
):
    """N threads racing on the same (user, matter, file) primary key must:
    1) leave exactly one row in the table (PK + INSERT OR IGNORE),
    2) all return the SAME first_read_at (the winner's),
    3) never raise (no SQLITE_BUSY / locked errors)."""
    N = 32

    def worker():
        return file_reads.mark("ou_a", "m-x", "01.md")

    with ThreadPoolExecutor(max_workers=N) as pool:
        futures = [pool.submit(worker) for _ in range(N)]
        entries = [f.result() for f in as_completed(futures)]

    assert len(entries) == N
    timestamps = {e.first_read_at for e in entries}
    assert len(timestamps) == 1, (
        f"expected one consistent first_read_at across all racers, got {timestamps}"
    )

    readers = file_reads.list_for_matter("m-x")["01.md"]
    assert len(readers) == 1
    assert readers[0].open_id == "ou_a"
    assert readers[0].first_read_at == next(iter(timestamps))


def test_concurrent_mark_distinct_keys_all_persist(file_reads):
    """N threads writing distinct PKs must all land — no rows lost to lock
    contention or transaction collisions."""
    N = 32

    def worker(i: int):
        # mix distinct dimensions so we hit varied PK collisions
        user = f"ou_{i % 4}"
        matter = f"m-{i % 3}"
        filename = f"{i:03d}.md"
        return file_reads.mark(user, matter, filename)

    with ThreadPoolExecutor(max_workers=N) as pool:
        futures = [pool.submit(worker, i) for i in range(N)]
        for f in as_completed(futures):
            f.result()  # raises if the worker hit SQLITE_BUSY/locked

    # All N rows landed (each filename is unique → distinct PKs).
    with file_reads._db.connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM file_reads").fetchone()[0]
    assert count == N


def test_concurrent_mark_does_not_raise_locked(file_reads):
    """Sanity: under the busy_timeout default, contention on a single SQLite
    file must not surface as OperationalError to the caller."""
    N = 64

    def worker(i: int):
        try:
            file_reads.mark(f"ou_{i % 8}", "m-x", f"{i % 4:02d}.md")
            return None
        except sqlite3.OperationalError as e:  # pragma: no cover — diagnostic
            return str(e)

    with ThreadPoolExecutor(max_workers=N) as pool:
        errors = [r for r in pool.map(worker, range(N)) if r is not None]

    assert errors == [], f"unexpected sqlite errors under contention: {errors}"
