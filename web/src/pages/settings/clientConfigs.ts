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
    `改完后告诉我完成了，并提醒我：要让新配置生效需要重启 Claude Code；如果当前会话仍在运行，可输入 /mcp 查看 pivot 是否已连接。`,
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
 * Codex: a natural-language prompt the user pastes into the Codex AI chat
 * (NOT into a raw terminal). The AI then runs `codex mcp add` for them and
 * orchestrates the optional shell-profile persistence step interactively —
 * detecting OS/shell, asking for confirmation, and surfacing the safety
 * trade-off before writing the token to disk.
 *
 * Mirrors the `claudeCodePrompt` pattern: keep MCP onboarding AI-orchestrated
 * across all clients so users never need raw shell knowledge.
 */
export function codexCliCommand(token: string): string {
  return [
    `请帮我把下面的 MCP 服务器加到 Codex 配置里。`,
    ``,
    `服务器名: pivot`,
    `URL: ${MCP_URL}`,
    `Bearer token: ${token}`,
    ``,
    `请按以下步骤完成：`,
    ``,
    `1) 临时设环境变量并注册 MCP（token 通过 env var 传，避免进 shell 历史）：`,
    `   export PIVOT_TOKEN="${token}"`,
    `   codex mcp add pivot --url ${MCP_URL} --bearer-token-env-var PIVOT_TOKEN`,
    ``,
    `2) 注册成功后问我："要不要让 PIVOT_TOKEN 永久生效（下次开终端也能用）？"`,
    ``,
    `3) 如果我说「是」：`,
    `   - 先检测我的 shell 和操作系统（zsh / bash / PowerShell 等），告诉我检测结果让我确认`,
    `   - 提醒我："这会把 token 明文写进用户级位置，仅推荐个人开发机使用"`,
    `   - 我确认后，用对应命令写入配置：`,
    `     * bash       → echo 'export PIVOT_TOKEN="${token}"' >> ~/.bashrc`,
    `     * zsh        → echo 'export PIVOT_TOKEN="${token}"' >> ~/.zshrc`,
    `     * PowerShell → [Environment]::SetEnvironmentVariable("PIVOT_TOKEN", "${token}", "User")`,
    `   - 告诉我新开终端后才会生效`,
    ``,
    `4) 如果我说「否」，告诉我每次启动 Codex 前需要先 export PIVOT_TOKEN。`,
    ``,
    `全程用中文跟我交流。`,
  ].join("\n");
}


/**
 * Claude Desktop: paste the JSON snippet into `claude_desktop_config.json`.
 *
 * The in-app "Add custom connector" UI runs an OAuth client_id/secret flow
 * that Pivot's PAT-only MCP backend cannot satisfy, so users must edit the
 * config file directly. Bridges HTTP→stdio via `mcp-remote` (npx) so older
 * Claude Desktop builds (stdio-only) work alongside newer ones.
 */
export function claudeDesktopJsonSnippet(token: string): string {
  return JSON.stringify(
    {
      mcpServers: {
        pivot: {
          command: "npx",
          args: [
            "-y",
            "mcp-remote",
            MCP_URL,
            "--header",
            `Authorization: Bearer ${token}`,
          ],
        },
      },
    },
    null,
    2,
  );
}


export const CLAUDE_DESKTOP_UI_HINT =
  "点下面按钮复制 JSON，然后：" +
  "① 文件管理器地址栏粘 %APPDATA%\\Claude\\claude_desktop_config.json " +
  "（macOS：~/Library/Application Support/Claude/claude_desktop_config.json）" +
  "回车，没这个文件就新建。" +
  "② 把复制的内容合并到文件里——已有 mcpServers 字段就把 pivot 那段并进去，没有就整段写入。" +
  "③ 完全退出 Claude Desktop（任务栏托盘也要退出）后重开。" +
  "需要本机装 Node.js。";
