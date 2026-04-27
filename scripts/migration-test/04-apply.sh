#!/usr/bin/env bash
# §4 迁移 apply(落盘 + 单次 commit,不自动 push)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

[[ -d "$TEST_WS/.git" ]] || fail "$TEST_WS 不存在,先跑 02-reset-repo.sh"

banner "§4 预检 git 身份(脚本最后会 commit,无身份会失败)"
cd "$TEST_WS"
EMAIL=$(git config --get user.email || echo "")
NAME=$(git config --get user.name || echo "")
[[ -n "$EMAIL" && -n "$NAME" ]] \
    || fail "$TEST_WS 没配 git 身份,先跑 02-reset-repo.sh 或手工 git config user.email/user.name"
echo "user.email = $EMAIL"
echo "user.name  = $NAME"

banner "§4 apply (DB_FLAG: $DB_FLAG)"
cd "$PIVOT_CODE"
uv run python scripts/migrate_index_schema.py \
    --workspace "$TEST_WS" \
    --apply \
    $DB_FLAG \
    --report "$REPORT_APPLY"

banner "§4 commit 结果"
cd "$TEST_WS"
git log -1 --oneline
git log -1 --shortstat

banner "✅ §4 完成"
echo "下一步: bash $SCRIPT_DIR/05-verify.sh"
