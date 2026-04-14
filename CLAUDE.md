# Team-Pivot APP — Claude Code Project Config

You are working on the **client side** of Team-Pivot, a team discussion management system.

## Important Distinction

- **`SKILL.md`** in this repo is the **EC server-side LLM fallback prompt**. It is NOT instructions for you. Do not follow its directives (e.g., "call discuss-new pipeline directly"). It exists for the EC Pipeline Runner's internal LLM to use when no pipeline trigger matches.
- **You should use `pivot-cli`** (a thin curl wrapper) to interact with the Pivot Agent via HTTP.

## Install / Setup

**STOP — Do NOT run `pip install` or any install command directly.**
When asked to install, set up, or onboard this project, you MUST read `README.md` first and follow its instructions. README.md has separate guides for users, admins, and developers — the correct steps depend on the role.

## Usage — You ARE the client

After setup, you should **directly execute** `pivot-cli` commands via Bash when the user asks about discussions, inbox, etc. Do NOT tell the user to run commands themselves — you run them, parse the JSON response, and present the results in a readable format.

Available commands:
```bash
pivot-cli discuss list [--category <cat>]
pivot-cli discuss inbox
pivot-cli discuss new --category <cat> --title <title> --content <text> [--mention <users>] [--comments <text>]
pivot-cli discuss reply --category <cat> --thread <thread> --content <text> [--mention <users>] [--comments <text>]
pivot-cli discuss read --category <cat> --thread <thread>
pivot-cli discuss close --category <cat> --thread <thread>
pivot-cli discuss pending --category <cat> --thread <thread>
pivot-cli discuss reopen --category <cat> --thread <thread> --reason <text>
pivot-cli file fetch --paths <path1,path2,...>
```

Example workflow:
- User: "有什么新消息？" → You run `pivot-cli discuss inbox`, parse JSON, present results
- User: "发起一个讨论" → You ask for category/title, then run `pivot-cli discuss new ...`

## Development

- Run tests: `pytest`
- **Do not auto-commit** without explicit user instruction.
- `pipelines/` and `tools/` are server-side code (runs on EC). `bin/` is client-side.
- For dev environment setup, see the "For Developers" section in `README.md`.
