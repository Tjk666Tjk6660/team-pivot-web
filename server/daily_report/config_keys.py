"""SQLite settings keys consumed by the daily-report runner (v0.2).

存储:沿用 server/settings.py SettingsRepo 机制(主服务的 settings 表)。
admin UI 读写。runner 启动时 read-only 读取。

v0.2 删除 v0.1 的 commit_author_overrides / code_repo_dir 配置(不接 git)。
新增多份报告各自的开关 / 触发方式 / 推送目标等(Phase 5 实施)。
"""
from __future__ import annotations

# 总开关。"1" → 启用;"0" / "false" / "off" → runner 跳过执行,退出码 0。
KEY_ENABLED = "daily_report.enabled"

# 公司视角报告开关("1" / "0",默认 "1")
KEY_COMPANY_ENABLED = "daily_report.company_enabled"

# 个人视角报告开关("1" / "0",默认 "1")
KEY_PERSONAL_ENABLED = "daily_report.personal_enabled"

# 时间范围(小时数,默认 24)。supports admin tuning per dengke #012.
KEY_TIME_WINDOW_HOURS = "daily_report.time_window_hours"

# 每日推送时刻(HH:MM,Asia/Shanghai),默认 09:30。in-process scheduler 用。
KEY_PUSH_TIME = "daily_report.push_time"

# Category 筛选(逗号分隔的 category 名;空 = 全部)。category 来自 matter
# 文件路径 discussions/<category>/<slug>/...,不是 index 字段。
KEY_CATEGORY_FILTER = "daily_report.category_filter"

# AI 正文读取权限(预留,v0.2 暂未启用 tool-use)
KEY_ALLOW_AI_READ_BODY = "daily_report.allow_ai_read_body"
