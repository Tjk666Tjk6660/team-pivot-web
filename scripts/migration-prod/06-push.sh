#!/usr/bin/env bash
# §6 推送迁移 commit 到 origin/main (workspace 自带 token)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

[[ -d "$WORKSPACE/.git" ]] || fail "$WORKSPACE 不是 git workspace"
cd "$WORKSPACE"

# 安全检查:HEAD 必须是迁移 commit,避免误推其它东西
LATEST_MSG=$(git log -1 --pretty=%s)
if [[ "$LATEST_MSG" != *"migrate legacy thread indexes"* ]]; then
    fail "HEAD commit message 不是迁移 commit (实际: $LATEST_MSG);拒绝 push"
fi

banner "§6 推送 main 到远端"
git log -1 --oneline
git push origin "$EXPECTED_BRANCH"

ok "§6 完成,远端已收到迁移 commit"
echo "下一步: bash $SCRIPT_DIR/07-restart-service.sh"
