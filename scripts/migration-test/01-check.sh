#!/usr/bin/env bash
# §1 环境检查 + uv sync(不会主动安装系统包,缺啥告诉用户怎么装)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

banner "§1.1 系统命令检查"

_missing=()
_check_cmd() {
    local cmd="$1"
    local hint="$2"
    if command -v "$cmd" >/dev/null 2>&1; then
        echo "  ✅ $cmd: $(command -v "$cmd")"
    else
        echo "  ❌ $cmd 缺失"
        echo "     安装: $hint"
        _missing+=("$cmd")
    fi
}

_check_cmd git     "sudo apt-get install -y git   (Debian/Ubuntu)"
_check_cmd python3 "sudo apt-get install -y python3"
_check_cmd sqlite3 "sudo apt-get install -y sqlite3"
_check_cmd uv      "curl -LsSf https://astral.sh/uv/install.sh | sh && source ~/.local/bin/env"

if [[ ${#_missing[@]} -gt 0 ]]; then
    echo
    fail "请先安装上面缺失的命令再重跑 01-check.sh"
fi

banner "§1.2 校验 PROD_DB_PATH"
if [[ -n "${PROD_DB_PATH:-}" ]]; then
    if [[ -r "$PROD_DB_PATH" ]]; then
        ok "PROD_DB_PATH=$PROD_DB_PATH 可读"
        # 用 sqlite3 校验是合法 db
        if sqlite3 "$PROD_DB_PATH" "SELECT count(*) FROM users;" >/dev/null 2>&1; then
            USERS=$(sqlite3 "$PROD_DB_PATH" "SELECT count(*) FROM users WHERE pinyin IS NOT NULL;")
            echo "  users with pinyin: $USERS"
        else
            warn "无法读 users 表,迁移时 mention 会跌回 open_id"
        fi
    else
        fail "PROD_DB_PATH=$PROD_DB_PATH 不可读;改路径或留空走 --no-users-db"
    fi
else
    warn "PROD_DB_PATH 为空,走 --no-users-db,mention 会落 open_id 字面量"
fi

banner "§1.3 切到 $PIVOT_BRANCH 并 uv sync"
cd "$PIVOT_CODE"
git fetch origin
git checkout "$PIVOT_BRANCH"
git pull --ff-only origin "$PIVOT_BRANCH"
git log --oneline -1
uv sync

banner "§1.4 校验迁移脚本和测试都跑得起来(快速 smoke)"
uv run python -c "from scripts.migrate_index_schema import migrate_one, _build_users_repo, _ReadOnlyUserView; print('imports ok')"

banner "✅ §1 完成"
echo "DB_FLAG = $DB_FLAG"
echo "下一步: bash $SCRIPT_DIR/02-reset-repo.sh"
