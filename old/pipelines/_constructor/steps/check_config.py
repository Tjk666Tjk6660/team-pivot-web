"""Constructor step: validate pivot-config.yaml completeness.

Reads the config file and checks that all required fields are filled.
If any are empty, exits with non-zero code and reports missing fields.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).parent
_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_ROOT))

from tools.config import check_config  # noqa: E402


def main():
    payload = json.loads(sys.stdin.read())

    import os
    data_dir = os.environ.get("PIVOT_DATA_DIR", "")
    if not data_dir:
        # Legacy fallback: derive from PIVOT_DATA_SPACE_DIR
        ds = os.environ.get("PIVOT_DATA_SPACE_DIR", "")
        data_dir = os.environ.get("PIVOT_REPO_PATH") or (str(Path(ds).parent) if ds else "")

    result = check_config(data_dir)

    if not result["ready"]:
        print(json.dumps({
            "error": "ConfigNotReady",
            "missing": result["missing"],
            "message": f"Configuration incomplete. Missing: {', '.join(result['missing'])}",
        }), file=sys.stderr)
        sys.exit(1)

    sys.stdout.write(json.dumps({"output": {"config_ok": True}}))


if __name__ == "__main__":
    main()
