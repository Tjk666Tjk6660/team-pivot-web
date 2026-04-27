#!/usr/bin/env bash
# §99 push 前 rollback: HEAD~1 reset
# push 后 rollback 是破坏性 force-push,涉及通知所有团队成员同步,
# 本脚本拒绝自动执行,要求走 migration-runbook.md §F.2 手工流程。
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

[[ -d "$WORKSPACE/.git" ]] || fail "$WORKSPACE 不是 git workspace"
cd "$WORKSPACE"

banner "§99.1 校验 HEAD 是迁移 commit"
LATEST_MSG=$(git log -1 --pretty=%s)
if [[ "$LATEST_MSG" != *"migrate legacy thread indexes"* ]]; then
    fail "HEAD 不是迁移 commit (message: $LATEST_MSG);拒绝自动 rollback"
fi

banner "§99.2 检查迁移 commit 是否已 push"
git fetch origin "$EXPECTED_BRANCH" 2>/dev/null || true
LOCAL_HEAD=$(git rev-parse HEAD)
REMOTE_HEAD=$(git rev-parse "origin/$EXPECTED_BRANCH" 2>/dev/null || echo "<none>")
echo "local  HEAD: $LOCAL_HEAD"
echo "remote HEAD: $REMOTE_HEAD"

if [[ "$LOCAL_HEAD" == "$REMOTE_HEAD" ]]; then
    cat <<EOM

❌ 迁移 commit 已经被 push 到 origin/$EXPECTED_BRANCH

本脚本只覆盖 push 前 reset 路径。push 后 rollback 是破坏性操作
(force push 会让所有团队成员的本地 main 错乱),请走手工流程:

  AI-docs/coding-test-plan/migration-runbook.md §F.2

简要步骤:
  cd $WORKSPACE
  git reset --hard HEAD~1
  git push --force-with-lease origin $EXPECTED_BRANCH
  # 通知团队所有人 git fetch && git reset --hard origin/$EXPECTED_BRANCH

如果 git 仓库本身受损,从最近 bundle 恢复 (runbook §F.3):
$(ls -t "$BACKUP_DIR"/pre-migration-*.bundle 2>/dev/null | head -1 | sed 's/^/  /')

EOM
    exit 1
fi

banner "§99.3 push 前回滚 (本地 HEAD~1)"
git log -2 --oneline
echo
read -r -p "确认要 'git reset --hard HEAD~1' 把迁移 commit 丢掉吗? [y/N] " ans
[[ "$ans" =~ ^[Yy]$ ]] || { echo "已取消"; exit 0; }

git reset --hard HEAD~1
git status
ok "§99 完成,workspace 回到迁移前 commit"
warn "如果原本想保留迁移再修问题,可从 reflog 找回:"
echo "  git -C $WORKSPACE reflog | head"
