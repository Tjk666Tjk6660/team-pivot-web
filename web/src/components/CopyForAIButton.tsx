import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Copy, Check } from "lucide-react";

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
  const url = filePath
    ? `${window.location.origin}/m/${encodeURIComponent(matterId)}/f/${encodeURIComponent(filePath)}`
    : `${window.location.origin}/m/${encodeURIComponent(matterId)}`;

  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      toast.success("已复制，粘到 Claude Code 或其他 AI 助手即可");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("复制失败，请手动复制：" + url);
    }
  };

  return (
    <Button size={size} variant={variant} onClick={onCopy} className="gap-1.5">
      {copied ? (
        <Check className="h-3.5 w-3.5" />
      ) : (
        <Copy className="h-3.5 w-3.5" />
      )}
      {label ?? "复制给 AI"}
    </Button>
  );
}
