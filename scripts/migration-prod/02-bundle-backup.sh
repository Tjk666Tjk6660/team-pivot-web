#!/usr/bin/env bash
# §2 离线快照: workspace 完整 git history + data.db 文件副本
# 是 git 仓库本身受损时的最终兜底。建议再 scp 一份到独立 ops 库。
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

[[ -d "$WORKSPACE/.git" ]] || fail "$WORKSPACE 不是 git workspace"

mkdir -p "$BACKUP_DIR"
TS=$(date -u +%Y%m%dT%H%M%SZ)
BUNDLE="$BACKUP_DIR/pre-migration-$TS.bundle"
DB_COPY="$BACKUP_DIR/pre-migration-$TS.data.db"

banner "§2.1 git bundle (workspace 完整 history,含所有 ref)"
cd "$WORKSPACE"
git bundle create "$BUNDLE" --all
ls -la "$BUNDLE"

banner "§2.2 data.db 文件副本"
if [[ -n "${PROD_DB_PATH:-}" && -r "$PROD_DB_PATH" ]]; then
    cp -p "$PROD_DB_PATH" "$DB_COPY"
    chmod 444 "$DB_COPY"
    ls -la "$DB_COPY"
else
    warn "PROD_DB_PATH 不可读或为空,跳过 db 备份"
fi

banner "§2.3 备份目录列表"
ls -la "$BACKUP_DIR/"

ok "§2 完成"
warn "强烈建议:把 bundle + db 副本 scp 到独立 ops 库,作为本机故障时的最终兜底"
echo "  示例: scp '$BUNDLE' '$DB_COPY' <ops-server>:<ops-vault-path>/"
echo "下一步: bash $SCRIPT_DIR/03-dryrun.sh"
