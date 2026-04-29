"""Daily report generator (v0.2).

基于 dengke #013 方向:
- 只读 Pivot matter index 数据,不接入 git 代码仓库
- 不评分,生成两份独立 LLM 报告(公司视角 / 个人视角)
- 共享底层事实数据,不共享 LLM 中间结果

由 systemd timer 触发(scripts/daily-report/run.py),也可由 admin 手动触发
(POST /api/admin/daily-report/trigger)。

模块组织:
    types.py            事实层 dataclass(TimeWindow / MatterEvent / UserActivity / TeamSummary)
    window.py           [since, until) 时间窗口推算
    collect_matter.py   扫 index 提取 timeline 事件
    aggregate.py        events → UserActivity[] + TeamSummary
    shared_facts.py     [Phase 2] 给两个 LLM 调用准备的统一事实底稿
    company_narrate.py  [Phase 3] 公司视角 LLM 调用,生成整体推进段落
    personal_narrate.py [Phase 4] 个人视角 LLM 调用,逐人生成输入/输出叙述
    render.py           [Phase 3/4] 飞书卡片渲染
    runner.py           CLI 入口,串起来
    config_keys.py      SQLite settings 配置键
"""
