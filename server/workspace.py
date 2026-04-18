from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from server.git_ops import clone, head_short, pull


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
        self.write_lock = asyncio.Lock()

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


def repo_dir_name(url: str) -> str:
    name = url.rstrip("/").rsplit("/", 1)[-1]
    return name[:-4] if name.endswith(".git") else name
