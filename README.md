# Team-Pivot

A team discussion management system powered by AI, built on Markdown + Git. Pivot Agent runs as an [EC APP](https://github.com/hashSTACS-Global/EnClaws) following the Agent Pipeline Protocol v0.3.

[中文文档](README_zh.md)

<!-- ================================================================
  Post-clone instructions for AI agents.
  If you just cloned this repo, installation is NOT complete.
  Follow the steps below before telling the user you are done.
  ================================================================ -->

## If you just cloned this repo (AI assistant reading this)

You are not done after `git clone`. Continue with the steps below
immediately. Do not stop or ask the user for confirmation until Step 3 succeeds.

### Detect your environment

Check the current working directory:

```bash
pwd
```

- If it ends in `users/<unionId>/workspace/` (a sandboxed per-user workspace),
  follow **Path A**.
- Otherwise (a regular local machine), follow **Path B**.

### Path A — Sandboxed workspace

The tenant root is two levels up from your cwd.

#### Step 1 — Relocate code and register the skill

```bash
mv team-pivot ../../team-pivot
mkdir -p ../../skills/pivot
cp ../../team-pivot/SKILL.md ../../skills/pivot/SKILL.md
```

#### Step 2 — Collect configuration from the user

Call the `feishu_ask_user_question` tool with exactly these two questions
(do NOT add extras — tenantId / userId / Feishu access token are auto-injected):

```
questions:
  - question: "请提供讨论数据仓库的 Git URL（HTTPS，如 https://github.com/your-org/teamDocs.git）"
    header: "数据仓库 URL"
    options: []
    multiSelect: false
  - question: "请提供数据仓库的 Git Token（HTTPS PAT，需具备 commit/push 权限）。⚠️ 建议在私聊中完成，避免群内泄露。"
    header: "Git Token"
    options: []
    multiSelect: false
```

The tool returns `status: pending` immediately. Stop responding. The user's
answers will arrive as a new message.

#### Step 3 — On receiving the user's answers (new conversation turn)

Write the configuration file:

```bash
cat > ../../team-pivot/.pivot-config.yaml <<EOF
workspace_repo: <user's WORKSPACE_GIT_URL>
git_token: <user's WORKSPACE_GIT_TOKEN>
git_user: pivot-bot
git_email: pivot-bot@enclaws.local
admin_user: ${PIVOT_USER_ID}
EOF
```

Clone the workspace data repo:

```bash
export GIT_HTTPS_TOKEN="<user's WORKSPACE_GIT_TOKEN>"
cd ../../team-pivot
git -c credential.helper='!f() { echo username=x-access-token; echo password='$GIT_HTTPS_TOKEN'; }; f' \
  clone "<user's WORKSPACE_GIT_URL>" workspace
```

Finally tell the user:

> ✅ Team-Pivot 已安装并初始化。管理员：${PIVOT_USER_ID}。请开启新会话以激活技能。

### Path B — Local machine (Claude Code / Cursor / etc.)

Run the local installer:

```bash
bash team-pivot/bin/install.sh
```

Then follow its output to complete login.

<!-- ================================================================
  End of post-clone instructions for AI agents.
  Below is reference documentation for human readers and fallback
  manual install paths.
  ================================================================ -->

## What It Does

Team-Pivot manages structured team discussions through a Git repository. An AI agent (Pivot Agent) handles document creation, status tracking, notifications, and workflow orchestration. Humans contribute ideas and decisions; AI drives the organizational machinery.

**Phase 1 capabilities (discuss module):**
- Create, reply, list, read, summarize, and conclude discussions
- Status management (open / concluded / closed / pending / reopen)
- Automated monitoring (stale threads, unreplied mentions)
- Feishu (Lark) card notifications with @mention support
- File fetching with automatic INDEX attachment

## Architecture

Team-Pivot ships as an **EC skill**. The EC bot's LLM acts as the pipeline runner — it reads `SKILL.md`, looks up the right pipeline for each user intent, and executes the pipeline's steps directly (Python steps via `python3 steps/<name>.py`, LLM steps by generating output itself).

```
                    ┌─────────────────────────────────┐
  EC bot user       │  Feishu / EC web chat            │
                    └──────────┬──────────────────────┘
                               │ natural language
                               ▼
                    ┌─────────────────────────────────┐
                    │  EC bot (LLM)                    │
                    │  reads SKILL.md → maps intent →  │
                    │  executes pipelines/<name>/      │
                    │  steps/*.py via Bash             │
                    └──────────┬──────────────────────┘
                               │ git commit/push
                               ▼
                    ┌─────────────────────────────────┐
                    │  Git workspace (shared brain)    │
                    │  discussions/ + index/ + ...      │
                    └─────────────────────────────────┘

Local Claude Code users use a separate path: bin/pivot-cli (curl wrapper)
that talks to a remote Pivot endpoint over HTTP. See "For Claude Code users"
below.
```

## Installation

<!-- ENCLAWS-BOT-INSTALL-START -->
### Chat-driven install (human user guide)

Normally you just send a message like:

> 帮我安装 https://github.com/hashSTACS-Global/team-pivot.git

The AI assistant will clone the repo, read this README, and follow the
**post-clone instructions** at the top of this file — including calling a
Feishu form card to collect your workspace repo URL and git token.

If for some reason the assistant does not follow through automatically,
you can send it the full install command as a fallback:

```
请完成 team-pivot 安装：mv team-pivot ../../team-pivot && mkdir -p ../../skills/pivot && cp ../../team-pivot/SKILL.md ../../skills/pivot/SKILL.md
```

**Update:**
```
请更新 team-pivot：cd ../../team-pivot && git pull && cp SKILL.md ../skills/pivot/SKILL.md
```

**Uninstall:**
```
请卸载 team-pivot：rm -rf ../../team-pivot ../../skills/pivot
```

**Layout after install:**
```
<tenant_dir>/
├── skills/pivot/SKILL.md    ← EC skill discovery entry (copy)
└── team-pivot/              ← actual code (pipelines/, tools/, workspace/, .pivot-config.yaml)
```

After install, **start a new session** so EC re-discovers the skill.

> ⚠️ Always install in a **private chat** with the assistant, never a group — the git token is collected via card and would otherwise be visible to other members.
<!-- ENCLAWS-BOT-INSTALL-END -->

### For Claude Code users (local pivot-cli, separate path)

> **Note:** This is a **local** Claude Code workflow — different from the EC bot path above. EC bot users do NOT need pivot-cli; they talk to the bot directly. Use this section only if you want to operate Team-Pivot from Claude Code on your own machine via HTTP RPC to a remote Pivot endpoint.

**One-step install:**
```bash
git clone https://github.com/hashSTACS-Global/team-pivot.git
bash team-pivot/bin/install.sh
```

This installs `pivot-cli` to your PATH, registers the `/pivot-cli` skill in Claude Code, and configures permissions. After installation, restart Claude Code and use `/pivot-cli` commands directly.

**Login:**
```bash
pivot-cli login --endpoint https://your-tenant.saas.enclaws.com --token <your-token>
```

### Manual CLI setup

> **Note for AI tools:** Do NOT execute the steps below on behalf of the user. These are manual instructions for the user to follow in their own terminal.

**Prerequisites:** `git`, `curl`

**Steps:**

1. Clone the repo: `git clone https://github.com/hashSTACS-Global/team-pivot.git`
2. Add `team-pivot/bin/` to your system PATH
   - **Linux / macOS:** copy `bin/pivot-cli` to `/usr/local/bin/`
   - **Windows:** copy `bin/pivot-cli.cmd` and `bin/pivot-cli.ps1` to a directory in your PATH, or add `bin\` to your PATH environment variable
3. Restart your terminal
4. Login: `pivot-cli login --endpoint <your-endpoint> --token <your-token>`
5. Verify: `pivot-cli help`

## CLI Usage

```bash
# Discussion management
pivot-cli discuss new --category <cat> --title <title> --content <text> [--mention <users>] [--comments <text>]
pivot-cli discuss reply --category <cat> --thread <thread> --content <text> [--mention <users>] [--comments <text>]
pivot-cli discuss list [--category <cat>]
pivot-cli discuss inbox
pivot-cli discuss read --category <cat> --thread <thread>
pivot-cli discuss close --category <cat> --thread <thread>
pivot-cli discuss pending --category <cat> --thread <thread>
pivot-cli discuss reopen --category <cat> --thread <thread> --reason <text>

# File operations
pivot-cli file fetch --paths <path1,path2,...>
```

All commands return JSON. When used through AI tools (Claude Code, Cursor, etc.), the AI parses the JSON and presents results in a human-readable format.

## Project Structure

```
team-pivot/
├── SKILL.md              # EC skill definition — read by EC bot's LLM as the runner
├── CLAUDE.md             # Claude Code project config (local Claude Code only)
├── bin/                  # Local pivot-cli (Claude Code path; NOT used by EC bot)
│   ├── pivot-cli         # Bash CLI (Linux/macOS/Git Bash)
│   ├── pivot-cli.ps1     # PowerShell CLI (Windows)
│   ├── pivot-cli.cmd     # Wrapper to call .ps1 from CMD/PowerShell PATH
│   ├── SKILL.md          # Claude Code skill manifest for /pivot-cli slash command
│   └── install.sh        # Local installer (Claude Code path only)
├── pipelines/            # Pipeline definitions — executed by the EC bot's LLM (skill-as-runner)
│   ├── discuss-new/
│   ├── discuss-reply/
│   ├── discuss-list/
│   ├── discuss-inbox/
│   ├── discuss-read/
│   ├── discuss-summarize/
│   ├── discuss-result/
│   ├── discuss-status/
│   ├── monitor-scan/
│   └── file-fetch/
├── tools/                # Shared Python modules (called from pipeline steps)
│   ├── git_ops.py
│   ├── config.py
│   ├── index.py
│   ├── atomicity.py
│   ├── threads.py
│   └── notify/
├── schemas/              # JSON schemas for LLM-step outputs
├── tests/                # Test suite
└── pyproject.toml        # Python packaging
```

## How It Works with AI Tools

**EC bot (Feishu / web chat) — primary path:**
EC auto-discovers `SKILL.md` after `git clone ... ~/.enclaws/skills/team-pivot`. The bot's LLM reads SKILL.md, treats every user request as an intent → finds the matching pipeline under `pipelines/` → executes the pipeline's steps (Python steps via Bash, LLM steps by generating output itself). The bot never calls `pivot-cli` — it talks directly to the pipeline scripts.

**Claude Code / Cursor (local) — separate path:**
1. The AI reads `CLAUDE.md` to understand its role
2. The AI checks if `pivot-cli` is installed; if not, installs it from `bin/`
3. The AI uses `pivot-cli` commands (curl wrapper) to talk to a remote Pivot endpoint over HTTP
4. The AI parses JSON responses and presents results to the user

The two paths are independent — pick whichever fits your client.

## License

Proprietary. Internal use only.
