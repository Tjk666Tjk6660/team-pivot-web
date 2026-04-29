import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Check, Copy, PlugZap } from "lucide-react";
import { fetchMe } from "@/api";
import {
  copyForAIGuideStorageKey,
  shouldShowCopyForAIGuide,
} from "@/lib/copyForAIGuide";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

let currentUserOpenIdPromise: Promise<string | null> | null = null;

function loadCurrentUserOpenId(): Promise<string | null> {
  if (!currentUserOpenIdPromise) {
    currentUserOpenIdPromise = fetchMe()
      .then((me) => me?.open_id ?? null)
      .catch(() => null);
  }
  return currentUserOpenIdPromise;
}

/**
 * A button that copies a Pivot context URL to the clipboard so the user
 * can paste it to an external AI (Claude Code / Cursor / Codex / etc.).
 *
 * - matter-level: omit filePath → copies `<origin>/m/<matterId>`
 * - file-level: pass filePath → copies `<origin>/m/<matterId>/f/<filePath>`
 */
export function CopyForAIButton({
  matterId,
  filePath,
  size = "sm",
  variant = "outline",
  label,
}: {
  matterId: string;
  filePath?: string;
  size?: "sm" | "default";
  variant?: "outline" | "ghost" | "secondary";
  label?: string;
}) {
  const [copied, setCopied] = useState(false);
  const [guideOpen, setGuideOpen] = useState(false);
  const [pendingStorageKey, setPendingStorageKey] = useState<string | null>(
    null,
  );
  const url = filePath
    ? `${window.location.origin}/m/${encodeURIComponent(matterId)}/f/${encodeURIComponent(filePath)}`
    : `${window.location.origin}/m/${encodeURIComponent(matterId)}`;

  const copyUrl = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      toast.success("已复制，粘到已接入 MCP 的 AI 助手即可");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("复制失败，请手动复制：" + url);
    }
  };

  const onCopy = async () => {
    const openId = await loadCurrentUserOpenId();
    const storageKey = copyForAIGuideStorageKey(openId);
    if (shouldShowCopyForAIGuide(window.localStorage.getItem(storageKey))) {
      setPendingStorageKey(storageKey);
      setGuideOpen(true);
      return;
    }
    await copyUrl();
  };

  const confirmGuideAndCopy = async () => {
    if (pendingStorageKey) {
      window.localStorage.setItem(pendingStorageKey, "1");
    }
    setGuideOpen(false);
    await copyUrl();
  };

  return (
    <>
      <Button size={size} variant={variant} onClick={onCopy} className="gap-1.5">
        {copied ? (
          <Check className="h-3.5 w-3.5" />
        ) : (
          <Copy className="h-3.5 w-3.5" />
        )}
        {label ?? "复制给 AI"}
      </Button>

      <Dialog open={guideOpen} onOpenChange={setGuideOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-[var(--r-md)] bg-[var(--accent-bg)] text-[var(--accent)]">
              <PlugZap className="h-5 w-5" />
            </div>
            <DialogTitle>先把 AI 接入 Pivot MCP</DialogTitle>
            <DialogDescription>
              「复制给 AI」会复制当前 matter / 文件链接。AI 客户端接入 MCP
              后，才能通过这个链接读取和写入 Pivot 内容。
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4">
            <div className="rounded-[var(--r-md)] border border-[var(--line)] bg-[var(--surface-alt)] p-4">
              <div className="mb-2 text-sm font-semibold text-[var(--text)]">
                MCP 可以让 AI 做什么
              </div>
              <ul className="space-y-1.5 text-sm leading-6 text-[var(--text-soft)]">
                <li>读取当前 matter 的时间线、文件正文和上下文。</li>
                <li>按链接定位到某一篇文件，继续追问、总结或分析。</li>
                <li>在你授权的 AI 客户端里辅助创建新文件或补充内容。</li>
                <li>让外部 AI 使用同一套 Pivot 数据，而不是只看一段复制文本。</li>
              </ul>
            </div>
            <div className="rounded-[var(--r-md)] border border-[var(--line)] bg-[var(--surface-alt)] p-4">
              <div className="mb-2 text-sm font-semibold text-[var(--text)]">
                第一次使用怎么做
              </div>
              <ol className="list-decimal space-y-1.5 pl-4 text-sm leading-6 text-[var(--text-soft)]">
                <li>到「外部 AI 接入」按你的客户端完成 MCP 连接。</li>
                <li>回到这里复制链接，粘到 Claude Code、Codex 或 Cursor。</li>
                <li>告诉 AI：请通过 MCP 读取这个链接对应的内容。</li>
              </ol>
            </div>
          </div>
          <DialogFooter>
            <Button asChild variant="outline">
              <Link to="/settings/external-ai">去接入 MCP</Link>
            </Button>
            <Button
              className="bg-[var(--accent)] text-[var(--accent-ink)] hover:opacity-90"
              onClick={() => void confirmGuideAndCopy()}
            >
              我知道了，复制链接
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
