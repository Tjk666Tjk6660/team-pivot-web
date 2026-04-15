# Team-Pivot

A team discussion management system powered by AI, built on Markdown + Git. Pivot Agent runs as an [EC APP](https://github.com/hashSTACS-Global/EnClaws) following the Agent Pipeline Protocol v0.3.

[中文文档](README_zh.md)

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
### For EnClaws bot users (chat-driven install)

The EC bot runs in a per-user sandbox whose cwd is `<tenant_dir>/users/<openId>/workspace/`. All install commands use the relative path `../../` to reach the tenant root.

Tell the EC bot in chat (Feishu or web):

- **Install:**
  ```
  请安装 team-pivot：git clone https://github.com/hashSTACS-Global/team-pivot.git ../../team-pivot && mkdir -p ../../skills/pivot && cp ../../team-pivot/SKILL.md ../../skills/pivot/SKILL.md
  ```
- **Update:**
  ```
  请更新 team-pivot：cd ../../team-pivot && git pull && cp SKILL.md ../skills/pivot/SKILL.md
  ```
- **Uninstall:**
  ```
  请卸载 team-pivot：rm -rf ../../team-pivot ../../skills/pivot
  ```

**Layout after install:**
```
<tenant_dir>/
├── skills/pivot/SKILL.md    ← EC skill discovery entry (copy)
└── team-pivot/              ← actual code (pipelines/, tools/, etc.)
```

After install, **start a new session** so EC re-discovers skills.

The first time you actually use Team-Pivot in chat (e.g. "发起一个讨论" / "看看讨论列表"), the bot will ask you for:

1. **数据仓库 URL** — your team's discussion data repo (e.g. `https://github.com/your-org/teamDocs.git`)
2. **Git Token** — an HTTPS PAT with commit/push access

It collects these via a Feishu form card and stores them at `<tenant_dir>/team-pivot/.pivot-config.yaml`. The first user to complete this becomes the admin.

> ⚠️ Do this in a **private chat** with the bot, not in a group, to avoid token exposure.

The bot reads `SKILL.md` (loaded from `skills/pivot/SKILL.md` but resolved to `team-pivot/` for all operations) — you don't need to memorize anything.
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
