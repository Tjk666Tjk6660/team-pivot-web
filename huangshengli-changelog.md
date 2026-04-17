# Changelog

## 2026-04-16 — SKILL.md 重写：从被动等待到主动调用 Runner

### 背景

在 EC 环境中安装 team-pivot 后，LLM 收到用户请求（如"帮我发起一个讨论"）时，不执行任何操作，而是以通用聊天方式回答（问用户"发到哪个飞书群"）。首次使用也不会触发配置引导。

根因：旧 SKILL.md 告诉 LLM"所有 Pipeline 由 Runner 自动执行，你只在 LLM step 和 Fallback 时被调用"，LLM 理解为有另一个程序在处理，自己不需要做任何事。但 EC 不感知 Runner 的存在——对 EC 来说，team-pivot 只是一个 skill，LLM 读到 SKILL.md 后需要自己行动。

### 改动内容

**SKILL.md** — 从"被动等待 Runner 调度"改为"主动调用 Runner 执行"：

1. **新增"如何执行"章节** — 明确给出 Runner 命令模板：`python3 <APP_DIR>/bin/pivot-runner.py run <pipeline-name> --params '{...}'`。LLM 只需调这一条命令，内部的 constructor/destructor/步骤串联/数据传递全由 Runner 保证，不违反 APP v0.4 规范。

2. **新增"可用 Pipeline"路由表** — 列出所有 Pipeline 的触发意图、名称和参数格式。这是 LLM 做意图分类（routing）的依据，对应 APP v0.4 中 routing model 的职责。

3. **新增"处理 Runner 输出"章节** — 告诉 LLM 如何解读 Runner 返回的 JSON（completed → 呈现结果，ConfigNotReady → 引导配置）。

4. **重写"配置初始化"章节** — 旧版说"Runner 的 _constructor 会自动检查"，LLM 不知道触发条件。新版明确：Runner 返回 ConfigNotReady 时引导用户提供 data_space_repo 和 git_token。

5. **保持不变的部分** — frontmatter（name/description/metadata）、Fallback 能力列表、❌ 禁止项、权限与身份、"不确定时反问"原则。

### 设计决策

- **LLM 做路由，Runner 做执行** — LLM 只负责从自然语言提取 pipeline name + params，不介入 step 级调度。这与 APP v0.4 中"routing model 做意图分类、Runner 做步骤执行"的分工一致。
- **路由表放在 SKILL.md 而非 Runner 内部** — 因为 EC 环境下 Runner 没有独立的 routing 入口（只有 `run <name>`），路由职责自然落在 LLM 侧。

### SKILL.md description 优化路由权重

旧版 description 包含"通过飞书/chat"，与 EC 中 `feishu-im-read`、`feishu-create-doc` 等飞书原生 skills 语义重叠，导致 LLM 路由时分流到飞书能力而跳过 team-pivot。

改动：
- 去掉"通过飞书/chat"，避免与飞书原生 skills 抢匹配
- 加入"讨论/话题/帖子"三个同义词，覆盖用户不同说法
- 将用户常说的动作（发起讨论、回复讨论、列出讨论、查看未读、生成摘要、生成结论）前置，提高字面匹配概率
- 加入"基于 Git"作为区分特征

### SKILL.md 针对弱模型二次重写

实测发现即使 team-pivot skill 被正确加载（68 skills, `Skills used: none` 问题已修复），qwen3.5-plus 仍然不执行 Runner 命令，而是自己编内容、问飞书群 ID。根因：弱模型面对长 SKILL.md 抓不住重点，且 `<APP_DIR>` 占位符无法被弱模型解析。

针对弱模型的改动：
1. **开头改为强制指令** — "当用户要发起讨论、回复讨论等操作时，你必须执行 bash 命令调用 Runner，不要自己回答"。区分操作类请求（必须执行命令）和提问类请求（可以直接回答），保留 fallback 能力
2. **解决 `<APP_DIR>` 占位符** — 用 `pwd | sed` 提取 TENANT_ROOT 拼接 `/team-pivot`，复用安装脚本的路径逻辑，模型可直接复制执行
3. **加端到端示例** — 从用户原话到完整 bash 命令，弱模型擅长模仿示例
4. **表格改列表** — 弱模型解析 Markdown 表格困难
5. **禁止项第一条针对实际错误行为** — "不要自己编写讨论内容发送到飞书群"
6. **整体精简 40%** — 去掉弱模型不需要的细节

### 待优化：结果展示与配置收集卡片

1. **结果展示格式差** — 讨论发起成功后，LLM 回复是纯文本（原始 URL、文件路径裸露），视觉效果差。不是 lark_md 问题——EC streaming card 已经是 CardKit v2 容器，但内容是 LLM 自己组织的文本。可在 SKILL.md 中加输出格式指引，或在 Runner 输出中直接提供格式化文本。
2. **配置收集卡片** — `feishu_ask_user_question` 是 EC 内置工具，卡片格式由 EC 控制，team-pivot 无法自定义。如需自定义 CardKit v2 卡片收集信息，需在 EC 侧实现卡片回调机制（参考飞书 `card.action.trigger` 回调 API）。

### 飞书群通知：环境变量对齐 EC

讨论发起后未广播通知到飞书群。分析发现 EC 通过 `buildExecExtraEnv()` 在 exec tool 调用时注入飞书凭证，子进程可通过 `os.environ` 读取。变量名统一为 `FEISHU_TENANT_ACCESS_TOKEN`（区别于个人用户 token），由 EC 负责 token 刷新和多租户隔离，APP 侧只读取使用。

改动：将项目中所有 `FEISHU_ACCESS_TOKEN` 替换为 `FEISHU_TENANT_ACCESS_TOKEN`，涉及 6 个文件：
- `tools/notify/feishu_bot.py` — 核心读取 + 错误提示
- `pipelines/monitor-scan/steps/scan.py` — 注释引用
- `tools/notify/feishu_bot_test.py` — 测试
- `pipelines/discuss-new/steps/publish_test.py` — 测试
- `pipelines/discuss-reply/steps/publish_test.py` — 测试
- `pipelines/monitor-scan/steps/scan_test.py` — 测试


### 待讨论：通知机制方案选择

`FEISHU_TENANT_ACCESS_TOKEN` 可以通过 EC 的 bash-tool extraEnv 机制（per-invocation 构建）传入 Python 子进程。但 `PIVOT_USER_ID` 是动态变量（每次请求对应不同用户），EC 是多租户多用户并发平台，无法通过 Node `process.env` 注入——需要 EC 的 `buildExecExtraEnv` 在每次 tool invocation 时根据请求上下文动态构建。此外 `PIVOT_USER_ID` 是 team-pivot 自定义的变量名，EC 作为通用平台不会为特定 skill 定制变量名，team-pivot 应适配 EC 提供的通用用户标识变量。

备选方案：通知卡片改为通过 pipeline 输出特殊字段（如 `notification`），交由外层 LLM 调用 EC 的飞书发卡片接口。该方案下：
- token 和用户身份由 EC 内部管理，APP 不需要感知
- 但需要 SKILL.md 指引 LLM 识别 notification 字段并发送
- 且 LLM 的执行可靠性依赖模型能力（弱模型可能跳过通知步骤）

两个方案各有 trade-off，待与 EC 侧对齐 extraEnv 的变量约定后决定。

### 待优化

- **EC skill 数量过多导致路由失败** — 实测发现 agent 加载 68 个 skills 时，qwen3.5-plus 在意图分类阶段未能将"帮我发起一个讨论"匹配到 team-pivot（日志显示 `Skills used: none`），而是用通用知识回答。team-pivot 的 SKILL.md 已正确加载（`snapshot skills count = 68`，包含 team-pivot），但 LLM 被其他 skills（尤其是飞书系列）干扰，跳过了 team-pivot 直接走了通用飞书逻辑。可能的优化方向：缩小 agent 的 skillFilter 只保留必要 skills；或优化 team-pivot 的 description 提高匹配权重；或在 EC 侧改进 skill 路由算法（如分层匹配）。
