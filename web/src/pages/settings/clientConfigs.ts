/**
 * Streamable HTTP MCP endpoint (single URL, both GET + POST).
 *
 * Dev: hit the FastAPI backend directly on :8000 — the Vite dev server's
 * SPA fallback swallows `.well-known/oauth-*` probes, which makes external
 * MCP clients fail auth handshake. Prod is same-origin behind a real proxy.
 */
const MCP_URL = import.meta.env.DEV
  ? "http://127.0.0.1:8000/mcp"
  : typeof window !== "undefined"
    ? `${window.location.origin}/mcp`
    : "https://pivot.enclaws.ai/mcp";


/**
 * Claude Code: a prompt the user pastes into Claude Code itself,
 * asking Claude to update ~/.claude.json for them.
 */
export function claudeCodePrompt(token: string): string {
  return [
    `请帮我把下面的 MCP 服务器加到 Claude Code 的配置里。`,
    ``,
    `服务器名: pivot`,
    `传输类型: http (Streamable HTTP)`,
    `URL: ${MCP_URL}`,
    `Authorization 头: Bearer ${token}`,
    ``,
    `请修改 ~/.claude.json 或项目 .mcp.json，对应的 JSON 形如：`,
    `  {"mcpServers":{"pivot":{"type":"http","url":"${MCP_URL}","headers":{"Authorization":"Bearer ${token}"}}}}`,
    `改完后告诉我完成了。`,
  ].join("\n");
}


/**
 * Cursor: deep link that opens Cursor and pre-fills the MCP config.
 * Cursor's mcp.json schema does NOT use a `type` field; transport is auto-detected.
 */
export function cursorDeepLink(token: string): string {
  const config = {
    name: "pivot",
    url: MCP_URL,
    headers: { Authorization: `Bearer ${token}` },
  };
  return `cursor://anysphere.cursor-deeplink/mcp/install?config=${encodeURIComponent(
    JSON.stringify(config),
  )}`;
}


/**
 * Codex: CLI command the user pastes into their terminal.
 * Codex detects Streamable HTTP from the presence of `url`.
 * Bearer token is passed via env var so it doesn't hit shell history.
 */
export function codexCliCommand(token: string): string {
  return [
    `# 1) 先设置 token 到环境变量（避免进 shell 历史）:`,
    `export PIVOT_TOKEN="${token}"`,
    `# 2) 添加 MCP 服务器:`,
    `codex mcp add pivot --url ${MCP_URL} --bearer-token-env-var PIVOT_TOKEN`,
  ].join("\n");
}


/**
 * Claude Desktop: NOT a JSON config paste. Users must add via the UI.
 * We give them copy-pasteable URL + Token, and instructions on where to paste.
 */
export function claudeDesktopConnectionInfo(token: string): string {
  return [`URL: ${MCP_URL}`, `Authorization: Bearer ${token}`].join("\n");
}


export const CLAUDE_DESKTOP_UI_HINT =
  '打开 Claude Desktop → Settings → Connectors → "Add custom connector"，' +
  "把上面的 URL 和 Authorization header 粘进去，保存即可。";
