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

# ---------------------------------------------------------------------------
# 1. 检测 tenant root
# ---------------------------------------------------------------------------
TENANT_ROOT="$(pwd | sed -E 's|(.*/\.enclaws/tenants/[^/]+).*|\1|')"
if [ "$TENANT_ROOT" = "$(pwd)" ] || [ ! -d "$TENANT_ROOT" ]; then
  echo "未检测到 EC 沙箱环境。如果你在本地机器上，请用："
  echo "  git clone $REPO_URL && bash team-pivot/bin/pivot-cli-install.sh"
  exit 1
fi

REPO_DIR="$TENANT_ROOT/team-pivot"
SKILL_DIR="$TENANT_ROOT/skills/pivot"

# ---------------------------------------------------------------------------
# 2. 安装或升级
# ---------------------------------------------------------------------------
if [ -d "$REPO_DIR/.git" ]; then
  # 已存在 → 升级
  echo "检测到已安装的 team-pivot，正在升级..."
  cd "$REPO_DIR"
  git pull --ff-only
  echo "✅ 代码已更新到最新版本。"
else
  # 不存在 → 首次安装
  echo "正在安装 team-pivot..."

  # 如果当前目录下有刚 clone 的 team-pivot，直接移过去
  if [ -d "team-pivot/.git" ]; then
    rm -rf "$REPO_DIR"
    mv team-pivot "$REPO_DIR"
  else
    git clone --depth 1 "$REPO_URL" "$REPO_DIR"
  fi

  echo "✅ 代码已安装到 $REPO_DIR"
fi

# ---------------------------------------------------------------------------
# 3. 注册 skill 入口（每次都刷新，确保 SKILL.md 是最新的）
# ---------------------------------------------------------------------------
mkdir -p "$SKILL_DIR"
cp "$REPO_DIR/SKILL.md" "$SKILL_DIR/SKILL.md"
echo "✅ skill 入口已注册到 $SKILL_DIR/SKILL.md"

# ---------------------------------------------------------------------------
# 4. 创建配置文件（如果不存在）
# ---------------------------------------------------------------------------
CONFIG_FILE="$REPO_DIR/pivot-config.yaml"
if [ ! -f "$CONFIG_FILE" ]; then
  cat > "$CONFIG_FILE" <<'EOF'
# Team-Pivot 配置文件
# 空字段将在首次使用时通过飞书卡片引导填写

data_space_repo:
git_token:
git_user: pivot-bot
git_email: pivot-bot@enclaws.local
admin_user:
EOF
  echo "✅ 配置文件已创建：$CONFIG_FILE（待填写）"
fi

# ---------------------------------------------------------------------------
# 5. 报告结果
# ---------------------------------------------------------------------------
# 检查必填字段是否已填写
if grep -q 'data_space_repo: *$' "$CONFIG_FILE" || ! [ -d "$REPO_DIR/data_space" ]; then
  echo ""
  echo "=== 安装完成，待配置 ==="
  echo "请开启新会话。首次使用 team-pivot 时，会自动引导你完成配置。"
else
  echo ""
  echo "=== 升级完成 ==="
  echo "配置和 data_space 均已就绪，请开启新会话以加载最新 skill。"
fi
