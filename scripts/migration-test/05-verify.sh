#!/usr/bin/env bash
# §5 验证迁移产物 (4 项核对 + pinyin 校验)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

[[ -d "$TEST_WS/.git" ]] || fail "$TEST_WS 不存在"
cd "$TEST_WS"

banner "§5.1 commit 的 R/A/D 分布"
git log -1 --oneline
echo "--- name-status (前 30 行) ---"
git log -1 --name-status | head -30
echo "--- 状态计数 ---"
git log -1 --name-status | awk '/^[RAD]/ {print substr($1,1,1)}' | sort | uniq -c

banner "§5.2 老命名 token 残留检查"
LEGACY_YAML=$(ls index/ 2>/dev/null | grep -c -- '-discuss.index.yaml$' || echo 0)
LEGACY_MD=$(find discussions -type f \( -name '*_proposal_*.md' -o -name '*_reply_*.md' \) 2>/dev/null | wc -l)
echo "残留老 yaml: $LEGACY_YAML  (期望 0)"
echo "残留老命名 MD: $LEGACY_MD  (期望 0)"
[[ "$LEGACY_YAML" -eq 0 && "$LEGACY_MD" -eq 0 ]] && ok "老命名清理干净" || warn "有残留,检查"

banner "§5.3 新 matter index 数量"
NEW_INDEX=$(ls index/*.index.yaml 2>/dev/null | wc -l)
echo "新 matter index: $NEW_INDEX"

banner "§5.4 mention.comments 完整迁入"
python3 -c "
import yaml, glob
total = 0; with_comment = 0
for p in sorted(glob.glob('index/*.index.yaml')):
    d = yaml.safe_load(open(p, encoding='utf-8')) or {}
    for it in d.get('timeline') or []:
        cs = it.get('comments') or []
        total += len(cs)
        if cs:
            with_comment += 1
print(f'items with comments: {with_comment}')
print(f'total comments:      {total}')
print('参考(本次生产数据): items=56, total=67  (43 carried + 24 standalone)')
"

banner "§5.5 git log --follow 跨 rename 抽查"
SAMPLE=$(find discussions -type f -name '*_think_*.md' | head -1)
if [[ -n "$SAMPLE" ]]; then
    echo "sample: $SAMPLE"
    git log --follow --oneline -- "$SAMPLE" | head -5
fi

banner "§5.6 mention 解析 pinyin vs open_id"
python3 -c "
import yaml, glob
pinyin = 0; open_id = 0
for p in sorted(glob.glob('index/*.index.yaml')):
    d = yaml.safe_load(open(p, encoding='utf-8')) or {}
    for it in d.get('timeline') or []:
        for c in it.get('comments') or []:
            for m in c.get('mentions') or []:
                if str(m).startswith('ou_'):
                    open_id += 1
                else:
                    pinyin += 1
print(f'pinyin解析: {pinyin}')
print(f'open_id 兜底: {open_id}')
print('--db-path 模式期望 pinyin >> open_id')
print('--no-users-db 模式期望 全是 open_id')
"

banner "✅ §5 完成"
echo "如果 4 项都通过,可选 push: bash $SCRIPT_DIR/06-push.sh"
echo "如果不满意要重跑:        bash $SCRIPT_DIR/07-retry.sh"
echo "彻底清理:                bash $SCRIPT_DIR/08-cleanup.sh"
