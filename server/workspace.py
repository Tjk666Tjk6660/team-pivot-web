from __future__ import annotations

import logging
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator
from urllib.parse import urlparse, urlunparse

from server.git_ops import (
    align_unborn_head,
    clone,
    commit,
    head_short,
    pull,
    push,
    set_remote_url,
)
from server.git_outbox import GitPushOutbox
from server.recovery import repair_partial_writes, warn_missing_matter_owner

log = logging.getLogger(__name__)

COMMITTER_NAME = "team-pivot-web"
COMMITTER_EMAIL = "team-pivot-web@pivot.local"

# Default lazy-pull interval. Beyond this window since the last successful pull
# the next write_session will run `git pull --rebase` once before yielding;
# inside the window the pull is skipped to keep the user-visible write latency
# in the millisecond range. Tunable via Workspace constructor.
DEFAULT_PULL_INTERVAL_SECONDS = 60.0


class Workspace:
    """Disk + git access layer for a single repository.

    Concurrency model (post 方案 A):
      * `write_lock` serializes the *local* fs + commit work in this process.
      * `git pull` runs at most once per `pull_interval_seconds` window
        (lazy pull) instead of on every write.
      * `git push` is decoupled: when an `outbox` is wired in, `write_session`
        only enqueues a push job after the local commit and immediately
        `worker_notify`s a background `GitWorker`; the user-facing request
        returns without waiting for the network. When no `outbox` is wired
        (legacy / unit tests / boot-time recover) we fall back to a
        synchronous `push` so behaviour stays observable.
    """

    def __init__(
        self,
        *,
        path: Path,
        repo_url: str,
        branch: str = "main",
        token: str | None = None,
        outbox: GitPushOutbox | None = None,
        worker_notify: Callable[[], None] | None = None,
        pull_interval_seconds: float = DEFAULT_PULL_INTERVAL_SECONDS,
    ) -> None:
        self.path = Path(path)
        self._repo_url = repo_url
        self._branch = branch
        self._token = token
        self.write_lock = threading.Lock()
        self._outbox = outbox
        self._worker_notify = worker_notify
        self._pull_interval_seconds = pull_interval_seconds
        # 0.0 = never pulled in this process. The first write_session after
        # boot always runs a pull; recover() also bumps this so the very next
        # write_session can skip pulling if it lands within the lazy window.
        self._last_pull_at: float = 0.0

    # ── outbox wiring (deferred so app.py can build the worker after the
    #    workspace is already constructed by WorkspaceRuntime) ─────────────

    def attach_outbox(
        self,
        *,
        outbox: GitPushOutbox,
        worker_notify: Callable[[], None] | None = None,
    ) -> None:
        """Switch this workspace from synchronous-push to outbox-async-push.

        Called once during app startup after the GitPushOutbox + GitWorker
        have been built. Idempotent — re-attaching just replaces the
        references, which is what we want during lifespan reload.
        """
        self._outbox = outbox
        self._worker_notify = worker_notify
        log.info("workspace outbox attached path=%s", self.path)

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
            set_remote_url(str(self.path), "origin", self._auth_url())
            align_unborn_head(str(self.path), self._branch)
            log.debug("workspace already cloned path=%s", self.path)
            return
        log.info("workspace cloning %s -> %s", self._repo_url, self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        clone(self._auth_url(), str(self.path), branch=self._branch)
        log.info("workspace ready path=%s head=%s", self.path, self.head())

    def refresh(self) -> None:
        pull(str(self.path))

    def head(self) -> str | None:
        if not self.is_cloned():
            return None
        return head_short(str(self.path))

    def recover(self) -> int:
        """Boot-time integrity sweep.

        Runs *synchronously* (synchronous push too) because it executes during
        WorkspaceRuntime startup before the GitWorker exists; we want any
        recovery commits flushed to origin immediately so the cluster sees a
        consistent state when the server starts accepting requests.
        """
        if not self.is_cloned():
            return 0
        with self.write_lock:
            fixed = repair_partial_writes(self.discussions_dir, self.index_dir)
            missing_owner = warn_missing_matter_owner(self.index_dir)
            dirty = _is_dirty(self.path)
            if fixed > 0:
                log.info("recovery fixed=%d partial write(s)", fixed)
            if missing_owner > 0:
                log.warning("recovery found %d matter index(es) missing owner", missing_owner)
            if fixed == 0 and missing_owner == 0 and dirty:
                log.warning("recovery found dirty working tree (no un-indexed posts)")
            elif fixed == 0 and missing_owner == 0:
                log.debug("recovery no-op")
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
                    # Boot-time: synchronous push is fine — see docstring.
                    push(str(self.path))
            pull(str(self.path))
            self._last_pull_at = time.monotonic()
            return fixed

    @contextmanager
    def write_session(
        self,
        *,
        message: str,
        author_name: str,
        author_email: str,
    ) -> Iterator[None]:
        """Locked context for one user-facing write.

        Flow:
          1. Acquire process-wide write_lock (fast — local only).
          2. Lazy `git pull --rebase` if the cached HEAD is older than
             `pull_interval_seconds`. Pull failures are logged but do NOT
             fail the write — the GitWorker surfaces real conflicts later.
          3. Yield to the caller (writes .md / .index.yaml).
          4. `git commit`. If anything changed, hand the push off:
               * outbox-mode: enqueue a push job + notify GitWorker → return
               * legacy-mode: synchronous git push (preserves old behaviour
                 for tests / boot path / workspaces without a wired outbox)
        """
        with self.write_lock:
            log.debug(
                "write_session begin message=%s author=%s", message, author_name,
            )
            self._maybe_lazy_pull()
            yield
            changed = commit(
                str(self.path),
                message=message,
                paths=[],
                author=f"{author_name} <{author_email}>",
                committer_name=COMMITTER_NAME,
                committer_email=COMMITTER_EMAIL,
            )
            if not changed:
                log.debug("write_session no-op (nothing changed)")
                return
            self._dispatch_push(reason=message)
            log.info(
                "write_session committed message=%s author=%s head=%s mode=%s",
                message, author_name, self.head(),
                "outbox" if self._outbox is not None else "sync",
            )

    # ── internals ─────────────────────────────────────────────────────────

    def _maybe_lazy_pull(self) -> None:
        """Pull at most once per `_pull_interval_seconds` window.

        Pre-方案-A behaviour: every write triggered a pull, paying the
        round-trip on every request. Now we cache "last successful pull at"
        and skip the pull when it's still within the freshness window.

        On failure we still bump the timestamp to avoid hot-retrying a
        broken upstream on every write — the next pull happens after the
        full interval, by which point transient blips have usually cleared.
        """
        now = time.monotonic()
        if self._last_pull_at and (now - self._last_pull_at) < self._pull_interval_seconds:
            log.debug(
                "write_session skipping lazy pull (age=%.1fs < %.1fs)",
                now - self._last_pull_at, self._pull_interval_seconds,
            )
            return
        try:
            pull(str(self.path))
        except Exception:
            log.exception(
                "write_session lazy pull failed; continuing with stale base",
            )
        finally:
            self._last_pull_at = now

    def _dispatch_push(self, *, reason: str) -> None:
        """Hand off the push: outbox if wired, otherwise synchronous fallback."""
        if self._outbox is None:
            # Legacy fallback: behave exactly like pre-方案-A code.
            push(str(self.path))
            return
        try:
            self._outbox.enqueue(reason=reason[:300] if reason else None)
        except Exception:
            # Enqueue failure is critical — without enqueue the commit will
            # never reach origin. Fall back to synchronous push so the user
            # gets at least the old (slow) guarantee. Log loudly so ops sees it.
            log.exception(
                "outbox.enqueue failed; falling back to synchronous push",
            )
            push(str(self.path))
            return
        if self._worker_notify is not None:
            try:
                self._worker_notify()
            except Exception:
                # Notify failure just delays the push to the next poll tick;
                # the commit itself is safely captured in the outbox.
                log.warning(
                    "git_worker notify raised; will retry on next poll",
                    exc_info=True,
                )

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
