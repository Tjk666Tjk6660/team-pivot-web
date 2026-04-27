#!/usr/bin/env bash
# §6 (可选) 把迁移结果推到测试仓库,让 GitHub 网页能 review
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

[[ -d "$TEST_WS/.git" ]] || fail "$TEST_WS 不存在"
cd "$TEST_WS"

banner "§6 推送当前 main 到测试仓库"
git log -1 --oneline
git push origin main

banner "✅ §6 完成"
echo "GitHub 网页查看: https://github.com/${TEST_REPO}/commits/main"
