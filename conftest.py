"""Project-root conftest — shared fixtures visible to all tests under
tools/, cli/, pipelines/, and tests/.
"""
import subprocess
import sys
from pathlib import Path

import pytest

# Make `tools.*` and `tests.*` importable in any collected test module.
sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture
def user_workspace(tmp_path: Path, monkeypatch) -> Path:
    """Isolated ENCLAWS_USER_WORKSPACE for the test — inherited by subprocesses."""
    ws = tmp_path / "user_workspace"
    ws.mkdir()
    monkeypatch.setenv("ENCLAWS_USER_WORKSPACE", str(ws))
    return ws


@pytest.fixture
def make_proposal_draft(user_workspace: Path):
    """Factory: save a proposal draft, return its draft_id."""
    from tools.drafts import save_draft

    def _make(title: str = "t", content: str = "body") -> str:
        return save_draft(type_="proposal", title=title, content=content).draft_id

    return _make


@pytest.fixture
def make_reply_draft(user_workspace: Path):
    """Factory: save a reply draft, return its draft_id."""
    from tools.drafts import save_draft

    def _make(thread: str, title: str = "r", content: str = "body") -> str:
        return save_draft(
            type_="reply", title=title, content=content, thread=thread,
        ).draft_id

    return _make


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:
    """Create a local bare + working git repo pair. Returns working repo path.

    Forces the local branch to `main` and sets upstream tracking so pull/push
    work without extra flags, regardless of the system's init.defaultBranch.
    """
    bare = tmp_path / "bare.git"
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(bare)], check=True
    )
    work = tmp_path / "work"
    subprocess.run(["git", "clone", str(bare), str(work)], check=True)
    subprocess.run(["git", "-C", str(work), "config", "user.email", "t@t.com"], check=True)
    subprocess.run(["git", "-C", str(work), "config", "user.name", "t"], check=True)
    subprocess.run(["git", "-C", str(work), "checkout", "-b", "main"], check=True)
    (work / "README.md").write_text("# test\n")
    subprocess.run(["git", "-C", str(work), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(work), "commit", "-m", "initial"], check=True)
    subprocess.run(
        ["git", "-C", str(work), "push", "-u", "origin", "main"], check=True
    )
    return work


@pytest.fixture
def tmp_data_space(tmp_path: Path) -> Path:
    """A temporary data_space dir simulating PIVOT_DATA_SPACE_DIR."""
    ws = tmp_path / "data_space"
    ws.mkdir()
    return ws


# ---------- Phase 1.1: mock Feishu webhook server ----------

import json as _json
import threading as _threading
from http.server import BaseHTTPRequestHandler as _BaseHTTPRequestHandler
from http.server import HTTPServer as _HTTPServer


@pytest.fixture
def mock_feishu_server():
    """Start a local HTTP server that mimics a Feishu webhook endpoint.

    Yields a dict with:
      - url: "http://127.0.0.1:<free port>" to use as FEISHU_WEBHOOK_URL
      - received: list of parsed JSON bodies captured from POSTs

    Shuts down cleanly on fixture teardown.
    """
    received: list = []

    class Handler(_BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0") or 0)
            body_bytes = self.rfile.read(length) if length else b""
            try:
                received.append(_json.loads(body_bytes))
            except _json.JSONDecodeError:
                received.append({"_raw": body_bytes.decode("utf-8", "replace")})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"code":0}')

        def log_message(self, *args, **kwargs):
            return  # suppress access log spam

    server = _HTTPServer(("127.0.0.1", 0), Handler)
    thread = _threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}"
    try:
        yield {"url": url, "received": received}
    finally:
        server.shutdown()
        server.server_close()
