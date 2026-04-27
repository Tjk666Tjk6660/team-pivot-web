#!/usr/bin/env bash
# §2 重置测试仓库到生产最新 head + clone 测试仓库到工作目录 + 配 git 身份
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

banner "§2.1 bare clone 生产仓库"
rm -rf "$PROD_MIRROR"
git clone --bare "https://${GH_TOKEN}@github.com/${PROD_REPO}.git" "$PROD_MIRROR"

banner "§2.2 强制 mirror 推到测试仓库"
cd "$PROD_MIRROR"
git remote add migration-test "https://${GH_TOKEN}@github.com/${TEST_REPO}.git" 2>/dev/null \
  || git remote set-url migration-test "https://${GH_TOKEN}@github.com/${TEST_REPO}.git"
git push --mirror migration-test

# bare clone 把远端分支映射到 refs/heads/* 而非 refs/remotes/origin/*
HEAD_HASH=$(git rev-parse main)
echo "main head = $HEAD_HASH"
echo "👆 这个 hash 应该等于 GitHub 网页上 ${TEST_REPO} 当前 main 的 head"

banner "§2.3 clone 测试仓库到工作目录"
rm -rf "$TEST_WS"
git clone "https://${GH_TOKEN}@github.com/${TEST_REPO}.git" "$TEST_WS"
cd "$TEST_WS"

banner "§2.4 配 git 身份(仅本仓库)"
git config user.email "$GIT_USER_EMAIL"
git config user.name  "$GIT_USER_NAME"
git config --get user.email
git config --get user.name

banner "§2.5 状态校验"
git status
git rev-parse --abbrev-ref HEAD          # 应为 main
LEGACY_COUNT=$(ls index/ 2>/dev/null | grep -c -- '-discuss.index.yaml$' || echo 0)
echo "老 index 数量: $LEGACY_COUNT"
[[ "$LEGACY_COUNT" -gt 0 ]] || fail "测试仓库里没找到老 *-discuss.index.yaml,异常"

banner "✅ §2 完成"
echo "下一步: bash $SCRIPT_DIR/03-dryrun.sh"
