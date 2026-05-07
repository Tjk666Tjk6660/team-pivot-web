# Phase 2 多 subject 评分测试 — 3 人手动剧本

> 输入素材和触发动作分开两段。先把 A 段的所有文本都准备好（屏幕一边开着这文档随时复制），再按 B 段的步骤依次操作。

## 准备

| 项 | 检查方式 | 期望 |
|---|---|---|
| 三个用户已注册并填了 pinyin | `/admin/users` 看 | 李帅=`lishuai` / 张三=`zhangsan` / 李四=`lisi`（pinyin 必须能 resolve） |
| 张三高权重 2.0 已配 | `/admin/scoring/settings` 高权重发言人 | `张三, weight=2.0, label=CEO`（label 任意，但 weight 必须 2.0） |
| 评分功能开关 | `/admin/scoring/settings` 总开关 | ✓ 启用 |
| AI 凭证 | `/admin/ai` | OpenRouter / 兼容服务的 key + base_url + 默认 model |
| 浏览器多账号 | 三个隐私窗口 / 三个 profile | 每个独立 cookie 池 |
| 后端在跑 | `journalctl -u team-pivot-web -f` 看日志 | 触发评分时能立即看到 `scoring trigger enqueued ...` |

---

## A. 输入内容素材

### 文件类（T 系列）—— 各人各自登录后追加到 matter

#### T1 · 李帅 · think（**新建 matter 时填这条**）

```
title:    测试评分系统 - 客服优化
category: 测试
type:     think
summary:  客服优化方向初步思考
body:
## 现状

客服流程冗余环节多，用户体验差。

## 风险评估

1. **A 风险**：字段对齐
2. **B 风险**：接口稳定性
3. **C 风险**：文档同步
```

#### T2 · 张三 · think

```
type:    think
summary: 字段对齐方案补充
body:
针对 A 风险，建议采用映射表方案，预留扩展位以支持后续字段变更。
```

#### T3 · 李四 · act

```
type:    act
summary: 完成接口对接，A/B 风险已规避
body:
按张三方案实施：
- A 风险：通过映射表解决
- B 风险：加重试机制 + 超时退避

C 风险（文档同步）暂未处理，待下一阶段。
```

#### T4 · 张三 · verify（针对 T3）

```
type:           verify
summary:        验收 - 部分通过
verifications:
  - target:     <T3 的 file 路径，UI 里下拉选 T3>
    judgement:  failed
    comment:    C 风险（文档同步）没处理，需补救
```

#### T5 · 李四 · act

```
type:    act
summary: 补充文档同步流程
body:
根据张三反馈，补充 C 风险的处理：
- 引入文档同步流程节点
- 加同步状态字段
```

#### T6 · 张三 · verify（针对 T5）

```
type:           verify
summary:        验收 - 全部通过
verifications:
  - target:     <T5 的 file 路径>
    judgement:  passed
    comment:    C 也补上了，整体方向对
```

#### T7 · 李帅 · result（触发评分）

```
type:           result
summary:        客服优化 v1 完成
outcome:        finished
status_change:  executing → finished
body:
## 结果

所有风险已规避，方案已通过验证可推广。

下一阶段：
- 推广到其它客户场景
- 沉淀字段映射模板
```

---

### 评论类（C 系列）—— 留在指定文件下

⚠️ "评论位置 = 在哪个文件下评"决定归因。看清"在 T 几下"再复制内容。

#### C1 · 在 T1（李帅 think）下，**李帅自己**评论 — 测自评拒收

```
"我这个想法很好"
mentions: 无
```

预期：被 schema 拒收，不进任何人的证据链。

#### C2 · 在 T1（李帅 think）下，**李四**评论 — 测默认归因

```
"李帅这个 think 想得很清楚，3 个风险点切中要害"
mentions: 无
```

预期：默认 file_creator 归因 → 入李帅的 judgment 证据链。

#### C3 · 在 T2（张三 think）下，**李四**评论 — 测 explicit_mention

```
"张三这方案考虑得周到，李四需要重点关注 C 风险"
mentions: 无（不要在 @ 选择器里加；让文本显式提到"李四"）
```

预期：文本里点名李四 → 应归李四不是张三（attribution: explicit_mention）。

#### C4 · 在 T3（李四 act）下，**张三**评论 — 测高权重 2.0x

```
"李四响应很快，A/B 处理得很扎实"
mentions: 无
```

预期：张三是高权重发言人（weight=2.0）→ 这条 evidence 的 weight_applied = 2.0，confidence 不低于 high。

#### C5 · 在 T5（李四 act）下，**张三**评论 — 再测高权重正向

```
"改得彻底，方案可以推广到其它项目"
mentions: 无
```

#### C6 · 在 T5（李四 act）下，**李帅**评论 — 测 at_target

```
body:     "@李四 后续推广方案再单独聊下"
mentions: 在 @ 选择器里选 李四
```

预期：mentions 数组里有李四 → attribution: at_target，归李四的 collaboration 维度。

---

## B. 触发动作

按顺序执行。每一步只做一件事；上一步保存成功再做下一步。

### 步骤 0 — 准备多账号

- 浏览器开三个 profile / 隐私窗口，分别登录李帅 / 张三 / 李四
- 把本文档放在右半边屏，左半边操作 UI
- 准备好后端日志窗口（`journalctl -u team-pivot-web -f`）

### 步骤 1 — 李帅创建 matter

```
登录: 李帅
打开: /new
选:   分类=测试, type=think
粘贴: T1 的 title / summary / body
点:   发布
```

回到 matter 详情页，复制 URL 里的 matter_id 备用（后面看日志要对照）。

### 步骤 2 — 张三补充 think

```
登录: 张三
打开: 步骤 1 创建的 matter 详情页
点:   "追加文件" 或时间线下方的添加按钮
选:   type=think
粘贴: T2 的 summary / body
点:   发布
```

### 步骤 3 — 李四完成 act

```
登录: 李四
打开: 同 matter
追加: type=act
粘贴: T3 的 summary / body
点:   发布
```

### 步骤 4 — 张三 verify failed

```
登录: 张三（仍在）
打开: 同 matter
追加: type=verify
选:   verifications.target = T3 的文件
填:   judgement=failed, comment=T4 的 comment
点:   发布
```

### 步骤 5 — 李四返工 act

```
登录: 李四
追加: type=act
粘贴: T5 的 summary / body
点:   发布
```

### 步骤 6 — 张三 verify passed

```
登录: 张三
追加: type=verify
选:   target=T5
填:   judgement=passed, comment=T6 的 comment
点:   发布
```

### 步骤 7 — 加评论（C1-C6）

按 C 系列每一条，登录指定用户 → 在指定文件下点"评论 / 留言" → 粘贴内容 → 发布。

```
C1: 登录 李帅 → T1 评论 → 粘贴 C1
C2: 登录 李四 → T1 评论 → 粘贴 C2
C3: 登录 李四 → T2 评论 → 粘贴 C3
C4: 登录 张三 → T3 评论 → 粘贴 C4
C5: 登录 张三 → T5 评论 → 粘贴 C5
C6: 登录 李帅 → T5 评论 → 粘贴 C6 + @ 选择器选 李四
```

### 步骤 8 — 李帅触发评分（写 result）

```
登录: 李帅
打开: 同 matter
点:   "完成"按钮（matter 状态机会推到 result + finished）
填:   T7 的 summary / body / outcome=finished
点:   发布
```

⚡ **此刻评分被触发**——后端日志应立即出现：

```
scoring trigger enqueued matter=<matter_id> primary=<李帅 id> candidates=3 actor=lishuai
                                                              ^^^^^^^^^^^^ 必须 = 3
scoring: calling AI matter=... timeout=180.0s model=...
```

如果 `candidates < 3`：用户 pinyin 没全部解析上，回到准备阶段查 `/admin/users`。

### 步骤 9 — 等评分完成

时间：1-3 分钟（视 AI model 速度）。

监控：
- 日志看 `scoring success matter=... subjects=3 primary_overall=...`
- 或者刷新 `/admin/scoring`，看刚那条 matter 状态从 ⏳ 变 ✅

### 步骤 10 — 看结果

```
登录: 李帅
打开: /admin/scoring
点:   刚才的 matter 行 → 抽屉打开
```

进入 D 段验证。

---

## C. 触发评分参考（如果忘了点完成）

如果步骤 8 之后过了几分钟没看到评分排队（可能 trigger 没被订阅 / 事件丢了），用 admin rerun 备份触发：

```bash
ADMIN_SID=<browser DevTools cookie sid>
MATTER_ID=<your matter_id>

curl -sX POST "http://localhost:8000/api/admin/scoring/matters/$MATTER_ID/rerun" \
  -H "Cookie: sid=$ADMIN_SID" -H "Content-Type: application/json"
```

期望返回 `{"ok": true, "queued": true, "message": "已入队，等待 worker 处理（约 1-3 分钟）"}`。

---

## D. 预期验证

### 顶部

- ✅ 浅灰提示框 **"评分候选 3 人"**
- ✅ 三张 ScoreCard：
  - 李帅（带"**负责人**"badge）
  - 张三
  - 李四

### 李帅 卡片

| 维度 | 期望 | 证据来源 |
|---|---|---|
| delivery | — | 李帅没写 act，没自己 verify |
| accountability | 中-高 | result 收口、推到完成 |
| judgment | 中-高（3.5+） | think 列出 3 风险 + result 印证 + C2 评论印证 |
| collaboration | 中 | C6 @李四 |
| process | 高 | 链路完整 |

证据 evidence 列表必须包含：
- ✅ C2（李四评李帅 think）—— attribution: **文件作者**
- ❌ **不应**有 C1（李帅自评）—— 自评拒收

### 张三 卡片

| 维度 | 期望 |
|---|---|
| delivery | — | 张三没写 act |
| judgment | 高 | T2 think 提出方案 |
| collaboration | 中 | T4 / T6 给李四反馈 |
| process | 中 | 参与了链路 |

证据列表**不应**包含：
- ❌ C3（李四在 T2 下评"李四需要重点关注"）—— 这条文本明确点名李四，应该归李四不归张三

### 李四 卡片（重点检查）

| 维度 | 期望 |
|---|---|
| delivery | 中（先 failed 后 passed，被高权重正向 C5 拉一下） | 多条证据 |
| accountability | **高** | 自驱补救 C 风险（T5） |
| collaboration | **高** | C4 张三高权重 + C6 李帅 @ + C3 explicit |
| judgment | 中 | T3 / T5 实施合理 |
| process | 高 | 链路完整 |

证据列表必须包含**至少 6 条**：
- ✅ T4 verify failed → delivery 负向，attribution: **验收动作**
- ✅ T6 verify passed → delivery 正向，attribution: **验收动作**
- ✅ C4 张三"响应很快" → attribution: **文件作者**，**weight 2.0x** 标签
- ✅ C5 张三"改得彻底" → attribution: **文件作者**，**weight 2.0x**
- ✅ C3 李四在张三 think 下被点名 → attribution: **文本点名**
- ✅ C6 李帅 @李四 → attribution: **@ 提及**

### EvidenceDialog 显示规范

每条 evidence 行应该显示**两个 inline tag**：
- 第一个：来源类型（**评论** / **文件 · verify** / **评价**）
- 第二个：归因依据（**文件作者** / **文本点名** / **@ 提及** / **转交原因** / **验收动作**）

如果旧 run（schema_version=1）跑出来，归因 tag 可能为空——这是向后兼容（attribution_basis=null）。

---

## E. 验证清单

逐项打勾：

- [ ] 步骤 8 后日志显示 `candidates=3`
- [ ] run.status = success（不是 failed）
- [ ] run.schema_version = 2（在元信息里看）
- [ ] subject_scores 数组长度 = 3
- [ ] 李帅卡 evidence 不含 C1（自评）
- [ ] 李四卡 evidence 含 C3（explicit_mention 归因）
- [ ] 张三卡 evidence **不**含 C3
- [ ] 李四卡 evidence 至少 1 条 weight 2.0x
- [ ] 李四卡 evidence 含 verify_outcome 标签的 T4 / T6
- [ ] 李四 5 个维度都有分（不是 "—"）
- [ ] 每条 evidence 显示两个 inline tag

---

## F. 排错

| 现象 | 第一步查什么 |
|---|---|
| 候选数 = 1 | 用户 pinyin 没解析上；`/admin/users` 检查 |
| 候选数 = 2 缺张三 | 张三只写了 verify？看 timeline 是不是真有 T2 think |
| 候选数 = 2 缺李帅 | 李帅没 think 也没 act？检查 T1 是 think 不是 result |
| run failed: schema_error: self-evaluation | 期望行为；看 error 哪条命中 |
| run failed: subject_not_in_candidates | AI 给了候选集外的人；看 worker 日志 candidates 字段 |
| 5 维只有 3 维 | 部分维度证据不足是可接受的；如要全 5 维必有，加更多多样化评论 |
| EvidenceDialog 没新两个 tag | 前端旧编译；`pnpm dev` 重启 |
| admin rerun 后仍单 subject | 老 build；确认 admin_scoring.py rerun 端点已含 `resolve_candidates(...)` |

---

## G. 反馈

跑完后请告知：
- 实际拿到的 candidates 数
- 三张卡片的 overall 分
- 任何"预期 vs 实际"差异

我可以根据偏差调整 prompt 规则或 schema 校验。
