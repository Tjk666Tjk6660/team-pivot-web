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

## Commands

### `/pivot-cli list [category]`
```bash
pivot-cli discuss list [category]
```
List all discussions, optionally filtered by category. Present as a readable table.

### `/pivot-cli inbox`
```bash
pivot-cli discuss inbox
```
Show unread messages. Ask if the user wants to read any thread.

### `/pivot-cli new <category> <title>`
```bash
pivot-cli discuss new <category> "<title>" [--draft <path>] [--mention <users>] [--comments <text>]
```
Start a new discussion. If the user doesn't specify a draft, ask if they want to write one first.

### `/pivot-cli reply <category>/<thread>`
```bash
pivot-cli discuss reply <category>/<thread> [--draft <path>] [--mention <users>] [--comments <text>]
```
Reply to an existing discussion.

### `/pivot-cli read <category>/<thread>`
```bash
pivot-cli discuss read <category>/<thread>
```
Read a discussion thread. Present with:
- Thread title, category, status
- Each post: author, date, content summary
- Overall status and open questions

### `/pivot-cli close <category>/<thread>`
```bash
pivot-cli discuss close <category>/<thread>
```
Close a discussion.

### `/pivot-cli pending <category>/<thread>`
```bash
pivot-cli discuss pending <category>/<thread>
```
Shelve a discussion for later.

### `/pivot-cli reopen <category>/<thread> --reason <text>`
```bash
pivot-cli discuss reopen <category>/<thread> --reason "<text>"
```
Reopen a closed/pending discussion. Reason is required.

### `/pivot-cli fetch <path> [path2 ...]`
```bash
pivot-cli file fetch <path> [<path2> ...]
```
Fetch files from the server.

## Natural Language Support

Users may type `/pivot-cli` followed by natural language. Infer the intent:

| User input | Action |
|------------|--------|
| `有什么新消息` | `inbox` |
| `看看讨论列表` | `list` |
| `读一下那个讨论` | `read` (identify the thread) |
| `回复` | `reply` (identify the thread) |
| `发起一个讨论` | `new` (ask for category and title) |
| `关闭这个讨论` | `close` |

## Response Handling

All `pivot-cli` commands return JSON. Always:
1. Parse the JSON response
2. Check for errors (non-zero exit code or error fields in JSON)
3. Present results in a clean, readable format — not raw JSON
