#!/bin/bash
# install.sh — Install Team-Pivot APP for Claude Code
# Registers the /pivot-cli skill and sets up pivot-cli
#
# Usage:
#   git clone https://github.com/hashSTACS-Global/team-pivot.git
#   bash team-pivot/bin/install.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== Installing Team-Pivot APP ==="
echo ""

# 1. Install pivot-cli
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
    # Windows (Git Bash / MSYS2)
    CLI_DIR="$HOME/bin"
    mkdir -p "$CLI_DIR"
    cp "$SCRIPT_DIR/pivot-cli" "$CLI_DIR/pivot-cli"
    chmod +x "$CLI_DIR/pivot-cli"
    echo "[OK] pivot-cli installed to $CLI_DIR/pivot-cli"
    if ! echo "$PATH" | tr ':' '\n' | grep -q "$CLI_DIR"; then
        echo "[WARN] $CLI_DIR may not be in your PATH. Add it or use full path."
    fi
else
    # Linux / macOS
    if [ -w /usr/local/bin ]; then
        cp "$SCRIPT_DIR/pivot-cli" /usr/local/bin/pivot-cli
        chmod +x /usr/local/bin/pivot-cli
        echo "[OK] pivot-cli installed to /usr/local/bin/pivot-cli"
    else
        sudo cp "$SCRIPT_DIR/pivot-cli" /usr/local/bin/pivot-cli
        sudo chmod +x /usr/local/bin/pivot-cli
        echo "[OK] pivot-cli installed to /usr/local/bin/pivot-cli (via sudo)"
    fi
fi

# 2. Register /pivot-cli skill in Claude Code
CLAUDE_SKILLS_DIR="$HOME/.claude/skills"
SKILL_TARGET="$CLAUDE_SKILLS_DIR/pivot-cli"

# Clean up old installation
if [ -L "$SKILL_TARGET" ]; then
    rm "$SKILL_TARGET"
elif [ -d "$SKILL_TARGET" ]; then
    rm -rf "$SKILL_TARGET"
fi

mkdir -p "$SKILL_TARGET"
cp "$SCRIPT_DIR/SKILL.md" "$SKILL_TARGET/SKILL.md"
echo "[OK] /pivot-cli skill registered at $SKILL_TARGET"

# 3. Add repo to Claude Code additionalDirectories
SETTINGS_FILE="$HOME/.claude/settings.json"
mkdir -p "$HOME/.claude"

add_directory() {
    local dir="$1"
    if [ ! -f "$SETTINGS_FILE" ]; then
        cat > "$SETTINGS_FILE" << EOF
{
  "permissions": {
    "additionalDirectories": [
      "$dir"
    ]
  }
}
EOF
        echo "[OK] Created $SETTINGS_FILE with additionalDirectories"
    else
        if command -v python3 >/dev/null 2>&1; then
            python3 -c "
import json, sys
f = '$SETTINGS_FILE'
with open(f) as fh:
    s = json.load(fh)
dirs = s.get('permissions', {}).get('additionalDirectories', [])
if '$dir' in dirs:
    print('[OK] $dir already in additionalDirectories')
    sys.exit(0)
if 'permissions' not in s:
    s['permissions'] = {}
if 'additionalDirectories' not in s['permissions']:
    s['permissions']['additionalDirectories'] = []
s['permissions']['additionalDirectories'].append('$dir')
with open(f, 'w') as fh:
    json.dump(s, fh, indent=2)
print('[OK] Added $dir to additionalDirectories')
"
        else
            echo "[WARN] python3 not found — please manually add $dir to additionalDirectories in $SETTINGS_FILE"
        fi
    fi
}

add_directory "$REPO_DIR"

echo ""
echo "=== Installation complete ==="
echo ""
echo "Next steps:"
echo "  1. Login:  pivot-cli login --endpoint <URL> --token <TOKEN>"
echo "  2. Restart Claude Code"
echo "  3. Use /pivot-cli commands:"
echo ""
echo "     /pivot-cli list                        List discussions"
echo "     /pivot-cli inbox                       Check unread"
echo "     /pivot-cli new <category> \"<title>\"    Start a discussion"
echo "     /pivot-cli reply <category>/<thread>   Reply to a discussion"
echo "     /pivot-cli read <category>/<thread>    Read a discussion"
echo ""
