# 共用 helper,被所有 step 脚本 source
# 调用方需要先设置 SCRIPT_DIR 变量
set -euo pipefail

# 保 uv 在 PATH 里(若用户已装但还没进 shell PATH)
export PATH="$HOME/.local/bin:$PATH"

# ---- 校验调用方 ----
if [[ -z "${SCRIPT_DIR:-}" ]]; then
    echo "❌ lib.sh 被错误地 source:调用方需要先设 SCRIPT_DIR"
    exit 1
fi

# ---- 自动定位 team-pivot-web ----
# 这些脚本住在 <repo>/scripts/migration-test/ 下,往上两级就是 repo 根
PIVOT_CODE="$(cd "$SCRIPT_DIR/../.." && pwd)"
export PIVOT_CODE
if [[ ! -f "$PIVOT_CODE/scripts/migrate_index_schema.py" ]]; then
    echo "❌ 看起来不在 team-pivot-web 仓库里"
    echo "   找不到 $PIVOT_CODE/scripts/migrate_index_schema.py"
    echo "   请先 git clone team-pivot-web,从仓库内的 scripts/migration-test/ 目录运行"
    exit 1
fi

# ---- Source env.init ----
if [[ ! -f "$SCRIPT_DIR/env.init" ]]; then
    echo "❌ $SCRIPT_DIR/env.init 不存在"
    echo "   先 cp env.init.example env.init 并填好变量"
    exit 1
fi
# shellcheck source=/dev/null
source "$SCRIPT_DIR/env.init"

# ---- 校验必填变量 ----
_check_var() {
    local name="$1"
    local val="${!name:-}"
    if [[ -z "$val" || "$val" == *'<'*'>'* ]]; then
        echo "❌ env.init 里 $name 没填或仍是占位符:'$val'"
        exit 1
    fi
}
# PROD_DB_PATH 允许留空(走 --no-users-db),所以不在必填里
for v in GH_TOKEN PROD_REPO TEST_REPO PIVOT_REPO PIVOT_BRANCH WORKDIR \
         GIT_USER_EMAIL GIT_USER_NAME; do
    _check_var "$v"
done

# ---- 派生路径 ----
mkdir -p "$WORKDIR"
export PROD_MIRROR="$WORKDIR/prod-mirror.git"
export TEST_WS="$WORKDIR/test-workspace"
export REPORT_DRYRUN="$WORKDIR/migration-report-dryrun.json"
export REPORT_APPLY="$WORKDIR/migration-report-apply.json"

# ---- DB_FLAG ----
# 迁移脚本通过 SQLite URI mode=ro 只读打开 PROD_DB_PATH,绝不写入,
# 可以直接指向生产 data.db。详见 scripts/migrate_index_schema.py 的
# _ReadOnlyUserView 类。
if [[ -n "${PROD_DB_PATH:-}" ]]; then
    if [[ -r "$PROD_DB_PATH" ]]; then
        export DB_FLAG="--db-path $PROD_DB_PATH"
    else
        echo "❌ PROD_DB_PATH=$PROD_DB_PATH 不可读"
        echo "   核对路径,或留空 PROD_DB_PATH 走 --no-users-db 兜底"
        exit 1
    fi
else
    export DB_FLAG="--no-users-db"
fi

# ---- 输出 helpers ----
banner() { echo; echo "=== $* ==="; }
ok()     { echo "✅ $*"; }
warn()   { echo "⚠️  $*"; }
fail()   { echo "❌ $*"; exit 1; }
