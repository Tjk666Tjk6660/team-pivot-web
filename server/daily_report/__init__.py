"""Daily report generator: scans matter index events + git commits over a
24h window, asks AI to score, broadcasts a Feishu group card.

Triggered by an external systemd timer (`scripts/daily-report/run.py`),
NOT by the main FastAPI process.

Module map:
    types.py            dataclasses for the report pipeline
    window.py           [since, until) computation
    collect_matter.py   read matter index timeline events in window
    collect_git.py      git log --all over the code mirror
    attribution.py      commit author → users.pinyin (8-tier match)
    aggregate.py        events + commits → UserActivity[] + TeamSummary
    score.py            AI prompt + JSON parse + fallback
    render.py           build Feishu card dict
    runner.py           CLI entrypoint orchestration
    config_keys.py      SQLite settings keys
"""
