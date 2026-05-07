# Phase 2 多 subject 评分 — 端到端测试用例

> 验证 commit 之前的 Phase 2 工作（schema 多行 + trigger candidate set + worker 多 subject + UI 多卡片 + EvidenceDialog 新两列）在真实链路上能跑通

## 准备

1. **后端在跑**：`uv run uvicorn server.app:app --reload` 或 systemd 服务
2. **前端在跑**：`cd web && pnpm dev`（编译 v2.1 类型 + 验证 multi-subject UI）
3. **AI 凭证就位**：admin 后台 `/admin/ai` 配 OpenRouter key + base_url + 默认 model
4. **评分功能开启**：admin 后台 `/admin/scoring/settings` 总开关 `✓ 启用`，超时 ≥ 180s
5. **三个用户存在**（按 pinyin）：
   - `zhangsan` — owner / 主候选
   - `lisi` — verifier
   - `wangwu` — 实施者
   - （可选）`dengke` — 高权重发言人，admin 在"高权重发言人"里加权 1.5x

如果用户名称对不上你的实际数据，把下面所有 pinyin 替换成你环境里真实存在的三个 pivot_user。

## 测试 Matter 设计

构造一个 matter，让多 subject 评分链所有规则都被触发：

| 序号 | 类型 | creator | 内容简述 | 触发的规则 |
|---|---|---|---|---|
| 001 | think | zhangsan | "客服优化方向" + 列出 3 个风险 | 候选 +1（zhangsan） |
| 002 | act | lisi | "完成接口对接" | 候选 +1（lisi） |
| 003 | act | wangwu | "补充字段映射" | 候选 +1（wangwu） |
| 004 | verify | lisi | verify 003 的 act，judgement=**failed** | wangwu delivery 隐式负向 (verify_outcome) |
| 005 | act | wangwu | "返工：修正字段" | wangwu 补救 |
| 006 | verify | lisi | verify 005，judgement=**passed** | wangwu delivery 弱正向 |
| 007 | result | zhangsan | outcome=**finished** | **触发评分** |

关键评论（在文件下做的留言）：

| 留在哪 | 评论者 | 内容 | 期望归因 |
|---|---|---|---|
| 002（lisi 的 act）下 | dengke | "lisi 这次响应很快" | → lisi（默认归文件作者；dengke 是高权重 → confidence high） |
| 002（lisi 的 act）下 | wangwu | "**zhangsan** 这个 think 想得很清楚" | → zhangsan（**explicit_mention** 跳过文件作者归因） |
| 003（wangwu 的 act）下 | wangwu | "我自己评：做得不错" | **拒收**（self-eval comment） |
| 005（wangwu 的 act）下 | dengke | "wangwu 改得彻底" | → wangwu（dengke 高权重） |

## 步骤

### 1. 创建 matter

通过 Pivot 网页前端 `/new` 或 MCP `create_matter`（用 `mcp__pivot__create_matter` 在 Claude Code 里直接跑）：

```
title: 客服优化系统 Phase2 评分测试
category: 测试评分
initial_file:
  type: think
  summary: 客服优化系统方向，识别 3 个风险
  body: |
    ## 现状
    客服流程冗余环节多
    ## 风险
    1. 字段对齐
    2. 接口超时
    3. 文档同步
```

### 2. 用其它账号登录追加 act / verify

> ⚠️ 这一步是**真实多账号操作**——你需要让 lisi / wangwu 各自登录追加文件，因为 Pivot 不允许冒名顶替。如果环境里没有这三个账号、又不方便切换登录，**可以跳到附录方案 B**（用 SQL + YAML 直接 seed）。

按上面表 002 → 006 的顺序，每个用户用自己的账号给 matter 加 act / verify 文件 + 写预定的评论。

### 3. zhangsan 写 result（outcome=finished）

zhangsan 登录，给 matter 追加 result 文件，outcome 选 `finished`。

⚡ **此刻评分被触发**——后端日志应该出现：
```
scoring trigger enqueued matter=客服优化系统Phase2评分测试 primary=<zhangsan_id> candidates=3 actor=zhangsan
scoring: calling AI matter=... timeout=180.0s model=...
```

等 1-3 分钟（AI 调用时间）。

### 4. 看评分结果

打开管理后台 `/admin/scoring`：

**A. 列表 tab（"评分"）**
- 应看到一行 "客服优化系统 Phase2 评分测试"，状态 ✅ 成功
- 点这一行进详情

**B. 详情抽屉**
- 顶部 RunHeader 显示 run_id / model / tokens / 触发：自动
- 下面有一个浅色提示框：**"评分候选 3 人"** + "候选集来自 timeline 中所有 think / act 文件的作者"
- 三张 ScoreCard 堆叠，按"主候选优先 + subject_user_id ASC"排序：
  1. **zhangsan**（带"负责人"小标签）
  2. lisi
  3. wangwu

每张卡片显示：⭐ 总分 + confidence + 五维度条 + "查看证据 (N)" / "✏ 人工修正" 两个按钮。

### 5. 点开"查看证据"逐个验证

#### zhangsan 的证据
- 至少有一条 evidence `quote: "zhangsan 这个 think 想得很清楚"`
  - 来源类型 tag：**评论**
  - 归因依据 tag：**文本点名**
  - 作者：wangwu
- 不应该有任何 `source_comment_author=zhangsan` 的证据（自我评价拒收 — 我们没让他自评，但也防止 AI 误认）

#### lisi 的证据
- 至少一条 evidence 指向 dengke "响应很快"
  - 来源类型：**评论**
  - 归因依据：**文件作者**（默认归文件作者，因为 dengke 评论挂在 lisi 的 act 下）
  - weight 标签：`weight 1.5x`

#### wangwu 的证据
- 一条隐式评价：verify failed → delivery 负向
  - 来源类型：**文件 · verify**
  - 归因依据：**验收动作**（verify_outcome）
- 一条来自 dengke "改得彻底"的正向评价
  - 来源类型：**评论**
  - 归因依据：**文件作者**

#### 全部
- 没有任何 evidence 标记 `attribution_basis=null`（v2.1 prompt 要求 AI 必填）
- 没有 wangwu 自评的那条 comment（已被 schema 拒收，AI 输出会跳过它，或者整个 run 标 failed 含 `self-evaluation`）

## 预期判定表

| 验证点 | 通过标准 | 不通过的可能原因 |
|---|---|---|
| run 状态 | `success` 且 schema_version=2 | 看 run.error；常见：AI 超时 / schema_error / 自我评价拒收 |
| 候选人数 | 3 | trigger 没识别到所有 think/act 作者；查 trigger 日志 |
| zhangsan 卡片显示"负责人"badge | ✅ | matter.owner pinyin 解析失败 |
| 多 subject 提示框出现 | "评分候选 3 人" 字样可见 | subject_scores 长度 ≤ 1，schema 没解锁多行 |
| EvidenceDialog 显示**两条** inline tag（来源类型 / 归因依据） | 都有 | attribution_basis 未传到前端，或新前端类型未编译 |
| wangwu delivery 维度 ≤ 3 | 是 | verify failed 的隐式归因没生效；prompt 规则有问题 |
| zhangsan 收到 wangwu 那条 explicit_mention 证据 | 是 | AI 没按 explicit_mention 决策链归因 |
| 自我评价不入 wangwu 证据 | 不存在 source_comment_author=wangwu 的 evidence | self-eval rule 没生效；查 run.error 是否含 `self-evaluation` |
| 历史 v1 run 仍能显示 | ✅ | 老 run 的 schema_version=1，UI 应回退单卡片但仍渲染 |

---

## 附录方案 B：直接 seed YAML（不用三账号登录）

如果切账号麻烦，可以直接写 matter index YAML + .md 占位 + 用 admin rerun 端点触发。这个路径**绕过 publish.py / notify**，但完整验证 scoring 模块（含 v2.1 多 subject）。

### 前置确认

```bash
# 1. 拿到真实 workspace 路径（在 server/app.py 里 workspace=cfg.data_dir/git）
sqlite3 /opt/team-pivot-web/data.db "SELECT key, value FROM settings WHERE key LIKE 'workspace%' OR key LIKE 'data%'" 2>/dev/null
# 或直接看你的部署：通常是 ~/.local/share/team-pivot-web/git 或 /opt/team-pivot-web/data/git
WORKSPACE=/opt/team-pivot-web/data/git   # ← 改成你环境的实际路径

# 2. 确认 4 个用户存在 + 有 pinyin
sqlite3 /opt/team-pivot-web/data.db \
  "SELECT id, pinyin FROM pivot_user WHERE pinyin IN ('zhangsan','lisi','wangwu','dengke')"
# 期望看到 4 行；少了的话先在 admin/users 里建用户并设 pinyin

# 3. 确认 scoring.enabled=1 + ai 凭证就绪
sqlite3 /opt/team-pivot-web/data.db \
  "SELECT key, substr(value,1,20) || '…' FROM settings WHERE key LIKE 'scoring%' OR key LIKE 'ai.%'"

# 4. 拿一个 admin sid（登录后看 cookie）
ADMIN_SID=<paste from browser DevTools>
```

### 写 YAML + .md 占位

```bash
MATTER=客服优化系统-phase2
mkdir -p "$WORKSPACE/index"
mkdir -p "$WORKSPACE/discussions/测试评分/$MATTER"

cat > "$WORKSPACE/index/$MATTER.index.yaml" <<'EOF'
matter:
  id: 客服优化系统-phase2
  title: 客服优化系统 Phase2 评分测试
  current_status: finished
  owner: zhangsan
  created_at: '2026-05-06T10:00:00+08:00'
  updated_at: '2026-05-06T18:00:00+08:00'
timeline:
  - file: discussions/测试评分/客服优化系统-phase2/001_zhangsan_think_x.md
    type: think
    creator: zhangsan
    summary: 客服优化方向
    created_at: '2026-05-06T10:00:00+08:00'
    comments:
      - author: wangwu
        body: zhangsan 这个 think 想得很清楚
        created_at: '2026-05-06T10:30:00+08:00'
  - file: discussions/测试评分/客服优化系统-phase2/002_lisi_act_x.md
    type: act
    creator: lisi
    summary: 接口对接
    created_at: '2026-05-06T11:00:00+08:00'
    comments:
      - author: dengke
        body: lisi 这次响应很快
        created_at: '2026-05-06T11:30:00+08:00'
  - file: discussions/测试评分/客服优化系统-phase2/003_wangwu_act_x.md
    type: act
    creator: wangwu
    summary: 补充字段映射
    created_at: '2026-05-06T12:00:00+08:00'
    comments:
      - author: wangwu
        body: 我自己评：做得不错
        created_at: '2026-05-06T12:30:00+08:00'
  - file: discussions/测试评分/客服优化系统-phase2/004_lisi_verify_x.md
    type: verify
    creator: lisi
    summary: verify failed
    created_at: '2026-05-06T13:00:00+08:00'
    verifications:
      - target: discussions/测试评分/客服优化系统-phase2/003_wangwu_act_x.md
        judgement: failed
        comment: 字段映射有问题
  - file: discussions/测试评分/客服优化系统-phase2/005_wangwu_act_x.md
    type: act
    creator: wangwu
    summary: 返工修正字段
    created_at: '2026-05-06T14:00:00+08:00'
    comments:
      - author: dengke
        body: wangwu 改得彻底
        created_at: '2026-05-06T14:30:00+08:00'
  - file: discussions/测试评分/客服优化系统-phase2/006_lisi_verify_x.md
    type: verify
    creator: lisi
    summary: verify passed
    created_at: '2026-05-06T15:00:00+08:00'
    verifications:
      - target: discussions/测试评分/客服优化系统-phase2/005_wangwu_act_x.md
        judgement: passed
        comment: ok
  - file: discussions/测试评分/客服优化系统-phase2/007_zhangsan_result_x.md
    type: result
    creator: zhangsan
    summary: 流程优化达成
    outcome: finished
    created_at: '2026-05-06T18:00:00+08:00'
    status_change:
      from: executing
      to: finished
EOF

# 创建 .md 占位（worker 会调 read_post 读 body；frontmatter 必须有 type/author/created）
write_post() {
  local seq_pin_kind=$1   # 形如 001_zhangsan_think
  local kind="${seq_pin_kind##*_}"
  local pinyin=$(echo "$seq_pin_kind" | cut -d_ -f2)
  local f="$WORKSPACE/discussions/测试评分/$MATTER/${seq_pin_kind}_x.md"
  cat > "$f" <<EOM
---
type: $kind
author: $pinyin
created: '2026-05-06T10:00:00+08:00'
---

(测试占位正文 — $kind by $pinyin)
EOM
}

for f in 001_zhangsan_think 002_lisi_act 003_wangwu_act 004_lisi_verify \
         005_wangwu_act 006_lisi_verify 007_zhangsan_result; do
  write_post "$f"
done
```

### 触发 + 观察

```bash
# 5. admin rerun 触发评分（v2.1 已修：admin rerun 现在也解析候选集，会走多 subject 路径）
curl -sX POST "http://localhost:8000/api/admin/scoring/matters/$MATTER/rerun" \
  -H "Cookie: sid=$ADMIN_SID" -H "Content-Type: application/json"
# 期望返回 { "ok": true, "matter_id": "...", "queued": true, ... }

# 6. 后端日志应该立即出现：
#   scoring admin rerun enqueued matter=客服优化系统-phase2 subject=<owner_id> candidates=3 admin=<your_id>
#                                                                       ^^^^^^^^^^^^ 关键：必须 ≥ 3 才证明走了多 subject
#   scoring: calling AI matter=... timeout=180.0s

# 7. 等 1-3 分钟，查 run
curl -s "http://localhost:8000/api/admin/scoring/runs?matter_query=$MATTER&limit=5" \
  -H "Cookie: sid=$ADMIN_SID" | python -m json.tool

# 8. 拿到 run_id 后看详情
RUN_ID=<copy from step 7>
curl -s "http://localhost:8000/api/admin/scoring/runs/$RUN_ID" \
  -H "Cookie: sid=$ADMIN_SID" | python -m json.tool
# 期望看到：
# - run.schema_version == 2
# - subject_scores 是 3 个元素的数组
# - 每个 subject 有自己的 evidence
# - 至少一条 evidence 的 attribution_basis = "verify_outcome"（wangwu delivery）
# - 至少一条 attribution_basis = "explicit_mention"（zhangsan）
```

### 直接打开 admin UI 看可视化

`http://localhost:5173/admin/scoring` → 找到刚才的 matter → 点行进抽屉，应该看到：

- 浅灰色提示框 "评分候选 3 人"
- 三张 ScoreCard 堆叠：zhangsan（带"负责人"badge） / lisi / wangwu
- 每张卡的"查看证据"打开 EvidenceDialog，evidence 行显示**两个 inline tag**（来源类型 + 归因依据）

> ⚠️ Phase 2 之前 admin rerun 是**单 subject**（漏填 `candidate_user_ids`，会被 worker fallback 成 `{owner}`），现已修复。如果你跑出来仍然只有 1 张卡片：检查 `candidates=N` 日志、用户是否都 resolve 到 pivot_user。

---

## 排错快速指引

| 现象 | 第一步查什么 |
|---|---|
| 没看到 run | `journalctl` 看 trigger 日志：`scoring trigger ...` 是否有"enqueued" |
| run 状态 failed + error 含 `subject_not_in_candidates` | AI 给了候选集外的 subject；prompt 没接对，看 worker 日志的 candidates 数量 |
| run 状态 failed + error 含 `self-evaluation` | 期望行为；说明 schema 拒收成功 |
| run 状态 failed + error 含 `pydantic_invalid` | AI 输出 JSON 不对；试改 model 或减小 candidate set 测试 |
| 详情页只看到一张卡片但 timeline 有多个作者 | subject_scores.length === 1：trigger 解析候选失败，或 AI 只输出了 1 行 |
| EvidenceDialog 没新 tag | 前端没重启 / `web/node_modules` 没装；老 type 编译产物缓存 |
| 多 subject 卡片渲染但点"查看证据"空白 | `subject_scores[i].evidence` 为空——后端 evidence 没按 subject_user_id 切分 |
