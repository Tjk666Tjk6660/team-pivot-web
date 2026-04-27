#!/usr/bin/env bash
# §4 迁移 apply: in-place 落盘到 workspace + 单次 commit (不 push)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

[[ -d "$WORKSPACE/.git" ]] || fail "$WORKSPACE 不是 git workspace"

banner "§4.1 强制要求:近期 bundle 备份已做"
RECENT_BUNDLE=$(find "$BACKUP_DIR" -name 'pre-migration-*.bundle' -mmin -60 2>/dev/null | sort -r | head -1)
[[ -n "$RECENT_BUNDLE" ]] || fail "近 1 小时内没找到 bundle 备份;先跑 02-bundle-backup.sh"
echo "最新 bundle: $RECENT_BUNDLE"

banner "§4.2 预检 git 身份"
cd "$WORKSPACE"
EMAIL=$(git config --get user.email || echo "")
NAME=$(git config --get user.name || echo "")
[[ -n "$EMAIL" && -n "$NAME" ]] \
    || fail "$WORKSPACE 没配 git 身份;先跑 01-preflight.sh"
echo "user.email = $EMAIL"
echo "user.name  = $NAME"

banner "§4.3 apply (DB_FLAG: $DB_FLAG)"
cd "$PIVOT_CODE"
uv run python scripts/migrate_index_schema.py \
    --workspace "$WORKSPACE" \
    --apply \
    $DB_FLAG \
    --report "$REPORT_APPLY"

banner "§4.4 commit 结果"
cd "$WORKSPACE"
git log -1 --oneline
git log -1 --shortstat

ok "§4 完成 (commit 已建,**未** push,可继续 verify;有问题用 99-rollback.sh)"
echo "下一步: bash $SCRIPT_DIR/05-verify.sh"
