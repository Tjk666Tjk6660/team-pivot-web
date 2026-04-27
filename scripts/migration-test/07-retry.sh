#!/usr/bin/env bash
# §7 不满意,重跑:把测试仓库远端 + 本地工作目录都回滚到生产同步那个 head
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

banner "§7.1 测试仓库远端重新对齐生产"
[[ -d "$PROD_MIRROR" ]] || fail "$PROD_MIRROR 不存在,先重跑 02-reset-repo.sh"
cd "$PROD_MIRROR"
git fetch origin
git push --mirror migration-test

banner "§7.2 本地工作目录重置"
[[ -d "$TEST_WS/.git" ]] || fail "$TEST_WS 不存在,先重跑 02-reset-repo.sh"
cd "$TEST_WS"
git fetch origin
git reset --hard origin/main
git clean -fd
git status

banner "✅ §7 完成"
echo "回到 §3 重新跑: bash $SCRIPT_DIR/03-dryrun.sh"
