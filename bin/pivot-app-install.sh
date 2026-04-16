#!/usr/bin/env bash
# pivot-app-install.sh — 在 EC/OpenClaw 沙箱中安装或升级 Team-Pivot skill。
#
# 幂等：首次运行 = 安装，再次运行 = 升级。
#
# 用法（在 EC chat 或飞书中让 bot 执行）：
#   bash <(curl -sL https://raw.githubusercontent.com/hashSTACS-Global/team-pivot/main/bin/pivot-app-install.sh)
#
# 或者先 clone 再运行：
#   git clone https://github.com/hashSTACS-Global/team-pivot.git
#   bash team-pivot/bin/pivot-app-install.sh

set -e

REPO_URL="https://github.com/hashSTACS-Global/team-pivot.git"
REMOTE_CONFIG_URL="https://raw.githubusercontent.com/hashSTACS-Global/team-pivot/main/pivot.yaml"

# ---------------------------------------------------------------------------
# 版本比较辅助函数
# ---------------------------------------------------------------------------
get_local_version() {
  local config="$1/pivot.yaml"
  [ -f "$config" ] && grep -m1 '^version:' "$config" | sed 's/version: *//' || echo "0.0.0"
}

get_remote_version() {
  curl -sL --max-time 5 "$REMOTE_CONFIG_URL" 2>/dev/null | grep -m1 '^version:' | sed 's/version: *//' || echo ""
}

# 返回 0 如果 $1 < $2（需要升级），返回 1 如果 $1 >= $2（已是最新）
version_lt() {
  [ "$1" = "$2" ] && return 1
  local lowest
  lowest=$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -n1)
  [ "$lowest" = "$1" ]
}

# ---------------------------------------------------------------------------
# 1. 检测 tenant root
# ---------------------------------------------------------------------------
echo "[INFO] pwd=$(pwd)"
TENANT_ROOT="$(pwd | sed -E 's|(.*/\.enclaws/tenants/[^/]+).*|\1|')"
if [ "$TENANT_ROOT" = "$(pwd)" ] || [ ! -d "$TENANT_ROOT" ]; then
  echo "[FAIL] 未检测到 EC 沙箱环境 (TENANT_ROOT=$TENANT_ROOT)"
  echo "  如果你在本地机器上，请用：git clone $REPO_URL && bash team-pivot/bin/pivot-cli-install.sh"
  exit 1
fi

REPO_DIR="$TENANT_ROOT/team-pivot"
SKILL_DIR="$TENANT_ROOT/skills/pivot"
echo "[INFO] TENANT_ROOT=$TENANT_ROOT"

# ---------------------------------------------------------------------------
# 2. 安装或升级
# ---------------------------------------------------------------------------
if [ -d "$REPO_DIR/.git" ]; then
  # 已存在 → 检查是否需要升级
  LOCAL_VER=$(get_local_version "$REPO_DIR")
  REMOTE_VER=$(get_remote_version)
  echo "[INFO] 已有安装: local=$LOCAL_VER, remote=${REMOTE_VER:-unreachable}"

  if [ -z "$REMOTE_VER" ]; then
    echo "[WARN] 无法获取远端版本号，跳过版本检查，直接 git pull..."
    cd "$REPO_DIR"
    git pull --ff-only 2>&1 | tail -1
    echo "✅ 代码已更新。"
  elif version_lt "$LOCAL_VER" "$REMOTE_VER"; then
    echo "[INFO] 需要升级: $LOCAL_VER → $REMOTE_VER"
    cd "$REPO_DIR"
    git pull --ff-only 2>&1 | tail -1
    echo "✅ 已升级到 $REMOTE_VER"
  else
    echo "✅ 当前版本 $LOCAL_VER 已是最新，无需升级。"
  fi
else
  # 不存在 → 首次安装
  echo "[INFO] 首次安装，目标: $REPO_DIR"

  # 如果当前目录下有刚 clone 的 team-pivot，直接移过去
  if [ -d "team-pivot/.git" ]; then
    echo "[INFO] 检测到当前目录下已有 clone，移动到 $REPO_DIR"
    rm -rf "$REPO_DIR"
    mv team-pivot "$REPO_DIR"
  else
    echo "[INFO] git clone --depth 1 $REPO_URL"
    git clone --depth 1 "$REPO_URL" "$REPO_DIR" 2>&1 | tail -1
  fi

  echo "✅ 代码已安装到 $REPO_DIR"
fi

# ---------------------------------------------------------------------------
# 3. 注册 skill 入口（每次都刷新，确保 SKILL.md 是最新的）
# ---------------------------------------------------------------------------
mkdir -p "$SKILL_DIR"
cp "$REPO_DIR/SKILL.md" "$SKILL_DIR/SKILL.md"
echo "✅ skill 已注册: $SKILL_DIR/SKILL.md"

# ---------------------------------------------------------------------------
# 4. 报告结果
# ---------------------------------------------------------------------------
CONFIG_FILE="$REPO_DIR/pivot-config.yaml"
HAS_CONFIG="no"
HAS_DATA_SPACE="no"
[ -f "$CONFIG_FILE" ] && ! grep -q 'data_space_repo: *$' "$CONFIG_FILE" && HAS_CONFIG="yes"
[ -d "$REPO_DIR/data_space/.git" ] && HAS_DATA_SPACE="yes"
echo "[INFO] config=$HAS_CONFIG, data_space=$HAS_DATA_SPACE"

if [ "$HAS_CONFIG" = "no" ] || [ "$HAS_DATA_SPACE" = "no" ]; then
  echo ""
  echo "=== 安装完成，待配置 ==="
  echo "请开启新会话。首次使用 team-pivot 时，会自动引导你完成配置。"
else
  INSTALLED_VER=$(get_local_version "$REPO_DIR")
  echo ""
  echo "=== 升级完成 (v$INSTALLED_VER) ==="
  echo "配置和 data_space 均已就绪，请开启新会话以加载最新 skill。"
fi
