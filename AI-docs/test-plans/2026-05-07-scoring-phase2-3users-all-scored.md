# Phase 2 多 subject 评分测试 — 三人全员出分版

> 上一版（[2026-05-07-scoring-phase2-3users.md](2026-05-07-scoring-phase2-3users.md)）的实测结果是 `candidates=3 / scored=1 / skipped=2`——李帅和张三因为只各写了 1 条 think 且没人评他们，被 AI 判"证据不足"跳过了。
>
> 本版本**专门为"三人都出分"设计**：每个人都至少 (a) 有 1 个 think 或 act 工作产出 + (b) 被另外两人评论或 verify。这样 AI 拿到的证据每人 ≥ 3 维有信号，不会跳过任何人。

## 测试目标

跑完后 admin/scoring 抽屉应该看到：

```
评分候选 3 人 · 出分 3 人 · 证据不足跳过 0 人
[李帅卡片]
[张三卡片]
[李四卡片]
```

所有归因路径 (`file_creator` / `explicit_mention` / `at_target` / `verify_outcome`) + 高权重 2.0x weight 都被命中。

## 准备

| 项 | 检查方式 | 期望 |
|---|---|---|
| 三个用户都有 pinyin | `/admin/users` | 李帅=`lishuai` / 张三=`zhangsan` / 李四=`lisi` |
| 张三高权重 2.0 | `/admin/scoring/settings` | `张三, weight=2.0, label=CEO` |
| 评分功能开启 | 同上 | ✓ |
| AI 凭证就绪 | `/admin/ai` | OpenRouter / 兼容服务 + 默认 model + timeout ≥ 180s |
| **后端已部署 v2.2** | 跑一下 `git log --oneline \| head -3` 看是否含 v2.2 改动 | 含 `set_skipped_subjects` 方法的版本 |

## A. 输入素材

### 文件类（T1-T10）

#### T1 · **李帅** · think

```
title:    测试评分 - 三人协作客服优化（v3）
category: 测试
type:     think
summary:  客服优化方向规划与风险识别
body:
## 现状

客服流程冗余环节多，影响响应时效。

## 风险评估

1. **A 风险**：字段对齐
2. **B 风险**：接口稳定性
3. **C 风险**：文档同步

## 方向

先攻 A/B 风险（影响 80% 流程），C 风险作为后续推广前置条件。
```

#### T2 · **张三** · think

```
type:    think
summary: 字段对齐技术方案
body:
针对李帅提出的 A 风险，建议采用映射表方案，预留扩展位。
B 风险加重试机制 + 超时退避即可。

C 风险需要先有同步流程节点定义，本期一并设计。
```

#### T3 · **李四** · act

```
type:    act
summary: 完成接口对接（A/B 风险已规避）
body:
按张三方案实施：
- A 风险：通过映射表解决
- B 风险：加重试机制 + 超时退避

C 风险（文档同步）暂未处理，等张三同步流程节点定义。
```

#### T4 · **张三** · verify（针对 T3）

```
type:           verify
summary:        T3 验收 - 部分通过
verifications:
  - target:     <T3 文件路径，UI 下拉选 T3>
    judgement:  failed
    comment:    A/B 处理得很扎实，C 还未处理；待补救后再二次验
```

#### T5 · **李四** · act

```
type:    act
summary: 补充文档同步流程（C 风险已规避）
body:
根据张三反馈，补充 C 风险的处理：
- 引入文档同步流程节点
- 加同步状态字段
```

#### T6 · **张三** · verify（针对 T5）

```
type:           verify
summary:        T5 验收 - 全部通过
verifications:
  - target:     <T5 路径>
    judgement:  passed
    comment:    C 也补上了，方案完整可推广
```

#### T7 · **李帅** · act

```
type:    act
summary: 推广方案规划
body:
基于李四交付的 v1，规划推广到 3 个客户场景：
1. 客户 A：直接套用映射表
2. 客户 B：需要扩展映射规则
3. 客户 C：需要兼容旧字段

方案细节由张三补充实施手册。
```

#### T8 · **张三** · act

```
type:    act
summary: 推广实施手册
body:
基于李帅的推广规划，输出客户接入手册：
- 字段映射 SOP
- 错误处理 checklist
- 上线前自检清单
```

#### T9 · **李四** · verify（一次 verify 两个 target：T7 + T8）

```
type:           verify
summary:        推广方案 + 实施手册一并验收 - 通过
verifications:
  - target:     <T7 路径>
    judgement:  passed
    comment:    推广方向清晰，已在我场景试用
  - target:     <T8 路径>
    judgement:  passed
    comment:    手册可落地，覆盖了实操要点
```

> ⚠️ 如果 UI 不允许一条 verify 写两个 target，就拆成 T9a (verify T7) 和 T9b (verify T8) 两个文件，T10 序号顺延 → T11。

#### T10 · **李帅** · result（触发评分）

```
type:           result
summary:        客服优化 v1 + 推广包一起完成
outcome:        finished
status_change:  executing → finished
body:
## 结果

- v1 实施：A/B/C 三个风险全部规避
- 推广包：方案 + 手册产出，已在 1 个客户场景试用通过

## 后续

进入 v2 规划，可独立 matter 跟踪。
```

---

### 评论类（C1-C9）

⚠️ "评在哪个文件下" + "谁评的" 决定归因。看清两个字段再粘内容。

| # | 在哪 | 谁评 | 内容 | 测什么 |
|---|---|---|---|---|
| **C1** | T1 (李帅 think) | **张三** | "李帅这个分析视角全面，3 个风险点切中要害" | **高权重 2x** → 李帅 judgment 强正向 |
| **C2** | T1 (李帅 think) | **李四** | "3 个风险列得清楚，方向也对" | 默认归因 → 李帅 judgment 弱正向 |
| **C3** | T2 (张三 think) | **李帅** | body: "方案务实可执行，**@张三** 这里再确认下扩展位"<br>mentions: 选 张三 | **at_target** → 张三 + collaboration 信号 |
| **C4** | T3 (李四 act) | **张三** | "李四响应很快，A/B 处理得很扎实" | **高权重 2x** → 李四 collaboration 强正向 |
| **C5** | T5 (李四 act) | **张三** | "改得彻底，方案可以推广到其它项目" | **高权重 2x** → 李四 delivery 强正向 |
| **C6** | T7 (李帅 act) | **张三** | "推广思路清晰，可执行" | **高权重 2x** → 李帅 collaboration 强正向 |
| **C7** | T7 (李帅 act) | **李四** | "已在我负责的场景试用，方案可用" | 默认归因 → 李帅 process 信号 |
| **C8** | T8 (张三 act) | **李帅** | body: "**@张三** 手册写得很实操"<br>mentions: 选 张三 | **at_target** → 张三 + collaboration |
| **C9** | T8 (张三 act) | **李四** | "实施细节清晰，已按手册接入" | 默认归因 → 张三 process 信号 |

### 每人证据预算（确保不被跳过）

| 候选 | think/act 工作产出 | 被他人评价的证据 |
|---|---|---|
| 李帅 | T1 think (matter 规划) + T7 act (推广方案) | C1 (张三高权重) + C2 (李四) + C6 (张三高权重) + C7 (李四) + T9 verify passed |
| 张三 | T2 think (技术方案) + T8 act (实施手册) | C3 (李帅 at_target) + C8 (李帅 at_target) + C9 (李四) + T9 verify passed |
| 李四 | T3 act (实施) + T5 act (返工) | T4 verify failed (张三高权重 verify_outcome 负) + T6 verify passed (verify_outcome 正) + C4 (张三高权重) + C5 (张三高权重) |

每人都有 ≥ 4 条不同来源的证据 + 至少 3 维有信号 → AI 不会判定"全部维度 null"，不会跳过。

---

## B. 触发动作

按顺序操作。每步只做一件事，保存成功再下一步。

### 步骤 0 — 准备

- 三个浏览器 profile / 隐私窗口分别登录李帅 / 张三 / 李四
- 后端日志窗口开着：`journalctl -u team-pivot-web -f` 或 tail server log
- 把 A 段 markdown 放右半屏，UI 放左半屏

### 步骤 1 — 李帅创建 matter

```
登录: 李帅
打开: /new
选:   分类=测试, type=think
粘贴: T1 的 title / summary / body
点:   发布
```

记录 matter URL（或 matter_id）。

### 步骤 2 — 张三补 think

```
登录: 张三
打开: 同 matter
追加: type=think
粘贴: T2 summary / body
点:   发布
```

### 步骤 3 — 李四 act

```
登录: 李四
追加: type=act
粘贴: T3 summary / body
```

### 步骤 4 — 张三 verify failed

```
登录: 张三
追加: type=verify
选:   target = T3 文件
填:   judgement=failed, comment=T4 comment 内容
```

### 步骤 5 — 李四返工 act

```
登录: 李四
追加: type=act
粘贴: T5 summary / body
```

### 步骤 6 — 张三 verify passed

```
登录: 张三
追加: type=verify
选:   target = T5
填:   judgement=passed, comment=T6 comment 内容
```

### 步骤 7 — 李帅 act 推广方案

```
登录: 李帅
追加: type=act
粘贴: T7 summary / body
```

### 步骤 8 — 张三 act 实施手册

```
登录: 张三
追加: type=act
粘贴: T8 summary / body
```

### 步骤 9 — 李四 verify 推广包

```
登录: 李四
追加: type=verify
target 选 T7，judgement=passed，comment=T9 第 1 条
（如果支持一个 verify 文件加多个 target）
target 再加 T8，judgement=passed，comment=T9 第 2 条
否则: 分两次 verify，序号顺延
```

### 步骤 10 — 加全部 9 条评论

按 C1-C9 顺序，每条切换登录用户，定位到对应文件下点"评论"，粘贴内容（C3 / C8 记得在 @ 选择器选张三，不能只在文本里写）。

```
C1: 张三 → T1 评 → 粘贴 C1
C2: 李四 → T1 评 → 粘贴 C2
C3: 李帅 → T2 评 → 粘贴 C3 + @张三
C4: 张三 → T3 评 → 粘贴 C4
C5: 张三 → T5 评 → 粘贴 C5
C6: 张三 → T7 评 → 粘贴 C6
C7: 李四 → T7 评 → 粘贴 C7
C8: 李帅 → T8 评 → 粘贴 C8 + @张三
C9: 李四 → T8 评 → 粘贴 C9
```

### 步骤 11 — 李帅写 result 触发评分

```
登录: 李帅
打开: 同 matter
点:   "完成"按钮
填:   T10 summary / body / outcome=finished
点:   发布
```

⚡ **此刻评分被触发**。后端日志立即出现：

```
scoring trigger enqueued matter=测试评分-三人协作客服优化（v3） primary=<李帅id> candidates=3 actor=lishuai
                                                                                ^^^^^^^^^^^^ 必须 = 3
scoring: calling AI matter=... timeout=180.0s model=...
```

### 步骤 12 — 等评分（1-3 分钟）

监控日志：

```
scoring: AI completed matter=... len=<NNNN>
scoring success matter=... subjects=3 primary_overall=...
                          ^^^^^^^^^^ 必须 = 3
```

如果日志显示 `subjects=2` 或 `subjects=1`，说明 AI 仍跳过了某些候选——见 F 段排错。

### 步骤 13 — 看结果

```
登录: 李帅 (admin)
打开: /admin/scoring
点:   刚才的 matter 行 → 抽屉打开
```

进入 D 段验证。

---

## C. 备选触发（如果实时事件丢了）

```bash
ADMIN_SID=<browser cookie sid>
MATTER_ID=<your matter_id, urlencode 中文>

curl -sX POST "http://localhost:8000/api/admin/scoring/matters/$MATTER_ID/rerun" \
  -H "Cookie: sid=$ADMIN_SID" -H "Content-Type: application/json"
```

---

## D. 预期验证

### 顶部信息行

```
评分候选 3 人 · 出分 3 人 · 证据不足跳过 0 人
```

✅ 三个数字都对：候选 3 / 出分 3 / 跳过 0

### 三张 ScoreCard

按 subject_user_id 排序展示。一张李帅（带"负责人"badge）+ 一张张三 + 一张李四。

#### 李帅 卡片

| 维度 | 期望 | 来源 |
|---|---|---|
| delivery | 中（无直接 verify on 李帅 的 act 是 fail/pass）| T9 verify T7 passed (verify_outcome 正向) |
| accountability | 中-高 | 主动推到 finished |
| judgment | **高** | T1 think 列 3 风险 + result 印证 + C1（张三 2x）+ C2 |
| collaboration | **高** | C6（张三 2x）+ C7（李四）+ T9 李四 verify |
| process | 中-高 | 链路完整 + result + C7 |

evidence 至少含：
- ✅ C1 (高权重 2x → 李帅)
- ✅ T9 verify T7 passed (attribution: verify_outcome → 李帅)
- ✅ C6 (高权重 2x → 李帅)

#### 张三 卡片

| 维度 | 期望 |
|---|---|
| delivery | 中-高（T8 act + T9 verify passed） |
| collaboration | 高（C3 / C8 @张三 + C9） |
| judgment | 高（T2 think 提方案 + 后续 verify 印证） |
| process | 中（T2 think + T8 act + verify 链路） |

evidence 至少含：
- ✅ C3 (attribution: at_target → 张三)
- ✅ C8 (attribution: at_target → 张三)
- ✅ T9 verify T8 passed (verify_outcome → 张三)

#### 李四 卡片

| 维度 | 期望 |
|---|---|
| delivery | 中（T4 failed + T6 passed + C5 张三 2x） |
| accountability | **高**（自驱补救 T5）|
| collaboration | **高**（C4 张三 2x + C5 + C7） |
| judgment | 中（T3/T5 实施合理） |
| process | 高（T3/T5 act + T9 verify 完整） |

evidence 至少含：
- ✅ T4 verify failed (verify_outcome → 李四 delivery 负)
- ✅ T6 verify passed (verify_outcome → 李四 delivery 正)
- ✅ C4 (高权重 2x → 李四)
- ✅ C5 (高权重 2x → 李四)

### 跳过面板（应**不**出现）

如果 UI 显示了 "AI 跳过的候选" 这块灰色面板，说明仍有人被跳过——回到 F 段排错。

---

## E. 验证清单

跑完后逐项打勾：

- [ ] 后端日志 `candidates=3` 且 `subjects=3`
- [ ] run.schema_version = 2
- [ ] subject_scores 数组长度 = 3
- [ ] skipped_subjects 数组长度 = **0**
- [ ] 三张卡片都展示，李帅带"负责人"badge
- [ ] 李帅卡 evidence 含 C1（weight 2.0x 标签）
- [ ] 张三卡 evidence 含 at_target 标签的归因
- [ ] 李四卡 evidence 同时含 verify_outcome 正向 + 负向（T4 + T6）
- [ ] 每张卡至少 3 个维度有数字（非"—"）
- [ ] 没有任何 attribution_basis 为空的 evidence
- [ ] EvidenceDialog 每条 evidence 显示**两个 inline tag**（来源类型 + 归因依据）

---

## F. 排错

| 现象 | 第一步查什么 |
|---|---|
| `subjects=1` 仍只有李四 | check `skipped_subjects` panel；很可能李帅 / 张三的某条 think 没真创建 → timeline 上没有他们的 think/act |
| `subjects=2` 缺李帅 | 李帅可能只创建了 matter 后没追加 T7 act，只有 T1 think → 看 matter timeline 是否有 `lishuai_act` |
| `subjects=2` 缺张三 | 张三可能只写了 verify (T4/T6)，T2 think 或 T8 act 没真创建 → 看 timeline |
| 5 维只有 2-3 维 | 部分维度证据稀薄是可接受的；如要全 5 维必有，加更多 mention / 评论 |
| 自评拒收报错 | v2.2 已放宽 file 自评；如果 comment 自评（评论者 == 文件作者），是期望行为 |
| candidates=3 但 subjects=0 | 全部被 AI 跳过 = 证据全空？检查 timeline 里实际有没有内容 |

---

## G. 反馈

跑完后回复：

1. 后端日志最后一行的 `subjects=N` 值
2. 三张卡片的 overall 分（如有）
3. skipped_subjects 数组内容（应为空）
4. 任何"预期 vs 实际"的偏差

预期 100% 三人都出分，0 跳过。如果仍跳过：(a) 是 AI 判断风格问题（可调 prompt） (b) 还是 timeline 实际缺哪条文件（多账号操作疏漏）。
