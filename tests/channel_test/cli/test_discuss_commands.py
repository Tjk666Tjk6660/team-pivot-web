"""CLI test: discuss subcommands send correct RPC."""
import json
import os
import subprocess
from pathlib import Path

PIVOT_CLI = Path(__file__).parent.parent.parent.parent / "bin" / "pivot-cli"


def _setup_config(tmp_path: Path, endpoint: str, token: str = "ptk_test"):
    config = tmp_path / ".pivot-cli.conf"
    config.write_text(f"PIVOT_ENDPOINT={endpoint}\nPIVOT_TOKEN={token}\n")


def _run_cli(tmp_path: Path, *args):
    return subprocess.run(
        ["bash", str(PIVOT_CLI), *args],
        capture_output=True, text=True,
        env={**os.environ, "HOME": str(tmp_path)},
    )


class TestDiscussCommands:
    def test_list_sends_correct_rpc(self, mock_rpc_server, tmp_path: Path):
        _setup_config(tmp_path, mock_rpc_server["url"])
        proc = _run_cli(tmp_path, "discuss", "list", "enclaws")
        assert proc.returncode == 0

        req = mock_rpc_server["received"][0]
        assert req["body"]["method"] == "app.pivot.discuss-list"
        assert req["body"]["params"]["category"] == "enclaws"
        assert req["path"] == "/api/rpc"

    def test_list_sends_bearer_token(self, mock_rpc_server, tmp_path: Path):
        _setup_config(tmp_path, mock_rpc_server["url"], token="my-secret")
        _run_cli(tmp_path, "discuss", "list")

        req = mock_rpc_server["received"][0]
        assert req["auth"] == "Bearer my-secret"

    def test_inbox_sends_rpc(self, mock_rpc_server, tmp_path: Path):
        _setup_config(tmp_path, mock_rpc_server["url"])
        _run_cli(tmp_path, "discuss", "inbox")

        req = mock_rpc_server["received"][0]
        assert req["body"]["method"] == "app.pivot.discuss-inbox"

    def test_read_parses_target(self, mock_rpc_server, tmp_path: Path):
        _setup_config(tmp_path, mock_rpc_server["url"])
        _run_cli(tmp_path, "discuss", "read", "enclaws/auth-redesign")

        req = mock_rpc_server["received"][0]
        assert req["body"]["method"] == "app.pivot.discuss-read"
        assert req["body"]["params"]["category"] == "enclaws"
        assert req["body"]["params"]["thread"] == "auth-redesign"

    def test_close_sends_status_rpc(self, mock_rpc_server, tmp_path: Path):
        _setup_config(tmp_path, mock_rpc_server["url"])
        _run_cli(tmp_path, "discuss", "close", "dev/my-thread")

        req = mock_rpc_server["received"][0]
        assert req["body"]["method"] == "app.pivot.discuss-status"
        assert req["body"]["params"]["action"] == "close"

    def test_reopen_requires_reason(self, tmp_path: Path):
        _setup_config(tmp_path, "http://localhost:1")
        proc = _run_cli(tmp_path, "discuss", "reopen", "dev/thread")
        assert proc.returncode != 0

    def test_not_logged_in_fails(self, tmp_path: Path):
        proc = _run_cli(tmp_path, "discuss", "list")
        assert proc.returncode != 0
