"""Demo: file mtime before vs after a write (cross-platform).

Run:
    python scripts/test_file_mtime.py
"""
from __future__ import annotations

import random
import string
import tempfile
import time
from datetime import datetime
from pathlib import Path


class FileMTimeTest:
    @staticmethod
    def _format_mtime(path: Path) -> str:
        st = path.stat()
        ns = st.st_mtime_ns
        dt = datetime.fromtimestamp(ns / 1_000_000_000).astimezone()
        return f"{dt.isoformat(timespec='microseconds')}  (mtime_ns={ns})"

    @staticmethod
    def _random_chars(n: int) -> str:
        return "".join(random.choices(string.ascii_letters + string.digits, k=n))

    def run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mtime_demo.txt"

            path.write_text("initial content\n", encoding="utf-8")
            t1 = self._format_mtime(path)
            print(f"file:           {path}")
            print(f"[1] after create:  {t1}")

            # Windows + NTFS 会合并相邻的 mtime 写,sleep 跨过一个系统 tick
            # (典型 15.6ms),保证两次 mtime 能拉开。Linux 上不需要,加上无害。
            time.sleep(0.1)

            payload = self._random_chars(50)
            with path.open("a", encoding="utf-8") as f:
                f.write(payload)
            t2 = self._format_mtime(path)
            print(f"[2] after append:  {t2}")
            print(f"    appended:      {payload!r}")
            print(f"    delta_ns:      {path.stat().st_mtime_ns - int(t1.split('mtime_ns=')[1].rstrip(')'))}")


if __name__ == "__main__":
    FileMTimeTest().run()
