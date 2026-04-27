#!/usr/bin/env bash
# §1 全面预检:工具/版本/分支/clean/同步/服务停了/db 可读/老 index 数量
# 任何一项失败拒绝继续。所有破坏性操作前的最后防线。
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

banner "§1.1 工具检查"
_missing=()
_check_cmd() {
    if command -v "$1" >/dev/null 2>&1; then
        echo "  ✅ $1: $(command -v "$1")"
    else
        echo "  ❌ $1 缺失,安装: $2"
        _missing+=("$1")
    fi
}
_check_cmd git     "sudo apt-get install -y git"
_check_cmd python3 "sudo apt-get install -y python3"
_check_cmd sqlite3 "sudo apt-get install -y sqlite3"
_check_cmd uv      "curl -LsSf https://astral.sh/uv/install.sh | sh && source ~/.local/bin/env"
[[ ${#_missing[@]} -eq 0 ]] || fail "请先安装上面缺失的命令"

banner "§1.2 team-pivot-web 代码仓库 ($PIVOT_CODE)"
cd "$PIVOT_CODE"
[[ -d .git ]] || fail "$PIVOT_CODE 不是 git 仓库"
CODE_BRANCH=$(git rev-parse --abbrev-ref HEAD)
[[ "$CODE_BRANCH" == "$EXPECTED_BRANCH" ]] \
    || fail "代码仓库当前分支 '$CODE_BRANCH' != EXPECTED_BRANCH '$EXPECTED_BRANCH';先 git checkout $EXPECTED_BRANCH && git pull"
git log --oneline -1

# 校验迁移脚本含 read-only safety 修复(_ReadOnlyUserView 类)
banner "§1.3 迁移脚本版本(含 read-only safety 修复)"
uv run python -c "from scripts.migrate_index_schema import _ReadOnlyUserView; print('✅ migration script: read-only safe (has _ReadOnlyUserView)')" \
    || fail "迁移脚本不含 _ReadOnlyUserView,代码版本旧;先在 $PIVOT_CODE 跑 git pull"

banner "§1.4 workspace ($WORKSPACE)"
[[ -d "$WORKSPACE/.git" ]] || fail "$WORKSPACE 不是 git workspace"
cd "$WORKSPACE"

WS_BRANCH=$(git rev-parse --abbrev-ref HEAD)
[[ "$WS_BRANCH" == "$EXPECTED_BRANCH" ]] \
    || fail "workspace 当前分支 '$WS_BRANCH' != EXPECTED_BRANCH '$EXPECTED_BRANCH'"

if [[ -n "$(git status --porcelain)" ]]; then
    git status
    fail "workspace 工作树不干净,迁移前必须 clean"
fi
ok "workspace 在 $EXPECTED_BRANCH,工作树干净"

banner "§1.5 workspace 与 origin/$EXPECTED_BRANCH 同步状态"
git fetch origin "$EXPECTED_BRANCH"
AHEAD=$(git rev-list --count "origin/$EXPECTED_BRANCH..HEAD")
BEHIND=$(git rev-list --count "HEAD..origin/$EXPECTED_BRANCH")
echo "ahead=$AHEAD  behind=$BEHIND"
[[ "$AHEAD" -eq 0 ]] || fail "workspace 比 origin 多 $AHEAD 个未推送 commit;手工处理后重试"
[[ "$BEHIND" -eq 0 ]] || fail "workspace 落后 origin $BEHIND 个 commit;先 git pull --ff-only"

banner "§1.6 workspace git 身份"
WS_EMAIL=$(git config --get user.email || true)
WS_NAME=$(git config --get user.name || true)
if [[ -z "$WS_EMAIL" || -z "$WS_NAME" ]]; then
    git config user.email "$GIT_USER_EMAIL"
    git config user.name  "$GIT_USER_NAME"
    ok "已配 user.email=$GIT_USER_EMAIL  user.name=$GIT_USER_NAME (本仓库 local config)"
else
    ok "已配 user.email=$WS_EMAIL  user.name=$WS_NAME"
fi

banner "§1.7 服务必须已停"
if systemctl is-active --quiet "$SERVICE_NAME"; then
    systemctl status "$SERVICE_NAME" --no-pager | head -5
    fail "$SERVICE_NAME 仍在运行,迁移前必须先 'sudo systemctl stop $SERVICE_NAME'"
else
    ok "$SERVICE_NAME 已停"
fi

banner "§1.8 PROD_DB_PATH"
if [[ -n "${PROD_DB_PATH:-}" ]]; then
    [[ -r "$PROD_DB_PATH" ]] || fail "PROD_DB_PATH=$PROD_DB_PATH 不可读"
    USERS=$(sqlite3 "$PROD_DB_PATH" "SELECT count(*) FROM users WHERE pinyin IS NOT NULL;" 2>/dev/null || echo 0)
    ok "PROD_DB_PATH 可读,users with pinyin: $USERS"
else
    warn "PROD_DB_PATH 留空,走 --no-users-db,mention 落 open_id 字面量"
fi

banner "§1.9 老 index 数量"
LEGACY=$(ls "$WORKSPACE/index/" 2>/dev/null | grep -c -- '-discuss.index.yaml$' || echo 0)
echo "legacy *-discuss.index.yaml 数量: $LEGACY"
[[ "$LEGACY" -gt 0 ]] || fail "没找到老 index,workspace 可能已迁移过或异常"

banner "✅ §1 preflight 全部通过"
echo "DB_FLAG = $DB_FLAG"
echo "下一步: bash $SCRIPT_DIR/02-bundle-backup.sh"
