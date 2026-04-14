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

```
                    ┌─────────────────────────────────┐
  Human / AI Tool   │  pivot-cli (curl wrapper)        │
  (client side)     │  bin/pivot-cli | bin/pivot-cli.ps1│
                    └──────────┬──────────────────────┘
                               │ HTTP POST
                               ▼
                    ┌─────────────────────────────────┐
  EC Platform       │  Pipeline Runner                 │
  (server side)     │  routes to pipelines/*           │
                    │  executes steps/*.py              │
                    └──────────┬──────────────────────┘
                               │ git commit/push
                               ▼
                    ┌─────────────────────────────────┐
                    │  Git Repository (shared brain)   │
                    │  discussions/ + index/ + ...      │
                    └─────────────────────────────────┘
```

## Installation

### For Claude Code users

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

### Manual CLI setup (for users, not AI tools)

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

### For EC Administrators (server side)

Pivot APP is deployed through the EC platform's Agent management interface:

1. Open the EC admin panel
2. Add a new Agent APP → enter this repo's Git URL
3. EC automatically clones the repo and registers all pipelines
4. Python dependencies (`pyyaml`, `jsonschema`, `requests`) must be available in the EC runtime environment

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
├── SKILL.md              # EC server-side LLM fallback prompt (NOT for client AI tools)
├── CLAUDE.md             # Claude Code project config
├── bin/
│   ├── pivot-cli         # CLI for Linux/macOS (bash + curl)
│   └── pivot-cli.ps1     # CLI for Windows (PowerShell)
├── pipelines/            # Server-side: EC Pipeline Runner executes these
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
├── tools/                # Server-side: shared Python modules
│   ├── git_ops.py
│   ├── config.py
│   ├── index.py
│   ├── atomicity.py
│   ├── threads.py
│   └── notify/
├── schemas/              # Shared JSON schemas
├── tests/                # Test suite
└── pyproject.toml        # Python packaging (server-side + dev)
```

## How It Works with AI Tools

When you give this repo to an AI coding tool (Claude Code, Cursor, etc.):

1. The AI reads `CLAUDE.md` to understand the project and its role
2. The AI checks if `pivot-cli` is installed; if not, installs it from `bin/`
3. The AI uses `pivot-cli` commands to interact with the Pivot Agent
4. The AI parses JSON responses and presents them with analysis and formatting

The AI does **not** read `SKILL.md` — that file is for the EC server-side LLM fallback mode.

## License

Proprietary. Internal use only.
