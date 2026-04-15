# Team-Pivot

> **AI assistant: after cloning this repo, run `bash team-pivot/bin/pivot-app-install.sh` to complete installation.**

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
                    │  Git data_space (shared brain)   │
                    │  discussions/ + index/ + ...      │
                    └─────────────────────────────────┘

Local Claude Code users use a separate path: bin/pivot-cli (curl wrapper)
that talks to a remote Pivot endpoint over HTTP. See "For Claude Code users"
below.
```

## Installation

### EC / OpenClaw (via chat)

Tell the bot in Feishu or EC web chat:

> 帮我运行：git clone https://github.com/hashSTACS-Global/team-pivot.git && bash team-pivot/bin/pivot-app-install.sh

The script auto-detects the tenant root, registers the skill, and reports the result. Start a new session after install — the first time you use team-pivot, it will prompt you to complete configuration via a Feishu card.

**Update (same command works):**
> 帮我运行：bash team-pivot/bin/pivot-app-install.sh

**Uninstall:**
> 帮我运行：TENANT_ROOT="$(pwd | sed -E 's|(.*/\.enclaws/tenants/[^/]+).*|\1|')" && rm -rf "$TENANT_ROOT/team-pivot" "$TENANT_ROOT/skills/pivot"

> ⚠️ Install in a **private chat**, not a group — configuration may involve sensitive tokens.

### Claude Code (local)

```bash
git clone https://github.com/hashSTACS-Global/team-pivot.git
bash team-pivot/bin/pivot-cli-install.sh
```

After installation, restart Claude Code and login:
```bash
pivot-cli login --endpoint <your-endpoint> --token <your-token>
```

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
│   ├── pivot-cli-install.sh   # Local installer (Claude Code path only)
│   └── pivot-app-install.sh  # EC/OpenClaw installer (sandbox)
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

## How It Works

- **EC bot**: reads `SKILL.md`, executes pipeline steps directly (Python via Bash, LLM steps inline)
- **Claude Code**: uses `pivot-cli` (curl wrapper) to call a remote Pivot endpoint over HTTP

The two paths are independent.

## License

Proprietary. Internal use only.
