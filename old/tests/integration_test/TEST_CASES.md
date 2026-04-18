# 真实集成测试用例文档

> 目的: 使用真实 Git 仓库，端到端验证讨论帖完整生命周期。

## 两种运行方式

### 方式 A：pytest + ClaudeCLIBackend（终端手动执行）

> 文件: `tests/integration_test/test_real_discuss_flow.py`

```bash
pytest tests/integration_test/test_real_discuss_flow.py -v -s
```

| 项目 | 要求 |
|------|------|
| Claude CLI | 已安装并完成认证 |
| 网络 | 可访问 GitHub |
| Git 仓库 | `https://github.com/hashSTACS-Global/test-discuss.git` |
| LLM 后端 | `ClaudeCLIBackend`（调用 `claude -p`，禁止 mock） |
| 输出目录 | `tests/test_output/real_flow_<YYYYmmdd_HHMMSS>/` |

**注意：** 此方式通过 `claude -p` 子进程调用 LLM，**不能在 Claude Code 会话内执行**（会导致 Claude 嵌套调用自己）。必须在普通终端中运行。

### 方式 B：step_runner 分步编排（Claude Code 自编排）

> 文件: `tests/integration_test/step_runner.py`

Claude Code 自身充当 LLM 后端，逐步执行 pipeline：

```bash
# 1. 初始化
python step_runner.py init --pipeline <name> --workspace <repo> --user-id <user> \
    --params '<json>' --context run_ctx.json

# 2. 执行下一步（自动识别 code / llm）
python step_runner.py next --context run_ctx.json
#   → code 步骤: 直接执行，输出结果
#   → llm 步骤: 输出 {"action":"need_llm","prompt":"..."}

# 3. 注入 LLM 响应（仅 llm 步骤后）
python step_runner.py respond --context run_ctx.json --response '<json>'

# 4. 重复 next 直到 {"action":"done"}

# 查看状态
python step_runner.py status --context run_ctx.json
```

| 项目 | 要求 |
|------|------|
| Claude CLI | **不需要** |
| 网络 | 可访问 GitHub（clone repo） |
| Git 仓库 | `https://github.com/hashSTACS-Global/test-discuss.git` |
| LLM 后端 | Claude Code 自身（无子进程） |
| 状态文件 | `tests/test_output/<name>_run_ctx.json` |

**优势：**
- 无嵌套调用问题，可在 Claude Code 会话内直接执行
- 每步独立执行，失败可从断点恢复
- 中间状态持久化在 context JSON 文件中

**执行流程：**

```
Claude Code (编排器 + LLM)
  │
  ├─ init          → 加载 pipeline 定义，创建 context 文件
  ├─ next          → prepare（代码步骤，直接执行）
  ├─ next          → generate_summary（LLM 步骤，返回 prompt）
  ├─ respond       → Claude Code 自己生成 JSON 摘要，注入回去
  ├─ next          → publish（代码步骤，写文件 + git commit）
  └─ next          → done，输出最终结果
```

---

## 用例 1: 新建讨论帖

| 字段 | 值 |
|------|-----|
| 用例编号 | TC-01 |
| 对应方法 | `test_01_new_thread` |
| 触发 Pipeline | `discuss-new` |
| 操作用户 | `huangshengli` |

### 输入参数

| 参数 | 值 |
|------|-----|
| `category` | `discussion` |
| `title` | `test-restructure-proposal` |
| `mention_users` | _(空)_ |
| `mention_comments` | _(空)_ |
| `content` | 见下方 |

**content 内容:**

```markdown
# 测试架构重构提案

## 背景
当前测试使用 mock 数据，无法验证 LLM 输出质量和真实 pipeline 行为。

## 方案
1. 引入四层测试架构：ec_simulator / pipeline_test / channel_test / integration_test
2. LLM step 使用本地 Claude CLI 真实调用
3. 所有输入输出录制到 test_output/ 目录

## 预期收益
- 测试可信度提升：LLM 返回真实 summary
- 数据可追溯：每次运行的完整 I/O 留档
- 回归保护：录制结果可作为后续 prerecorded fixture
```

### 验证点

| # | 断言 | 说明 |
|---|------|------|
| 1 | `result.status == "completed"` | Pipeline 执行成功 |
| 2 | `result.output["committed"] == True` | Git commit 已提交 |
| 3 | `discussions/discussion/test-restructure-proposal/` 目录存在 | 帖子目录已创建 |
| 4 | 该目录下有且仅有 1 个 `001_*.md` 文件 | 首帖文件已生成 |
| 5 | `generate_summary` 存在于 `step_outputs` | LLM 摘要步骤被真实调用 |
| 6 | 摘要长度 > 20 字符 | LLM 返回了有效摘要 |

### 录制产物

输出到 `<run_dir>/01_discuss_new/`:
- LLM 调用的 prompt 和 response
- `test_assertions.txt`（status、committed、summary 等）

---

## 用例 2: 回复讨论帖

| 字段 | 值 |
|------|-----|
| 用例编号 | TC-02 |
| 对应方法 | `test_02_reply_thread` |
| 触发 Pipeline | `discuss-reply` |
| 操作用户 | `ken` |
| 前置依赖 | TC-01 已通过 |

### 输入参数

| 参数 | 值 |
|------|-----|
| `category` | `discussion` |
| `thread` | `test-restructure-proposal` |
| `mention_users` | `huangshengli` |
| `mention_comments` | _(空)_ |
| `content` | 见下方 |

**content 内容:**

```markdown
# 回复：赞同方案，补充几点

1. PrerecordedBackend 应该保留，用于 CI 快速验证
2. ClaudeCLIBackend 只在本地开发时使用，CI 跳过
3. 建议增加 `--llm-backend` pytest 参数来切换

另外 test_output/ 目录的录制结果也可以反哺 prerecorded fixture，
形成「录制 → 回放」的闭环。
```

### 验证点

| # | 断言 | 说明 |
|---|------|------|
| 1 | `result.status == "completed"` | Pipeline 执行成功 |
| 2 | `result.output["committed"] == True` | Git commit 已提交 |
| 3 | `result.output["post_number"] == 2` | 帖子编号为 2（回复） |
| 4 | 目录下有且仅有 1 个 `002_*.md` 文件 | 回复文件已生成 |
| 5 | `generate_summary` 存在于 `step_outputs` | LLM 摘要步骤被真实调用 |
| 6 | 摘要长度 > 20 字符 | LLM 返回了有效摘要 |

### 录制产物

输出到 `<run_dir>/02_discuss_reply/`:
- LLM 调用的 prompt 和 response
- `test_assertions.txt`（status、committed、post_number、summary 等）

---

## 用例 3: 列出讨论帖

| 字段 | 值 |
|------|-----|
| 用例编号 | TC-03 |
| 对应方法 | `test_03_list_threads` |
| 触发 Pipeline | `discuss-list` |
| 操作用户 | `huangshengli` |
| 前置依赖 | TC-01 已通过 |

### 输入参数

| 参数 | 值 |
|------|-----|
| `category` | `discussion` |

### 验证点

| # | 断言 | 说明 |
|---|------|------|
| 1 | `result.status == "completed"` | Pipeline 执行成功 |
| 2 | `"test-restructure-proposal"` 在 slugs 列表中 | 新建的帖子出现在列表里 |

### 录制产物

输出到 `<run_dir>/03_discuss_list/`:
- `test_assertions.txt`（thread_count、slugs 列表）

---

## 用例 4: 读取讨论帖

| 字段 | 值 |
|------|-----|
| 用例编号 | TC-04 |
| 对应方法 | `test_04_read_thread` |
| 触发 Pipeline | `discuss-read` |
| 操作用户 | `huangshengli` |
| 前置依赖 | TC-01、TC-02 已通过 |

### 输入参数

| 参数 | 值 |
|------|-----|
| `category` | `discussion` |
| `thread` | `test-restructure-proposal` |

### 验证点

| # | 断言 | 说明 |
|---|------|------|
| 1 | `result.status == "completed"` | Pipeline 执行成功 |
| 2 | `len(posts) == 2` | 帖子包含 2 条内容（首帖 + 回复） |
| 3 | `posts[0]["author"] == "huangshengli"` | 首帖作者正确 |
| 4 | `posts[1]["author"] == "ken"` | 回复作者正确 |

### 录制产物

输出到 `<run_dir>/04_discuss_read/`:
- `test_assertions.txt`（post_count、authors 列表）

---

## 用例 5: 验证 Git 状态

| 字段 | 值 |
|------|-----|
| 用例编号 | TC-05 |
| 对应方法 | `test_05_verify_git_state` |
| 触发 Pipeline | _(无，直接检查 git)_ |
| 前置依赖 | TC-01、TC-02 已通过 |

### 输入参数

无 Pipeline 输入。直接对 workspace 执行 `git log` 和 `git status`。

### 验证点

| # | 断言 | 说明 |
|---|------|------|
| 1 | `git log` 返回码为 0 | Git 仓库状态正常 |
| 2 | commit 数量 >= 3 | 至少有 3 条 commit（初始 + new + reply） |

### 录制产物

输出到 `<run_dir>/05_git_state.txt`:
- `git log --oneline -10` 输出
- `git status -sb` 输出

---

## 测试流程总览

### 方式 A：pytest 一体化流程

```
Clone test-discuss repo
        │
        ▼
  TC-01: discuss-new ──→ 创建帖子 + git commit
        │
        ▼
  TC-02: discuss-reply ──→ 回复帖子 + git commit
        │
        ▼
  TC-03: discuss-list ──→ 验证帖子可被列出
        │
        ▼
  TC-04: discuss-read ──→ 验证帖子内容完整
        │
        ▼
  TC-05: verify git ──→ 验证 git 历史正确
```

### 方式 B：step_runner 分步流程

```
Clone test-discuss repo
        │
        ▼
  ┌─ discuss-new pipeline ─────────────────────────┐
  │  init → next(prepare) → next(need_llm)         │
  │           代码执行         返回 prompt            │
  │                               │                 │
  │                          respond(摘要)           │
  │                          Claude Code 生成        │
  │                               │                 │
  │                          next(publish)           │
  │                          代码+git commit         │
  │                               │                 │
  │                          next → done ✅          │
  └────────────────────────────────────────────────┘
        │
        ▼
  ┌─ discuss-reply pipeline ───────────────────────┐
  │  （同上流程，thread 指向已创建的帖子）              │
  └────────────────────────────────────────────────┘
        │
        ▼
  验证: git log / 文件检查
```

## 录制目录结构示例

### 方式 A：pytest 录制

```
tests/test_output/real_flow_20260413_143022/
├── repo_initial_state.txt
├── 01_discuss_new/
│   ├── llm_prompt_*.txt
│   ├── llm_response_*.txt
│   └── test_assertions.txt
├── 02_discuss_reply/
│   ├── llm_prompt_*.txt
│   ├── llm_response_*.txt
│   └── test_assertions.txt
├── 03_discuss_list/
│   └── test_assertions.txt
├── 04_discuss_read/
│   └── test_assertions.txt
└── 05_git_state.txt
```

### 方式 B：step_runner 状态文件

```
tests/test_output/
├── real_run_ctx.json          # discuss-new 的 context（含所有步骤输入输出）
└── reply_run_ctx.json         # discuss-reply 的 context
```

context JSON 包含完整的执行记录：pipeline 参数、每步的输出、LLM prompt 和注入的 response。

---

## 方式 B 已验证结果（2026-04-13）

在真实 repo `hashSTACS-Global/test-discuss.git` 上完整跑通：

| Pipeline | 结果 | 产物 |
|----------|------|------|
| discuss-new | `committed: true` | `001_huangshengli_proposal_c83b54.md` |
| discuss-reply | `committed: true`, `post_number: 2` | `002_ken_reply_169c59.md` |

```
Git Log:
  1c23c00 reply: discussion/step-runner-real-test #002 by ken
  ecb86e0 new thread: discussion/step-runner-real-test by huangshengli
  eac0a85 test
  36aa5a5 first commit
```
