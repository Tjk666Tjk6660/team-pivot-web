#!/usr/bin/env bash
# pivot-check-config.sh — 检查 pivot-config.yaml 配置是否完整
#
# 输出 JSON：
#   {"ready": true}
#   {"ready": false, "missing": ["data_space_repo", "git_token"]}
#
# 用法：bash $REPO_PATH/bin/pivot-check-config.sh $REPO_PATH

set -e

REPO_PATH="${1:-.}"
CONFIG_FILE="$REPO_PATH/pivot-config.yaml"

if [ ! -f "$CONFIG_FILE" ]; then
  echo '{"ready": false, "missing": ["config_file"], "error": "pivot-config.yaml not found"}'
  exit 0
fi

MISSING=""

grep -q 'data_space_repo: *$' "$CONFIG_FILE" && MISSING="${MISSING}\"data_space_repo\","
grep -q 'git_token: *$' "$CONFIG_FILE" && MISSING="${MISSING}\"git_token\","

if [ ! -d "$REPO_PATH/data_space" ]; then
  MISSING="${MISSING}\"data_space_dir\","
fi

if [ -z "$MISSING" ]; then
  echo '{"ready": true}'
else
  # 去掉末尾逗号
  MISSING="${MISSING%,}"
  echo "{\"ready\": false, \"missing\": [$MISSING]}"
fi
