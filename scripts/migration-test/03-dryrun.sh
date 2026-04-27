#!/usr/bin/env bash
# §3 迁移 dry-run(不写盘)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

[[ -d "$TEST_WS/.git" ]] || fail "$TEST_WS 不存在,先跑 02-reset-repo.sh"

banner "§3 dry-run (DB_FLAG: $DB_FLAG)"
cd "$PIVOT_CODE"
uv run python scripts/migrate_index_schema.py \
    --workspace "$TEST_WS" \
    $DB_FLAG \
    --report "$REPORT_DRYRUN"

banner "§3 报告摘要"
python3 -c "
import json
r = json.load(open('$REPORT_DRYRUN', encoding='utf-8'))
print(f\"legacy={r['legacy_count']} migrated={r['migrated_count']} skipped={r['skipped_count']} errors={len(r['errors'])}\")
warn = sum(1 for t in r['threads'] if t.get('warnings'))
print(f'threads with warnings: {warn}')
for t in r['threads']:
    if t.get('warnings'):
        print(f\"  - {t.get('slug')}: {len(t['warnings'])} warnings\")
        for w in t['warnings'][:3]:
            print(f'      · {w}')
if r['errors']:
    print('ERRORS:')
    for e in r['errors']:
        print(f'  - {e}')
"

banner "✅ §3 完成"
echo "如果 errors=0 且 warnings 都可接受,继续 §4"
echo "下一步: bash $SCRIPT_DIR/04-apply.sh"
