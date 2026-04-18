from __future__ import annotations

import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse, urlunparse

from server.git_ops import clone, commit, head_short, pull, push
from server.recovery import repair_partial_writes

COMMITTER_NAME = "team-pivot-web"
COMMITTER_EMAIL = "team-pivot-web@pivot.local"


class Workspace:
    def __init__(
        self,
        *,
        path: Path,
        repo_url: str,
        branch: str = "main",
        token: str | None = None,
    ) -> None:
        self.path = Path(path)
        self._repo_url = repo_url
        self._branch = branch
        self._token = token
        self.write_lock = threading.Lock()

    @property
    def discussions_dir(self) -> Path:
        return self.path / "discussions"

    @property
    def index_dir(self) -> Path:
        return self.path / "index"

    def is_cloned(self) -> bool:
        return (self.path / ".git").is_dir()

    def ensure_cloned(self) -> None:
        if self.is_cloned():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        clone(self._auth_url(), str(self.path), branch=self._branch)

    def refresh(self) -> None:
        pull(str(self.path))

    def head(self) -> str | None:
        if not self.is_cloned():
            return None
        return head_short(str(self.path))

    def recover(self) -> int:
        if not self.is_cloned():
            return 0
        with self.write_lock:
            pull(str(self.path))
            fixed = repair_partial_writes(self.discussions_dir, self.index_dir)
            dirty = _is_dirty(self.path)
            if fixed > 0 or dirty:
                changed = commit(
                    str(self.path),
                    message=f"chore: recover {fixed} partial write(s)"
                    if fixed > 0 else "chore: recover dirty working tree",
                    paths=[],
                    author=f"{COMMITTER_NAME} <{COMMITTER_EMAIL}>",
                    committer_name=COMMITTER_NAME,
                    committer_email=COMMITTER_EMAIL,
                )
                if changed:
                    push(str(self.path))
            return fixed

    @contextmanager
    def write_session(
        self,
        *,
        message: str,
        author_name: str,
        author_email: str,
    ) -> Iterator[None]:
        with self.write_lock:
            pull(str(self.path))
            yield
            changed = commit(
                str(self.path),
                message=message,
                paths=[],
                author=f"{author_name} <{author_email}>",
                committer_name=COMMITTER_NAME,
                committer_email=COMMITTER_EMAIL,
            )
            if changed:
                push(str(self.path))

    def _auth_url(self) -> str:
        if not self._token:
            return self._repo_url
        p = urlparse(self._repo_url)
        if p.scheme != "https":
            return self._repo_url
        netloc = f"oauth2:{self._token}@{p.hostname}"
        if p.port:
            netloc += f":{p.port}"
        return urlunparse(p._replace(netloc=netloc))


def _is_dirty(repo_path: Path) -> bool:
    proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        check=True,
    )
    return bool(proc.stdout.strip())


def repo_dir_name(url: str) -> str:
    name = url.rstrip("/").rsplit("/", 1)[-1]
    return name[:-4] if name.endswith(".git") else name
