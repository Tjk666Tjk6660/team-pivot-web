"""Matter scoring system.

Trigger: Matter 进入 finished 后由 events.TOPIC_RESULT_CREATED 订阅器入队，
后台 worker 读 timeline → 调 AI → 解析 → 写入 SQLite。

Design: 见 matter「需求：员工评价体系需求与设计」第 002 条 act 文件。

Module layout:
    resolve.py    pinyin ↔ pivot_user.id 解析层（git timeline 用 pinyin，
                  SQLite 用 pivot_user.id）
    store.py      SQLite repo（runs / scores / evidence / commenter_weights）
    schema.py     [PR2] pydantic ScoringOutput + 反伪造校验
    prompt.py     [PR2] timeline + weights → AI prompt
    ai_runner.py  [PR2] oneshot.generate_text + 解析
    trigger.py    [PR3] events.subscribe(TOPIC_RESULT_CREATED)
    worker.py     [PR3] asyncio queue + offload to thread
"""
