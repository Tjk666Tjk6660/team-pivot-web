"""CLI test: login command."""
import os
import subprocess
import sys
from pathlib import Path

PIVOT_CLI = Path(__file__).parent.parent.parent.parent / "bin" / "pivot-cli"


class TestLogin:
    def test_login_saves_config(self, tmp_path: Path):
        proc = subprocess.run(
            ["bash", str(PIVOT_CLI), "login",
             "--endpoint", "https://test.enclaws.com",
             "--token", "ptk_test123"],
            capture_output=True, text=True,
            env={**os.environ, "HOME": str(tmp_path)},
        )
        assert proc.returncode == 0
        config = (tmp_path / ".pivot-cli.conf").read_text()
        assert "https://test.enclaws.com" in config
        assert "ptk_test123" in config

    def test_login_requires_endpoint(self, tmp_path: Path):
        proc = subprocess.run(
            ["bash", str(PIVOT_CLI), "login", "--token", "x"],
            capture_output=True, text=True,
            env={**os.environ, "HOME": str(tmp_path)},
        )
        assert proc.returncode != 0
