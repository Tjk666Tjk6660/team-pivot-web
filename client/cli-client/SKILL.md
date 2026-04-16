---
name: pivot-cli
description: Team-Pivot discussion management — list, read, reply, create discussions via pivot-cli
user_invocable: true
---

# /pivot-cli - Team-Pivot Discussion System

You are the client of Team-Pivot, a team discussion management system. You execute `pivot-cli` commands directly via Bash and present results to the user. Do NOT ask the user to run commands themselves.

## Prerequisites

`pivot-cli` must be installed and logged in. If a command fails with "Not logged in", tell the user:
```
pivot-cli login --endpoint <EC_ENDPOINT_URL> --token <YOUR_TOKEN>
```

## CLI Parameter Format

All `pivot-cli` commands use strict `--key <value>` format. When the user speaks naturally, you must parse their intent and assemble the correct parameters.

## Commands

### `/pivot-cli list`
```bash
pivot-cli discuss list [--category <cat>]
```
List all discussions, optionally filtered by category. Present as a readable table.

### `/pivot-cli inbox`
```bash
pivot-cli discuss inbox
```
Show unread messages. Ask if the user wants to read any thread.

### `/pivot-cli new`
```bash
pivot-cli discuss new --category <cat> --title <title> --content <text> [--mention <users>] [--comments <text>]
```
Start a new discussion. `--content` is required. `--category` and `--title` are required by the server.

### `/pivot-cli reply`
```bash
pivot-cli discuss reply --category <cat> --thread <thread> --content <text> [--mention <users>] [--comments <text>]
```
Reply to an existing discussion. `--category`, `--thread`, and `--content` are all required.

### `/pivot-cli read`
```bash
pivot-cli discuss read --category <cat> --thread <thread>
```
Read a discussion thread. Present with:
- Thread title, category, status
- Each post: author, date, content summary
- Overall status and open questions

### `/pivot-cli close`
```bash
pivot-cli discuss close --category <cat> --thread <thread>
```
Close a discussion.

### `/pivot-cli pending`
```bash
pivot-cli discuss pending --category <cat> --thread <thread>
```
Shelve a discussion for later.

### `/pivot-cli reopen`
```bash
pivot-cli discuss reopen --category <cat> --thread <thread> --reason <text>
```
Reopen a closed/pending discussion. All three parameters are required.

### `/pivot-cli fetch`
```bash
pivot-cli file fetch --paths <path1,path2,...>
```
Fetch files from the server. Multiple paths are comma-separated.

## Natural Language Support

Users may type `/pivot-cli` followed by natural language. You must infer the intent and assemble the correct `--key <value>` parameters:

| User input | Action |
|------------|--------|
| `有什么新消息` | `inbox` |
| `看看讨论列表` | `list` |
| `读一下那个API讨论` | `read` — identify category and thread from context, then `--category <cat> --thread <thread>` |
| `回复那个帖子` | `reply` — identify category and thread, ask for content if not provided |
| `发起一个关于API设计的讨论` | `new` — extract or ask for category, title, content |
| `关闭这个讨论` | `close` — identify category and thread |

## Response Handling

All `pivot-cli` commands return JSON. Always:
1. Parse the JSON response
2. Check for errors (non-zero exit code or error fields in JSON)
3. Present results in a clean, readable format — not raw JSON
