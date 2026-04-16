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
# 日志：同时输出到 stdout 和临时日志文件
# ---------------------------------------------------------------------------
_TMP_LOG="$(pwd)/pivot-app-install-$$.log"
_FINAL_LOG=""  # 安装成功后移到 DATA_DIR
exec > >(tee -a "$_TMP_LOG") 2>&1

_move_log() {
  if [ -n "$_FINAL_LOG" ] && [ -f "$_TMP_LOG" ]; then
    mkdir -p "$(dirname "$_FINAL_LOG")"
    cp "$_TMP_LOG" "$_FINAL_LOG"
  fi
  rm -f "$_TMP_LOG"
}
trap _move_log EXIT

log_info()  { echo "[INFO]  $*"; }
log_warn()  { echo "[WARN]  $*"; }
log_error() { echo "[ERROR] $*"; }
log_debug() { echo "[DEBUG] $*"; }

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
# 0. 环境信息
# ---------------------------------------------------------------------------
log_info "========== pivot-app-install.sh 开始 =========="
log_info "date=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
log_info "pwd=$(pwd)"
log_info "whoami=$(whoami)"
log_info "HOME=$HOME"
log_info "shell=$SHELL"
log_info "uname=$(uname -s -m)"
log_debug "PATH=$PATH"
log_debug "\$0=$0"
log_debug "\$BASH_SOURCE=${BASH_SOURCE[0]:-n/a}"

# ---------------------------------------------------------------------------
# 1. 检测 tenant root
# ---------------------------------------------------------------------------
log_info "--- 步骤 1: 检测 tenant root ---"
RAW_PWD="$(pwd)"
TENANT_ROOT="$(echo "$RAW_PWD" | sed -E 's|(.*/\.enclaws/tenants/[^/]+).*|\1|')"
log_info "RAW_PWD=$RAW_PWD"
log_info "TENANT_ROOT=$TENANT_ROOT"

if [ "$TENANT_ROOT" = "$RAW_PWD" ]; then
  log_error "sed 未能从 pwd 中截取 tenant root（pwd 不包含 .enclaws/tenants/{id}/ 子路径）"
  log_error "pwd=$RAW_PWD"
  log_error "期望 pwd 格式: .../.enclaws/tenants/{tenant_id}/...（需要在 tenant 子目录下执行）"
  echo "[FAIL] 未检测到 EC 沙箱环境 (TENANT_ROOT=$TENANT_ROOT)"
  echo "  如果你在本地机器上，请用：git clone $REPO_URL && bash team-pivot/client/cli-client/pivot-cli-install.sh"
  exit 1
fi

if [ ! -d "$TENANT_ROOT" ]; then
  log_error "TENANT_ROOT 目录不存在: $TENANT_ROOT"
  echo "[FAIL] TENANT_ROOT 目录不存在"
  exit 1
fi

log_info "TENANT_ROOT 检测成功: $TENANT_ROOT"

TMP_DIR="$TENANT_ROOT/tmp/team-pivot"
SKILL_DIR="$TENANT_ROOT/skills/team-pivot"
DATA_DIR="$TENANT_ROOT/workspace/skill-team-pivot"
log_info "TMP_DIR=$TMP_DIR"
log_info "SKILL_DIR=$SKILL_DIR"
log_info "DATA_DIR=$DATA_DIR"
_FINAL_LOG="$DATA_DIR/install.log"
log_info "LOG_FILE=$_FINAL_LOG"

# ---------------------------------------------------------------------------
# 2. 获取源码到临时目录
# ---------------------------------------------------------------------------
log_info "--- 步骤 2: 获取源码 ---"
NEED_COPY=false

if [ -d "$TMP_DIR/.git" ]; then
  log_info "临时目录已存在: $TMP_DIR"
  LOCAL_VER=$(get_local_version "$TMP_DIR")
  REMOTE_VER=$(get_remote_version)
  log_info "本地版本=$LOCAL_VER, 远端版本=${REMOTE_VER:-unreachable}"

  if [ -z "$REMOTE_VER" ]; then
    log_warn "无法获取远端版本号，跳过版本检查，直接 git pull..."
    cd "$TMP_DIR"
    log_debug "cd $TMP_DIR, pwd=$(pwd)"
    git pull --ff-only 2>&1 | tail -1
    NEED_COPY=true
  elif version_lt "$LOCAL_VER" "$REMOTE_VER"; then
    log_info "需要升级: $LOCAL_VER → $REMOTE_VER"
    cd "$TMP_DIR"
    log_debug "cd $TMP_DIR, pwd=$(pwd)"
    git pull --ff-only 2>&1 | tail -1
    NEED_COPY=true
  else
    if [ ! -f "$SKILL_DIR/SKILL.md" ]; then
      log_info "版本已最新但 skill 目录不存在，需要复制"
      NEED_COPY=true
    else
      log_info "当前版本 $LOCAL_VER 已是最新，无需升级"
    fi
  fi
else
  log_info "临时目录不存在，首次安装"
  mkdir -p "$(dirname "$TMP_DIR")"
  log_debug "创建 tmp 父目录: $(dirname "$TMP_DIR")"

  if [ -d "team-pivot/.git" ]; then
    log_info "检测到当前目录下已有 clone (team-pivot/.git)，移动到临时目录"
    rm -rf "$TMP_DIR"
    mv team-pivot "$TMP_DIR"
    log_info "mv team-pivot → $TMP_DIR 完成"
  else
    log_info "当前目录下无 team-pivot/.git，执行 git clone"
    log_info "git clone --depth 1 $REPO_URL → $TMP_DIR"
    git clone --depth 1 "$REPO_URL" "$TMP_DIR" 2>&1
    log_info "git clone 完成, exit_code=$?"
  fi
  NEED_COPY=true
fi

log_info "NEED_COPY=$NEED_COPY"

# ---------------------------------------------------------------------------
# 3. 复制运行必需的文件到 skill 目录
# ---------------------------------------------------------------------------
log_info "--- 步骤 3: 复制文件到 skill 目录 ---"
if [ "$NEED_COPY" = true ]; then
  log_info "开始复制文件到 $SKILL_DIR"
  mkdir -p "$SKILL_DIR/bin"

  log_debug "cp SKILL.md"
  cp "$TMP_DIR/SKILL.md"               "$SKILL_DIR/SKILL.md"
  log_debug "cp pivot.yaml"
  cp "$TMP_DIR/pivot.yaml"             "$SKILL_DIR/pivot.yaml"
  log_debug "cp pivot-runner.py"
  cp "$TMP_DIR/bin/pivot-runner.py"     "$SKILL_DIR/bin/pivot-runner.py"
  log_debug "cp pivot-check-config.sh"
  cp "$TMP_DIR/bin/pivot-check-config.sh" "$SKILL_DIR/bin/pivot-check-config.sh"

  log_debug "同步 pipelines/ 和 tools/"
  rm -rf "$SKILL_DIR/pipelines" "$SKILL_DIR/tools"
  cp -R "$TMP_DIR/pipelines" "$SKILL_DIR/pipelines"
  cp -R "$TMP_DIR/tools"     "$SKILL_DIR/tools"

  INSTALLED_VER=$(get_local_version "$SKILL_DIR")
  log_info "文件复制完成, 版本=$INSTALLED_VER"
  echo "✅ 已安装 v$INSTALLED_VER 到 $SKILL_DIR"

  log_debug "skill 目录内容:"
  ls -la "$SKILL_DIR/" 2>&1 | while read line; do log_debug "  $line"; done
else
  log_info "跳过复制（NEED_COPY=false）"
fi

# ---------------------------------------------------------------------------
# 4. 创建数据目录并迁移旧数据
# ---------------------------------------------------------------------------
log_info "--- 步骤 4: 数据目录与迁移 ---"
mkdir -p "$DATA_DIR"
log_info "DATA_DIR 已创建/确认: $DATA_DIR"

# 从旧安装路径迁移（$TENANT_ROOT/team-pivot）
OLD_DIR="$TENANT_ROOT/team-pivot"
if [ -d "$OLD_DIR" ]; then
  log_info "检测到旧安装路径: $OLD_DIR"
  if [ -f "$OLD_DIR/pivot-config.yaml" ] && [ ! -f "$DATA_DIR/pivot-config.yaml" ]; then
    mv "$OLD_DIR/pivot-config.yaml" "$DATA_DIR/pivot-config.yaml"
    log_info "迁移 pivot-config.yaml: $OLD_DIR → $DATA_DIR"
  fi
  if [ -d "$OLD_DIR/data_space/.git" ] && [ ! -d "$DATA_DIR/data_space" ]; then
    mv "$OLD_DIR/data_space" "$DATA_DIR/data_space"
    log_info "迁移 data_space: $OLD_DIR → $DATA_DIR"
  fi
  rm -rf "$OLD_DIR"
  log_info "已删除旧安装路径: $OLD_DIR"
else
  log_debug "旧安装路径不存在: $OLD_DIR（无需迁移）"
fi

# 从 skill 目录迁移（之前版本把数据放在 skill 目录下）
if [ -f "$SKILL_DIR/pivot-config.yaml" ] && [ ! -f "$DATA_DIR/pivot-config.yaml" ]; then
  mv "$SKILL_DIR/pivot-config.yaml" "$DATA_DIR/pivot-config.yaml"
  log_info "从 skill 目录迁移 pivot-config.yaml → $DATA_DIR"
fi
if [ -d "$SKILL_DIR/data_space/.git" ] && [ ! -d "$DATA_DIR/data_space" ]; then
  mv "$SKILL_DIR/data_space" "$DATA_DIR/data_space"
  log_info "从 skill 目录迁移 data_space → $DATA_DIR"
fi
# 清理 skill 目录中残留的数据文件
rm -f "$SKILL_DIR/pivot-config.yaml" 2>/dev/null
rm -rf "$SKILL_DIR/data_space" 2>/dev/null

# 清理旧的 skills/pivot 目录
OLD_SKILL="$TENANT_ROOT/skills/pivot"
if [ -d "$OLD_SKILL" ] && [ "$OLD_SKILL" != "$SKILL_DIR" ]; then
  rm -rf "$OLD_SKILL"
  log_info "已清理旧 skill 目录: $OLD_SKILL"
fi

log_debug "DATA_DIR 内容:"
ls -la "$DATA_DIR/" 2>&1 | while read line; do log_debug "  $line"; done

# ---------------------------------------------------------------------------
# 5. 清理临时目录
# ---------------------------------------------------------------------------
log_info "--- 步骤 5: 清理临时目录 ---"
rm -rf "$TMP_DIR"
rmdir "$TENANT_ROOT/tmp" 2>/dev/null || true
log_info "临时目录已清理"

# ---------------------------------------------------------------------------
# 6. 报告结果
# ---------------------------------------------------------------------------
log_info "--- 步骤 6: 最终状态 ---"
CONFIG_FILE="$DATA_DIR/pivot-config.yaml"
HAS_CONFIG="no"
HAS_DATA_SPACE="no"
[ -f "$CONFIG_FILE" ] && ! grep -q 'data_space_repo: *$' "$CONFIG_FILE" && HAS_CONFIG="yes"
[ -d "$DATA_DIR/data_space/.git" ] && HAS_DATA_SPACE="yes"

log_info "CONFIG_FILE=$CONFIG_FILE (exists=$([ -f "$CONFIG_FILE" ] && echo yes || echo no))"
log_info "HAS_CONFIG=$HAS_CONFIG"
log_info "HAS_DATA_SPACE=$HAS_DATA_SPACE"
log_info "SKILL_DIR=$SKILL_DIR (exists=$([ -d "$SKILL_DIR" ] && echo yes || echo no))"
log_info "DATA_DIR=$DATA_DIR (exists=$([ -d "$DATA_DIR" ] && echo yes || echo no))"

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

log_info "========== pivot-app-install.sh 结束 =========="
