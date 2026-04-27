#!/usr/bin/env bash
# §7 启服 + 烟测
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

banner "§7.1 启动 $SERVICE_NAME"
sudo systemctl start "$SERVICE_NAME"
sleep 3
sudo systemctl status "$SERVICE_NAME" --no-pager | head -15

banner "§7.2 回环烟测 /me (期望 401 not logged in)"
HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/me 2>/dev/null || echo "000")
echo "HTTP code: $HTTP_CODE"

if [[ "$HTTP_CODE" == "401" ]]; then
    ok "服务已活,后端响应正常"
elif [[ "$HTTP_CODE" == "000" ]]; then
    warn "curl 失败,服务可能没起来;查日志: sudo journalctl -u $SERVICE_NAME -n 100"
else
    warn "HTTP $HTTP_CODE 不是预期 401,检查日志: sudo journalctl -u $SERVICE_NAME -n 100"
fi

banner "§7.3 简要日志(最近 30 行)"
sudo journalctl -u "$SERVICE_NAME" -n 30 --no-pager | tail -30

ok "§7 完成"
warn "请人工再用浏览器打开生产域名做完整 UI 烟测:"
echo "  - 飞书登录正常"
echo "  - 主页能列出几个 matter"
echo "  - 抽查任一 matter 的 timeline 完整、quote/refer/comments 都对"
echo "  - 新建一个 think/act,飞书通知发出"
echo
echo "如果 UI 烟测失败 → 走 99-rollback.sh + migration-runbook.md §F.2"
