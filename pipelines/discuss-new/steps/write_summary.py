"""Write the LLM-generated summary into the draft file's frontmatter."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).parent
_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_ROOT))

from tools.atomicity import read_business_file, write_business_file_pending  # noqa: E402


def main():
    payload = json.loads(sys.stdin.read())
    draft_path = payload["steps"]["prepare"]["output"].get("draft_path", "")
    summary = payload["steps"]["generate_summary"]["output"]["summary"]

    if not draft_path:
        # content mode: no draft file to write back to, summary lives in LLM output
        sys.stdout.write(json.dumps({"output": {"written": False, "summary": summary}}, ensure_ascii=False))
        return

    parsed = read_business_file(draft_path)
    parsed.frontmatter["summary"] = summary
    write_business_file_pending(draft_path, frontmatter=parsed.frontmatter, body=parsed.body)

    sys.stdout.write(json.dumps({"output": {"written": True}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
