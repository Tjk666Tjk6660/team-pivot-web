import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { toast, Toaster } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  CLAUDE_DESKTOP_UI_HINT,
  claudeCodePrompt,
  claudeDesktopConnectionInfo,
  codexCliCommand,
  cursorDeepLink,
} from "./settings/clientConfigs";
import { createApiToken, fetchApiTokens, type ApiTokenSummary } from "@/api";

const CLIENT_NAMES = [
  "Claude Code",
  "Cursor",
  "Codex",
  "Claude Desktop",
] as const;

export function SettingsExternalAI() {
  const [token, setToken] = useState<string | null>(null);
  const [connected, setConnected] = useState<ApiTokenSummary[]>([]);

  useEffect(() => {
    fetchApiTokens()
      .then((items) => {
        const clientTokens = items.filter((t) =>
          (CLIENT_NAMES as readonly string[]).includes(t.name),
        );
        setConnected(clientTokens);
      })
      .catch((e) =>
        toast.error(
          "加载已接入客户端失败：" +
            (e instanceof Error ? e.message : String(e)),
        ),
      );
  }, []);

  const ensureToken = async (clientName: string): Promise<string> => {
    if (token) return token;
    const r = await createApiToken(clientName, 90);
    setToken(r.token);
    return r.token;
  };

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast.success("已复制");
    } catch {
      toast.error("复制失败");
    }
  };

  return (
    <div className="min-h-screen bg-background">
      <Toaster position="top-center" richColors />
      <header className="border-b px-6 py-3">
        <div className="mx-auto flex max-w-3xl items-center gap-3">
          <Button asChild variant="ghost" size="sm">
            <Link to="/settings">
              <ArrowLeft className="h-4 w-4" /> 返回设置
            </Link>
          </Button>
          <h1 className="text-lg font-semibold">外部 AI 接入</h1>
        </div>
      </header>

      <main className="mx-auto max-w-3xl space-y-6 px-6 py-8">
        <div>
          <p className="text-sm leading-6 text-muted-foreground">
            选择你的 AI 客户端，按提示完成连接。连接上之后，在 matter /
            文件页点「复制给 AI」就能让 AI 读写 Pivot 内容。
          </p>
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Card className="space-y-2 p-4">
            <h3 className="font-medium">Claude Code</h3>
            <p className="text-sm text-muted-foreground">
              跨平台，让 Claude 自己改配置
            </p>
            <Button
              onClick={async () =>
                copy(claudeCodePrompt(await ensureToken("Claude Code")))
              }
            >
              复制 Prompt
            </Button>
          </Card>

          <Card className="space-y-2 p-4">
            <h3 className="font-medium">Cursor</h3>
            <p className="text-sm text-muted-foreground">
              浏览器一键唤起 Cursor
            </p>
            <Button
              onClick={async () => {
                const link = cursorDeepLink(await ensureToken("Cursor"));
                window.location.href = link;
              }}
            >
              一键安装
            </Button>
          </Card>

          <Card className="space-y-2 p-4">
            <h3 className="font-medium">Codex</h3>
            <p className="text-sm text-muted-foreground">
              粘到 Codex 对话里，AI 会帮你注册 MCP 并询问是否永久生效
            </p>
            <Button
              onClick={async () =>
                copy(codexCliCommand(await ensureToken("Codex")))
              }
            >
              复制 Codex 提示词
            </Button>
          </Card>

          <Card className="space-y-2 p-4">
            <h3 className="font-medium">Claude Desktop</h3>
            <p className="text-sm text-muted-foreground">
              {CLAUDE_DESKTOP_UI_HINT}
            </p>
            <Button
              onClick={async () =>
                copy(
                  claudeDesktopConnectionInfo(
                    await ensureToken("Claude Desktop"),
                  ),
                )
              }
            >
              复制 URL + Token
            </Button>
          </Card>
        </div>

        <div>
          <h3 className="mb-2 font-medium">已接入客户端</h3>
          {connected.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              暂无。完成上面任一客户端的接入后，这里会显示。
            </p>
          ) : (
            <ul className="space-y-1 text-sm">
              {connected.map((t) => (
                <li key={t.id}>
                  已接入 {t.name} · 最后使用：
                  {t.last_used_at
                    ? new Date(t.last_used_at * 1000).toLocaleString()
                    : "尚未使用"}
                </li>
              ))}
            </ul>
          )}
        </div>

        <details className="mt-4">
          <summary className="cursor-pointer text-sm text-muted-foreground">
            高级设置（访问令牌、撤销连接、手工配置）
          </summary>
          <div className="mt-3 space-y-2 text-sm">
            {token && (
              <div>
                当前 token（仅本次显示一次）：
                <code className="ml-1 break-all font-mono text-xs">
                  {token}
                </code>
              </div>
            )}
            <p>
              如果要撤销某个客户端的连接，去
              <Link to="/settings" className="text-primary underline">
                设置 → API Tokens
              </Link>
              删除对应 token。
            </p>
          </div>
        </details>

        <McpToolsPanel />
      </main>
    </div>
  );
}

function McpToolsPanel() {
  return (
    <Card className="rounded-[var(--r-md)] border-[var(--line)] bg-[var(--surface)] p-5 shadow-none">
      <div className="mb-3">
        <h2 className="text-base font-semibold text-[var(--text)]">
          Pivot MCP 能做什么
        </h2>
        <p className="mt-1 text-sm leading-6 text-[var(--text-mute)]">
          MCP 是外部 AI 客户端访问 Pivot 的安全通道。接入后，你复制给 AI
          的 matter / 文件链接不只是文本引用，AI 可以通过工具读取对应内容并协助写回。
        </p>
      </div>
      <div className="space-y-2">
        <McpToolRow
          name="resolve_context"
          title="解析复制链接"
          body="AI 收到「复制给 AI」的 matter / 文件 URL 后，用这个工具确认链接对应的 matter、文件和当前状态，并把可读摘要展示给你核对。"
        />
        <McpToolRow
          name="list_matters"
          title="查找可见 matters"
          body="按状态、负责人或关键词列出当前用户能访问的 matters，适合让 AI 先帮你找相关讨论。"
        />
        <McpToolRow
          name="get_matter"
          title="读取时间线目录"
          body="获取 matter 标题、状态、可触发的状态迁移，以及时间线上的文件元数据；不拉正文，方便 AI 先判断该读哪些文件。"
        />
        <McpToolRow
          name="read_files"
          title="读取文件正文"
          body="按文件路径读取完整正文和作者、类型等信息。单次最多 5 篇、总量有上限，避免 AI 一次拉太多上下文。"
        />
        <McpToolRow
          name="create_file"
          title="写入新文件"
          body="在你的明确确认后，AI 可以创建 think / act / verify / result / insight 文件；如果涉及状态变更，也必须先把可选迁移展示给你选择。"
        />
      </div>
      <p className="mt-3 rounded-[var(--r-sm)] bg-[var(--accent-bg)] px-3 py-2 text-sm leading-6 text-[var(--accent)]">
        推荐流程：先在本页完成客户端接入，再回到 matter 或文件页点击「复制给
        AI」，把链接粘给 AI，并要求它通过 Pivot MCP 读取上下文。
      </p>
    </Card>
  );
}

function McpToolRow({
  name,
  title,
  body,
}: {
  name: string;
  title: string;
  body: string;
}) {
  return (
    <div className="rounded-[var(--r-sm)] border border-[var(--line)] bg-[var(--surface-alt)] p-3">
      <div className="flex flex-wrap items-center gap-2">
        <code className="rounded bg-[var(--surface)] px-1.5 py-0.5 font-mono text-[11px] text-[var(--accent)] ring-1 ring-[var(--accent-soft)]">
          {name}
        </code>
        <span className="text-sm font-semibold text-[var(--text)]">
          {title}
        </span>
      </div>
      <p className="mt-1.5 text-sm leading-6 text-[var(--text-soft)]">
        {body}
      </p>
    </div>
  );
}
