"""Constructor step: git pull in data_space to sync latest data."""
from __future__ import annotations

import json
import os
import subprocess
import sys


def main():
    payload = json.loads(sys.stdin.read())
    data_space_dir = os.environ.get("PIVOT_DATA_SPACE_DIR", "")

    if not data_space_dir or not os.path.isdir(data_space_dir):
        # data_space not yet cloned — skip silently (check_config already flagged it)
        sys.stdout.write(json.dumps({"output": {"synced": False, "reason": "data_space not found"}}))
        return

    try:
        proc = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=data_space_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        sys.stdout.write(json.dumps({"output": {
            "synced": proc.returncode == 0,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }}))
    except subprocess.TimeoutExpired:
        sys.stdout.write(json.dumps({"output": {"synced": False, "reason": "git pull timed out"}}))


if __name__ == "__main__":
    main()
