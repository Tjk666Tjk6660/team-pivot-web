#!/usr/bin/env bash
# §8 完事清理
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

banner "§8 清理 $WORKDIR 下的产物"
rm -rf "$PROD_MIRROR"
rm -rf "$TEST_WS"

# 注意:PROD_DB_PATH 是用户填的生产路径,**绝不删**
# (脚本对它只读,但删它是另一回事——必须保护)
ok "保留 PROD_DB_PATH=${PROD_DB_PATH:-(空)} 不动"

# 迁移报告留着可查
ls -la "$WORKDIR" 2>/dev/null || true

ok "§8 完成"
warn "迁移报告保留在 $WORKDIR/migration-report-*.json,如需归档自取"
