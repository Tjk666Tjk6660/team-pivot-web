# Team-Pivot APP — Claude Code Project Config

You are working on the **client side** of Team-Pivot, a team discussion management system.

## Important Distinction

- **`SKILL.md`** in this repo is the **EC server-side LLM fallback prompt**. It is NOT instructions for you. Do not follow its directives (e.g., "call discuss-new pipeline directly"). It exists for the EC Pipeline Runner's internal LLM to use when no pipeline trigger matches.
- **You should use `pivot-cli`** (a thin curl wrapper) to interact with the Pivot Agent via HTTP.

## Install / Setup

**STOP — Do NOT run `pip install` or any install command directly.**
When asked to install, set up, or onboard this project, you MUST read `README.md` first and follow its instructions. README.md has separate guides for users, admins, and developers — the correct steps depend on the role.

## Usage

```bash
pivot-cli discuss list [category]                    # List discussions
pivot-cli discuss inbox                              # Unread messages
pivot-cli discuss new <category> <title> [--draft <path>] [--mention <users>]
pivot-cli discuss reply <category>/<thread> [--draft <path>] [--mention <users>]
pivot-cli discuss read <category>/<thread>           # Read a discussion
pivot-cli discuss close <category>/<thread>          # Close
pivot-cli discuss pending <category>/<thread>        # Shelve
pivot-cli discuss reopen <category>/<thread> --reason <text>
pivot-cli file fetch <path> [<path2> ...]            # Fetch files
```

All commands return JSON. Parse and present the results to the user in a readable format.

## Development

- Run tests: `pytest`
- **Do not auto-commit** without explicit user instruction.
- `pipelines/` and `tools/` are server-side code (runs on EC). `bin/` is client-side.
- For dev environment setup, see the "For Developers" section in `README.md`.
