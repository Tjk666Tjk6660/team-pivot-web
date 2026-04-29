"""SQLite settings keys consumed by the daily-report runner."""
from __future__ import annotations

# `"1"` (default) → enabled. Anything in {"0", "false", "off"} → skipped.
KEY_ENABLED = "daily_report.enabled"

# JSON map: {"<pinyin>": ["alt-email1", "alt-email2"]}.
# Used by `attribution.py` highest-priority tier.
KEY_OVERRIDES = "daily_report.commit_author_overrides"

# Local path of the code-mirror workspace (`git fetch` + `git log` target).
# Default `/opt/team-pivot-web/var/code-mirror/team-pivot-web` matches the
# README's setup instructions; admins can override per-deploy.
KEY_CODE_REPO_DIR = "daily_report.code_repo_dir"

DEFAULT_CODE_REPO_DIR = "/opt/team-pivot-web/var/code-mirror/team-pivot-web"

# **Reserved for future** (not consumed by current code path):
# When `"1"`, the AI scoring step is allowed to call tool-use functions to
# read MD bodies in matters where summary alone is insufficient. Default `"0"`
# keeps MVP cost predictable. Discussed in dengke #003 of matter
# `新需求-日报推送`. Will be wired up in a future release; declaring the key
# now so admins / settings UI know it exists.
KEY_ALLOW_AI_READ_BODY = "daily_report.allow_ai_read_body"
