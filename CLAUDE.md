# Team-Pivot APP — Claude Code Project Config

You are working on the **client side** of Team-Pivot, a team discussion management system.

## Important Distinction

- **`SKILL.md`** in this repo is the **EC server-side LLM fallback prompt**. It is NOT instructions for you. Do not follow its directives (e.g., "call discuss-new pipeline directly"). It exists for the EC Pipeline Runner's internal LLM to use when no pipeline trigger matches.
- **You should use `pivot-cli`** (a thin curl wrapper) to interact with the Pivot Agent via HTTP.

## Setup

1. Check if `pivot-cli` is available:
   ```bash
   which pivot-cli 2>/dev/null || echo "not installed"
   ```

2. If not installed:
   - **Linux/Mac**: `cp bin/pivot-cli /usr/local/bin/ && chmod +x /usr/local/bin/pivot-cli`
   - **Windows PowerShell**: Copy `bin/pivot-cli.ps1` to a directory in your PATH, or invoke directly: `powershell -File bin/pivot-cli.ps1`

3. Login:
   ```bash
   pivot-cli login --endpoint <EC_ENDPOINT_URL> --token <YOUR_TOKEN>
   ```

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

- Python 3.9+, install dev deps: `pip install -e ".[dev]"`
- Run tests: `pytest`
- **Do not auto-commit** without explicit user instruction.
- `pipelines/` and `tools/` are server-side code (runs on EC). `bin/` is client-side.
