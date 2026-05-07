"""Tests for `server.daily_report.render`. Snapshot-style assertions on key
card fields — we don't try to exactly match Feishu's card schema (the network
layer would catch real schema breaks).

Phase 3 covers `build_company_card`. Phase 4 will add `build_personal_card`.
"""
from __future__ import annotations

from datetime import datetime

from server.daily_report.company_narrate import CompanyNarrative
from server.daily_report.personal_narrate import PersonalEntry, PersonalNarrative
from server.daily_report.render import (
    build_admin_alert_card,
    build_company_card,
    build_personal_card,
)
from server.daily_report.shared_facts import build_shared_facts
from server.daily_report.types import (
    MatterEvent,
    TeamSummary,
    TimeWindow,
    UserActivity,
)
from server.daily_report.window import CHINA_TZ


# --------------------------------------------------------------------------- #
# fixtures                                                                    #
# --------------------------------------------------------------------------- #


def _w() -> TimeWindow:
    return TimeWindow(
        since=datetime(2026, 4, 28, 9, 0, tzinfo=CHINA_TZ),
        until=datetime(2026, 4, 29, 9, 0, tzinfo=CHINA_TZ),
    )


def _ev(matter_id: str = "m1", file: str = "discussions/Pivot/m1/001.md") -> MatterEvent:
    return MatterEvent(
        matter_id=matter_id, matter_title=matter_id,
        matter_current_status="executing",
        file=file, file_type="act",
        created_at=_w().since, file_in_window=True,
        creator="alice", owner="alice",
        summary="x", status_change=None,
        verifications=(), comments_in_window=(),
    )


def _ua(pinyin: str, *, active: bool = True) -> UserActivity:
    creates = (_ev(),) if active else ()
    return UserActivity(
        pinyin=pinyin, display_name=pinyin,
        file_creates=creates, file_owns=(),
        verifications_given=(), status_changes_triggered=(),
        comments_given=(), mentions_received=0,
    )


def _summary(**overrides) -> TeamSummary:
    base = dict(
        window=_w(), total_files=5, total_status_changes=1,
        total_comments=3, matters_touched=2, inactive_users=("zhang",),
    )
    base.update(overrides)
    return TeamSummary(**base)


def _facts():
    events = [_ev("m1"), _ev("m2", "discussions/enclaws/m2/001.md")]
    activities = [_ua("alice"), _ua("zhang", active=False)]
    return build_shared_facts(events, activities, _summary(), _w())


def _markdown_from(card: dict) -> str:
    """把卡片所有可见文本元素拼成一个字符串供测试 assert in 检查。
    新版卡片是 multi-element(markdown / note / hr 多块),需要把所有
    markdown 和 note 内容串起来,加 \\n 分隔。hr 不出文字。"""
    parts: list[str] = []
    for el in card["body"]["elements"]:
        tag = el.get("tag")
        if tag == "markdown":
            parts.append(el.get("content", ""))
        elif tag == "note":
            for sub in el.get("elements") or []:
                if sub.get("tag") in ("plain_text", "lark_md"):
                    parts.append(sub.get("content", ""))
    if not parts:
        raise AssertionError(f"no markdown/note element in card: {card}")
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# build_company_card                                                          #
# --------------------------------------------------------------------------- #


def test_ai_company_card_has_blue_template():
    nar = CompanyNarrative(
        status="ai",
        summary="团队聚焦于 Pivot 与 enclaws,主链路有实质闭环动作。",
        tone="active",
    )
    card = build_company_card(_facts(), nar)
    assert card["header"]["template"] == "blue"
    assert (
        card["header"]["title"]["content"]
        == "📊 公司日报 · 2026-04-28 09:00 → 2026-04-29 09:00"
    )


def test_company_card_can_link_to_full_report_page():
    nar = CompanyNarrative(status="ai", summary="x", tone="active")
    card = build_company_card(
        _facts(), nar, report_url="http://web/daily-report/runs/42",
    )
    button = card["body"]["elements"][-1]
    assert button["tag"] == "button"
    assert button["text"]["content"] == "查看完整日报"
    assert button["multi_url"]["url"] == "http://web/daily-report/runs/42"


def test_company_compact_card_keeps_feishu_message_short():
    summary = (
        "今天团队主要在 Pivot 与 enclaws 两个方向上推进。\n"
        "\n"
        "第一是 Pivot 产品方向。需要关注的有：\n"
        "lishuai 负责的 Owner 机制验证未过，需要继续修复字段问题。\n"
        "tangkun 相关筛选项还在待验证阶段。\n"
        "\n"
        "第二是 enclaws 底层方向。部署环境 lishuai 已完成。\n"
    )
    nar = CompanyNarrative(status="ai", summary=summary, tone="active")
    card = build_company_card(
        _facts(), nar, report_url="http://web/daily-report/runs/42", compact=True,
    )
    md = _markdown_from(card)
    assert '## <font color="blue">今日概况</font>' in md
    assert '## <font color="red">需要关注</font>' in md
    assert '- <font color="red">lishuai 负责的 Owner 机制验证未过，需要继续修复字段问题。</font>' in md
    assert "完整方向明细、事项列表和人员动作请查看完整日报" in md


def test_company_compact_attention_strips_subsection_number():
    summary = (
        "今天团队主要在 Pivot 产品方向上推进。\n"
        "\n"
        "第一是 Pivot 产品方向。多项底层改造与内部产品固定位置集中暂停：\n"
        "xiongjianping 按 dengke 拍板暂停 EC 底层改造规划，重新评估 ToB 架构与商业化定位。\n"
        "xiongjianping 同步暂停 AI 客服 S1 上线，等待架构重估结论。\n"
    )
    nar = CompanyNarrative(status="ai", summary=summary, tone="steady")

    md = _markdown_from(build_company_card(_facts(), nar, compact=True))

    assert "(1) 多项底层改造与内部产品固定位置集中暂停" not in md
    assert "多项底层改造与内部产品固定位置集中暂停" in md


def test_company_compact_card_omits_disclaimer():
    nar = CompanyNarrative(
        status="ai",
        summary="今天团队主要在 Pivot 产品方向上推进。",
        tone="steady",
    )

    md = _markdown_from(
        build_company_card(
            _facts(),
            nar,
            report_url="http://web/daily-report/runs/42",
            compact=True,
        )
    )

    assert "本日报由 AI 基于 Pivot matter 数据生成" not in md


def test_fallback_company_card_uses_wathet_template():
    nar = CompanyNarrative(
        status="fallback",
        summary="今日团队触动 2 个 matter ...",
        tone="steady",
        fallback_reason="ai_error: TimeoutError",
    )
    card = build_company_card(_facts(), nar)
    assert card["header"]["template"] == "wathet"
    md = _markdown_from(card)
    assert "AI 公司视角生成失败" in md
    assert "TimeoutError" in md


def test_no_activity_card_uses_wathet_template():
    """no_activity / fallback 走 wathet 浅色模板,与 ai 状态的 blue 区分。
    v0.13 之后不再渲染"整体节奏: X"那行,所以仅检查 template 颜色 +
    叙事正文。"""
    nar = CompanyNarrative(
        status="no_activity",
        summary="今日团队在 Pivot 上无任何 matter 活动。",
        tone="stalled",
    )
    card = build_company_card(_facts(), nar)
    assert card["header"]["template"] == "wathet"
    md = _markdown_from(card)
    assert "今日团队在 Pivot 上无任何 matter 活动" in md


def test_ai_card_renders_window_in_header_no_stats():
    """v0.7(2026-05-01): 不再渲染"📈 团队总览"统计行 —— 老板不爱看僵硬
    的统计数字。
    v0.20(2026-05-06): 时间窗口移到 note 元素(小灰字),"覆盖窗口" 字面
    词省略,只保留 📅 + 时间区间。"""
    nar = CompanyNarrative(status="ai", summary="x", tone="steady")
    card = build_company_card(_facts(), nar)
    md = _markdown_from(card)
    assert "2026-04-28 09:00 → 2026-04-29 09:00" in card["header"]["title"]["content"]
    assert "📅" not in md
    assert "2026-04-28 09:00" not in md
    assert "2026-04-29 09:00" not in md
    # 统计行已删除
    assert "团队总览" not in md
    assert "matter 事件" not in md
    assert "状态推进" not in md


def test_tone_label_no_longer_rendered():
    """v0.13 后(2026-05-06 演示反馈):"整体节奏: 积极推进/平稳推进/偏停滞"
    那行被认定为多余的主观判断,直接陈述事实即可,不再渲染。
    tone 仍解析(影响 template 冷暖色),但卡片正文里看不到。"""
    for tone in ("active", "steady", "stalled"):
        nar = CompanyNarrative(status="ai", summary="x", tone=tone)
        md = _markdown_from(build_company_card(_facts(), nar))
        # "整体节奏" 字样不再出现
        assert "整体节奏" not in md
        # tone 文字标签也不再出现
        assert "积极推进" not in md
        assert "平稳推进" not in md
        assert "偏停滞" not in md


def test_disclaimer_always_present():
    """提示这是 AI 分析不是结论 —— ai/fallback 都要有这一行。"""
    for status in ("ai", "fallback", "no_activity"):
        nar = CompanyNarrative(status=status, summary="x", tone="steady")
        md = _markdown_from(build_company_card(_facts(), nar))
        assert "AI" in md and "管理参考" in md


# --------------------------------------------------------------------------- #
# 公司视角:格式后处理(v0.13 视觉层次)                                        #
# --------------------------------------------------------------------------- #


def test_company_summary_direction_header_renders_with_h2_number():
    """方向段开头"第X是 Y。"渲染成 "## X、Y"。
    先暂定 markdown h2,让一级方向标题在飞书里更明显。"""
    summary = (
        "今天团队主要在 Pivot 与 enclaws 两个方向上推进。\n"
        "\n"
        "第一是 Pivot 产品方向。多项老需求集中闭环：\n"
        "A 完成 X。\n"
        "B 完成 Y。\n"
        "C 完成 Z。\n"
    )
    nar = CompanyNarrative(status="ai", summary=summary, tone="active")
    md = _markdown_from(build_company_card(_facts(), nar))
    # markdown h2 + 中文序号
    assert '## <font color="blue">一、Pivot 产品方向</font>' in md
    # "第一是" 序号文字不再出现
    assert "第一是 Pivot" not in md


def test_company_summary_direction_header_without_方向_suffix():
    """方向名不以"方向"结尾也要被识别为方向段标题。
    序号来自原始"第X是"。"""
    summary = (
        "今天团队主要在 Pivot 产品 与 enclaws 与 OPC 项目底座 两个方向上推进。\n"
        "\n"
        "第二是 enclaws 与 OPC 项目底座。OPC 演示与方案项集中闭环：\n"
        "A 完成 X。\n"
        "B 完成 Y。\n"
        "C 完成 Z。\n"
    )
    nar = CompanyNarrative(status="ai", summary=summary, tone="active")
    md = _markdown_from(build_company_card(_facts(), nar))
    # markdown h2 + 中文序号,不带"方向"后缀
    assert '## <font color="blue">二、enclaws 与 OPC 项目底座</font>' in md
    assert "第二是 enclaws" not in md
    # 子段头用 (1) + 语义色 + bold(去掉行尾 ":")
    assert '<font color="green">**(1)** OPC 演示与方案项集中闭环</font>' in md
    # 事项 bullet 化
    assert "- A 完成 X。" in md


def test_company_summary_direction_number_keeps_external_title():
    """外部客户交付方向也用统一的 h2 + 中文序号标题。"""
    summary = (
        "今天团队主要在外部客户交付方向上推进。\n"
        "\n"
        "第一是外部客户交付方向。物料定稿：\n"
        "A 完成 X。\n"
        "B 完成 Y。\n"
    )
    nar = CompanyNarrative(status="ai", summary=summary, tone="active")
    md = _markdown_from(build_company_card(_facts(), nar))
    assert '## <font color="blue">一、外部客户交付方向</font>' in md


def test_company_summary_subsection_renders_with_secondary_number_bold():
    """子段标题用 (1) + 语义色 + bold,去掉行尾 :,后多行(≥2)事项逐行加 "- " 前缀。"""
    summary = (
        "第一是 Pivot 产品方向。多项老需求集中闭环：\n"
        "A 完成 X。\n"
        "B 完成 Y。\n"
        "C 完成 Z。\n"
        "D 完成 W。\n"
    )
    nar = CompanyNarrative(status="ai", summary=summary, tone="active")
    md = _markdown_from(build_company_card(_facts(), nar))
    # 子段头 (1) + 语义色 + bold,无 :
    assert '<font color="green">**(1)** 多项老需求集中闭环</font>' in md
    assert "多项老需求集中闭环：" not in md
    # 事项 bullet 化
    assert "- A 完成 X。" in md
    assert "- B 完成 Y。" in md
    assert "- D 完成 W。" in md


def test_company_summary_both_fullwidth_and_halfwidth_colon_trigger_subsection():
    """子段头识别全角 ":" 与半角 ":"——LLM 实测两种都偶发输出,渲染层
    都识别才 robust。但 —— 不识别(prompt 已弃用)。"""
    # 全角 ":" 触发
    summary_full = (
        "第一是 Pivot 方向。\n"
        "\n"
        "执行中与待推进的有：\n"
        "A 推进 X。\n"
        "B 推进 Y。\n"
        "C 推进 Z。\n"
    )
    nar = CompanyNarrative(status="ai", summary=summary_full, tone="active")
    md = _markdown_from(build_company_card(_facts(), nar))
    assert '<font color="blue">**(1)** 执行中与待推进的有</font>' in md
    assert "- A 推进 X。" in md

    # 半角 ":" 同样触发
    summary_half = (
        "第一是 Pivot 方向。\n"
        "\n"
        "进入实施或待验收的有:\n"
        "A 推进 X。\n"
        "B 推进 Y。\n"
        "C 推进 Z。\n"
    )
    nar = CompanyNarrative(status="ai", summary=summary_half, tone="active")
    md = _markdown_from(build_company_card(_facts(), nar))
    assert '<font color="orange">**(1)** 进入实施或待验收的有</font>' in md
    assert "- A 推进 X。" in md

    # —— 不触发(prompt 已统一改 ":")
    summary_dash = (
        "第一是 Pivot 方向。多项闭环 ——\n"
        "A 完成 X。\n"
        "B 完成 Y。\n"
    )
    nar = CompanyNarrative(status="ai", summary=summary_dash, tone="active")
    md = _markdown_from(build_company_card(_facts(), nar))
    assert "- A 完成 X。" not in md
    assert "(1) 多项闭环" not in md


def test_company_summary_inline_subsection_with_semicolons_gets_split():
    """LLM 偶尔把多 matter 串成一行 "X 的有:A;B;C。" 形式(违反 prompt 的
    "≥4 matter 每行一个"规则),渲染层要兜底拆成二级序号子段头 + bullet list。"""
    summary = (
        "第一是 Pivot 产品方向。\n"
        "\n"
        "实施推进与待验收的有：yezaiyong正修复MCP字段；"
        "terry.tao明确视图spec后zhangbo接手；lishuai交付Owner机制验证未过。\n"
    )
    nar = CompanyNarrative(status="ai", summary=summary, tone="active")
    md = _markdown_from(build_company_card(_facts(), nar))
    # 子段头被识别 + 二级序号化
    assert '<font color="orange">**(1)** 实施推进与待验收的有</font>' in md
    # 三个 matter 各自成 bullet
    assert "- yezaiyong正修复MCP字段" in md
    assert "- terry.tao明确视图spec后zhangbo接手" in md
    assert "- lishuai交付Owner机制验证未过。" in md


def test_company_summary_inline_subsection_too_short_not_split():
    """≤2 项分号串接不当作子段(避免误伤"项目X:配置项A;配置项B"这种句子)。"""
    summary = (
        "第一是 Pivot 方向。\n"
        "\n"
        "项目A：备注X；备注Y。\n"     # 只有 2 项,不拆
    )
    nar = CompanyNarrative(status="ai", summary=summary, tone="active")
    md = _markdown_from(build_company_card(_facts(), nar))
    # 原句保留
    assert "项目A：备注X；备注Y。" in md
    # 不被强行拆成 bullet
    assert "- 备注X" not in md


def test_company_summary_subsection_header_breaks_list_collection():
    """LLM 偶尔在 list 末尾紧跟下一个子段头(无空行间隔)时,后续子段头
    不能被吞进当前 list 当 item。_collect_block 遇到子段头要主动停。"""
    summary = (
        "第一是 Pivot 方向。已完成的有：\n"
        "A 完成 X。\n"
        "B 完成 Y。\n"
        "执行中或待验证的有：\n"          # <- 紧跟前一项,无空行
        "C 推进 Z。\n"
        "D 卡 8 天待修。\n"
    )
    nar = CompanyNarrative(status="ai", summary=summary, tone="active")
    md = _markdown_from(build_company_card(_facts(), nar))
    # 两个子段头都被识别为二级序号
    assert '<font color="green">**(1)** 已完成的有</font>' in md
    assert '<font color="orange">**(2)** 执行中或待验证的有</font>' in md
    # 第二段开头的子段头不能被当成 list item
    assert "- 执行中或待验证的有" not in md
    # 各项归到正确的 list
    assert "- A 完成 X。" in md
    assert "- C 推进 Z。" in md


def test_company_summary_single_item_after_subsection_not_bulleted_but_arrow():
    """子段下只有一行(≤3 matter 串接子段)不加 -,但子段头本身仍有序号。"""
    summary = (
        "第一是 enclaws 方向。三项交付完毕：\n"
        "A 完成 X; B 完成 Y; C 完成 Z。\n"
    )
    nar = CompanyNarrative(status="ai", summary=summary, tone="active")
    md = _markdown_from(build_company_card(_facts(), nar))
    assert '<font color="green">**(1)** 三项交付完毕</font>' in md
    assert "- A 完成 X" not in md           # 单行不 bullet
    assert "A 完成 X; B 完成 Y; C 完成 Z" in md


def test_company_card_inline_visual_hierarchy_in_single_markdown():
    """v0.21(2026-05-06):飞书 schema 2.0 拒绝 note / hr 元素(200861 错误),
    改回单 markdown blob 用 markdown 内部语法做视觉层次:
    - "_..._" italic 模拟小灰字辅助文本
    - "---" markdown 水平线模拟段间分隔
    - h2 方向标题 + 二级序号 + bullet list 做层次
    """
    summary = (
        "今天团队主要在 Pivot 方向推进。\n"
        "\n"
        "第一是 Pivot 产品方向。多项闭环：\n"
        "A 完成 X。\n"
        "B 完成 Y。\n"
    )
    nar = CompanyNarrative(status="ai", summary=summary, tone="active")
    card = build_company_card(_facts(), nar)
    # 单 markdown element(不再用 hr / note element)
    elements = card["body"]["elements"]
    md_elements = [e for e in elements if e.get("tag") == "markdown"]
    assert len(md_elements) == 1
    assert all(e.get("tag") == "markdown" for e in elements)   # 全部都是 markdown
    md = md_elements[0]["content"]
    # 时间窗口已上移到卡片标题;正文仍用水平线做段间分隔
    assert "2026-04-28 09:00 → 2026-04-29 09:00" in card["header"]["title"]["content"]
    assert "_📅" not in md
    assert "---" in md
    # italic footer
    assert "_本日报由 AI" in md


def test_company_summary_closing_paragraph_unchanged():
    """收尾段(普通段落)不被 bulletize 也不 bold。"""
    summary = (
        "第一是 Pivot 方向。三项闭环：\n"
        "A; B; C。\n"
        "\n"
        "团队今日 5 人 / 8 项推进,节奏紧凑。\n"
    )
    nar = CompanyNarrative(status="ai", summary=summary, tone="active")
    md = _markdown_from(build_company_card(_facts(), nar))
    assert "团队今日 5 人 / 8 项推进,节奏紧凑。" in md
    assert "- 团队今日" not in md
    assert "**团队今日" not in md


def test_company_summary_passes_through_for_non_ai_status():
    """fallback / no_activity 状态下不走后处理(summary 是固定统计句子)。"""
    summary = "今日团队触动 5 个 matter,产生 8 篇文件。"
    nar = CompanyNarrative(status="fallback", summary=summary, tone="steady",
                           fallback_reason="ai_disabled")
    md = _markdown_from(build_company_card(_facts(), nar))
    assert summary in md
    # 没有 h2 / 二级序号化
    assert "1️⃣" not in md


# --------------------------------------------------------------------------- #
# build_personal_card                                                         #
# --------------------------------------------------------------------------- #


def _personal_entries(*, n_active: int = 2, n_inactive: int = 3):
    entries: list[PersonalEntry] = []
    for i in range(n_active):
        entries.append(PersonalEntry(
            pinyin=f"a{i}", display_name=f"成员{i}",
            has_activity=True,
            narrative=f"成员{i}今天的输入和输出",
        ))
    for j in range(n_inactive):
        entries.append(PersonalEntry(
            pinyin=f"b{j}", display_name=f"无活动{j}",
            has_activity=False,
            narrative="今天没有任何输入和输出",
        ))
    return tuple(entries)


def test_personal_card_ai_template_blue():
    nar = PersonalNarrative(status="ai", entries=_personal_entries())
    card = build_personal_card(_facts(), nar)
    assert card["header"]["template"] == "blue"
    assert "👥" in card["header"]["title"]["content"]
    assert "2026-04-28 09:00 → 2026-04-29 09:00" in card["header"]["title"]["content"]


def test_personal_card_active_users_each_on_own_line():
    """渲染层用 pinyin 显示,与公司日报"人名一律 pinyin"口径对齐。
    每行用 markdown bullet "- " 前缀渲染成飞书列表。"""
    nar = PersonalNarrative(status="ai", entries=_personal_entries(
        n_active=3, n_inactive=0,
    ))
    md = _markdown_from(build_personal_card(_facts(), nar))
    for i in range(3):
        # markdown bullet 前缀 "- " + bold pinyin
        assert f"- **a{i}**:" in md
        assert f"成员{i}今天的输入和输出" in md


def test_personal_card_bolds_pinyin_mentions_inside_narrative():
    """正文里再次提到 pinyin 时也要加粗,方便扫读人名。"""
    nar = PersonalNarrative(
        status="ai",
        entries=(
            PersonalEntry(
                pinyin="a0", display_name="成员0", has_activity=True,
                narrative="与 a1 一起推进验证,等待 alice 确认。",
            ),
            PersonalEntry(
                pinyin="a1", display_name="成员1", has_activity=True,
                narrative="补充验证说明。",
            ),
        ),
    )
    md = _markdown_from(build_personal_card(_facts(), nar))
    assert "与 **a1** 一起推进验证,等待 **alice** 确认。" in md


def test_personal_card_inactive_users_merged_to_one_line():
    """无活动成员合并到一行,顿号串联;名字是 pinyin;"无活动"短语 italic
    与 active 行视觉区分。"""
    nar = PersonalNarrative(status="ai", entries=_personal_entries(
        n_active=1, n_inactive=3,
    ))
    md = _markdown_from(build_personal_card(_facts(), nar))
    # 合并行:"- _今天没有任何输入和输出_: b0、b1、b2"(- 列表前缀 + italic)
    assert "_今天没有任何输入和输出_" in md
    assert "**b0**、**b1**、**b2**" in md
    # 不应该有"bX 今天没有任何输入和输出"独立成行的形式
    assert "**b0**: 今天没有任何输入和输出" not in md


def test_personal_card_no_active_users_status():
    entries = tuple(
        PersonalEntry(pinyin=f"u{i}", display_name=f"u{i}",
                      has_activity=False,
                      narrative="今天没有任何输入和输出")
        for i in range(3)
    )
    nar = PersonalNarrative(status="no_active_users", entries=entries)
    card = build_personal_card(_facts(), nar)
    md = _markdown_from(card)
    assert card["header"]["template"] == "wathet"
    assert "团队成员在 Pivot 上均无任何输入和输出" in md


def test_personal_card_fallback_shows_reason():
    nar = PersonalNarrative(
        status="fallback",
        entries=_personal_entries(),
        fallback_reason="ai_error: TimeoutError",
    )
    card = build_personal_card(_facts(), nar)
    md = _markdown_from(card)
    assert card["header"]["template"] == "wathet"
    assert "AI 个人视角生成失败" in md
    assert "TimeoutError" in md


def test_personal_card_disclaimer_mentions_no_perf_eval():
    """免责声明特别强调"不用于绩效评价"——dengke #013 反复强调。"""
    nar = PersonalNarrative(status="ai", entries=_personal_entries())
    md = _markdown_from(build_personal_card(_facts(), nar))
    assert "不用于绩效评价" in md


# --------------------------------------------------------------------------- #
# admin alert card                                                            #
# --------------------------------------------------------------------------- #


def test_admin_alert_failed_renders_per_target_failures_with_names():
    card = build_admin_alert_card(
        alert_type="failed",
        job_name="个人早报",
        job_view="personal",
        error="2 failed: …a966fa55(http_400 …)",
        retry_count=3,
        failures=[
            {"to": "ou_1234", "name": "邓柯", "error": "http_400: invalid receive_id"},
            {"to": "ou_5678", "name": None, "error": "feishu_230015: receive_id invalid"},
        ],
    )
    md = _markdown_from(card)
    # 含汇总 error
    assert "2 failed" in md or "http_400" in md
    # 单条明细行
    assert "邓柯" in md and "ou_1234" in md
    assert "ou_5678" in md
    # 没有 name 时不会出现 None 字面
    assert "None" not in md


def test_admin_alert_failed_truncates_when_many_failures():
    failures = [
        {"to": f"ou_{i:04d}", "name": None, "error": "http_400"}
        for i in range(12)
    ]
    card = build_admin_alert_card(
        alert_type="failed",
        job_name="x", job_view="personal",
        error="12 failed", retry_count=3, failures=failures,
    )
    md = _markdown_from(card)
    # 只列前 8 条 + "…另 4 条未列出"
    assert "ou_0000" in md
    assert "ou_0007" in md  # 第 8 条 (0-indexed 7) 仍在
    assert "ou_0008" not in md
    assert "另 4 条未列出" in md


def test_admin_alert_missed_unchanged_no_failures_section():
    card = build_admin_alert_card(
        alert_type="missed",
        job_name="个人早报", job_view="personal",
        expected_at=datetime(2026, 4, 30, 9, 30, tzinfo=CHINA_TZ),
    )
    md = _markdown_from(card)
    assert "未自动补跑" in md
    assert "未送达明细" not in md  # missed 类型不展示这块
