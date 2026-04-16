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
  echo "  如果你在本地机器上，请用：git clone $REPO_URL && bash team-pivot/client/cli-client/pivot-cli-install.sh"
  exit 1
fi

TMP_DIR="$TENANT_ROOT/tmp/team-pivot"
SKILL_DIR="$TENANT_ROOT/skills/team-pivot"
DATA_DIR="$TENANT_ROOT/workspace/skill-team-pivot"
echo "[INFO] TENANT_ROOT=$TENANT_ROOT"
echo "[INFO] SKILL_DIR=$SKILL_DIR"
echo "[INFO] DATA_DIR=$DATA_DIR"

# ---------------------------------------------------------------------------
# 2. 获取源码到临时目录
# ---------------------------------------------------------------------------
NEED_COPY=false

if [ -d "$TMP_DIR/.git" ]; then
  # 临时目录已存在 → git pull
  LOCAL_VER=$(get_local_version "$TMP_DIR")
  REMOTE_VER=$(get_remote_version)
  echo "[INFO] 已有缓存: local=$LOCAL_VER, remote=${REMOTE_VER:-unreachable}"

  if [ -z "$REMOTE_VER" ]; then
    echo "[WARN] 无法获取远端版本号，跳过版本检查，直接 git pull..."
    cd "$TMP_DIR"
    git pull --ff-only 2>&1 | tail -1
    NEED_COPY=true
  elif version_lt "$LOCAL_VER" "$REMOTE_VER"; then
    echo "[INFO] 需要升级: $LOCAL_VER → $REMOTE_VER"
    cd "$TMP_DIR"
    git pull --ff-only 2>&1 | tail -1
    NEED_COPY=true
  else
    # 检查 skill 目录是否存在，不存在也需要复制
    if [ ! -f "$SKILL_DIR/SKILL.md" ]; then
      NEED_COPY=true
    else
      echo "✅ 当前版本 $LOCAL_VER 已是最新，无需升级。"
    fi
  fi
else
  # 首次安装
  mkdir -p "$(dirname "$TMP_DIR")"

  # 如果当前目录下有刚 clone 的 team-pivot，直接移过去
  if [ -d "team-pivot/.git" ]; then
    echo "[INFO] 检测到当前目录下已有 clone，移动到临时目录"
    rm -rf "$TMP_DIR"
    mv team-pivot "$TMP_DIR"
  else
    echo "[INFO] git clone --depth 1 $REPO_URL → $TMP_DIR"
    git clone --depth 1 "$REPO_URL" "$TMP_DIR" 2>&1 | tail -1
  fi
  NEED_COPY=true
fi

# ---------------------------------------------------------------------------
# 3. 复制运行必需的文件到 skill 目录
# ---------------------------------------------------------------------------
if [ "$NEED_COPY" = true ]; then
  echo "[INFO] 复制文件到 $SKILL_DIR ..."
  mkdir -p "$SKILL_DIR/bin"

  # 核心文件
  cp "$TMP_DIR/SKILL.md"               "$SKILL_DIR/SKILL.md"
  cp "$TMP_DIR/pivot.yaml"             "$SKILL_DIR/pivot.yaml"
  cp "$TMP_DIR/bin/pivot-runner.py"     "$SKILL_DIR/bin/pivot-runner.py"
  cp "$TMP_DIR/bin/pivot-check-config.sh" "$SKILL_DIR/bin/pivot-check-config.sh"

  # pipelines 和 tools（整目录同步，删除已移除的文件）
  rm -rf "$SKILL_DIR/pipelines" "$SKILL_DIR/tools"
  cp -R "$TMP_DIR/pipelines" "$SKILL_DIR/pipelines"
  cp -R "$TMP_DIR/tools"     "$SKILL_DIR/tools"

  INSTALLED_VER=$(get_local_version "$SKILL_DIR")
  echo "✅ 已安装 v$INSTALLED_VER 到 $SKILL_DIR"
fi

# ---------------------------------------------------------------------------
# 4. 创建数据目录并迁移旧数据
# ---------------------------------------------------------------------------
mkdir -p "$DATA_DIR"

# 从旧安装路径迁移（$TENANT_ROOT/team-pivot）
OLD_DIR="$TENANT_ROOT/team-pivot"
if [ -d "$OLD_DIR" ]; then
  [ -f "$OLD_DIR/pivot-config.yaml" ] && [ ! -f "$DATA_DIR/pivot-config.yaml" ] \
    && mv "$OLD_DIR/pivot-config.yaml" "$DATA_DIR/pivot-config.yaml"
  [ -d "$OLD_DIR/data_space/.git" ] && [ ! -d "$DATA_DIR/data_space" ] \
    && mv "$OLD_DIR/data_space" "$DATA_DIR/data_space"
  rm -rf "$OLD_DIR"
  echo "[INFO] 已从旧路径迁移数据: $OLD_DIR → $DATA_DIR"
fi

# 从 skill 目录迁移（之前版本把数据放在 skill 目录下）
if [ -f "$SKILL_DIR/pivot-config.yaml" ] && [ ! -f "$DATA_DIR/pivot-config.yaml" ]; then
  mv "$SKILL_DIR/pivot-config.yaml" "$DATA_DIR/pivot-config.yaml"
  echo "[INFO] 已从 skill 目录迁移 pivot-config.yaml → $DATA_DIR"
fi
if [ -d "$SKILL_DIR/data_space/.git" ] && [ ! -d "$DATA_DIR/data_space" ]; then
  mv "$SKILL_DIR/data_space" "$DATA_DIR/data_space"
  echo "[INFO] 已从 skill 目录迁移 data_space → $DATA_DIR"
fi
# 清理 skill 目录中残留的数据文件
rm -f "$SKILL_DIR/pivot-config.yaml" 2>/dev/null
rm -rf "$SKILL_DIR/data_space" 2>/dev/null

# 清理旧的 skills/pivot 目录
OLD_SKILL="$TENANT_ROOT/skills/pivot"
if [ -d "$OLD_SKILL" ] && [ "$OLD_SKILL" != "$SKILL_DIR" ]; then
  rm -rf "$OLD_SKILL"
  echo "[INFO] 已清理旧 skill 目录: $OLD_SKILL"
fi

# ---------------------------------------------------------------------------
# 5. 清理临时目录
# ---------------------------------------------------------------------------
rm -rf "$TMP_DIR"
rmdir "$TENANT_ROOT/tmp" 2>/dev/null || true
echo "[INFO] 已清理临时目录"

# ---------------------------------------------------------------------------
# 6. 报告结果
# ---------------------------------------------------------------------------
CONFIG_FILE="$DATA_DIR/pivot-config.yaml"
HAS_CONFIG="no"
HAS_DATA_SPACE="no"
[ -f "$CONFIG_FILE" ] && ! grep -q 'data_space_repo: *$' "$CONFIG_FILE" && HAS_CONFIG="yes"
[ -d "$DATA_DIR/data_space/.git" ] && HAS_DATA_SPACE="yes"
echo "[INFO] config=$HAS_CONFIG, data_space=$HAS_DATA_SPACE"
echo "[INFO] DATA_DIR=$DATA_DIR"

if [ "$HAS_CONFIG" = "no" ] || [ "$HAS_DATA_SPACE" = "no" ]; then
  echo ""
  echo "=== 安装完成，待配置 ==="
  echo "请开启新会话。首次使用 team-pivot 时，会自动引导你完成配置。"
else
  INSTALLED_VER=$(get_local_version "$SKILL_DIR")
  echo ""
  echo "=== 升级完成 (v$INSTALLED_VER) ==="
  echo "配置和 data_space 均已就绪，请开启新会话以加载最新 skill。"
fi
