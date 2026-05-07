import { useEffect, useRef, useState } from "react";
import { MessageSquareText } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

import { appendMatterAnnotation } from "@/api";

const BODY_MAX = 300;

/** Standalone evaluation popover (Phase 6).
 *
 * Visually paired with ``MentionPopover``: same anchored panel layout
 * (top-full, ~22rem wide, click-outside dismiss), same uppercase section
 * label, same Cancel / Submit footer. Differences:
 *  - no @-target picker (annotations have no explicit recipients;
 *    stakeholders are derived server-side)
 *  - body uses Textarea (rows=6) rather than single-line Input —
 *    evaluations tend to be multi-sentence
 *  - submit button reads "提交评价" */
export function AnnotationPopover({
  matterId,
  targetFile,
  align = "right",
  onSubmitted,
}: {
  matterId: string;
  targetFile: string;
  align?: "left" | "right";
  onSubmitted?: () => void | Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [body, setBody] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (
        popoverRef.current &&
        !popoverRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const reset = () => {
    setBody("");
    setSubmitting(false);
  };

  const submit = async () => {
    const trimmed = body.trim();
    if (trimmed.length === 0) {
      toast.error("评价不能为空");
      return;
    }
    if (trimmed.length > BODY_MAX) {
      toast.error(`评价超过 ${BODY_MAX} 字`);
      return;
    }
    setSubmitting(true);
    try {
      await appendMatterAnnotation(matterId, {
        target_file: targetFile,
        type: "evaluation",
        body: trimmed,
      });
      toast.success("已发送");
      reset();
      setOpen(false);
      await onSubmitted?.();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
      setSubmitting(false);
    }
  };

  return (
    <div className="relative" ref={popoverRef}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        title="对该文件写一条评价（不可编辑/删除，三个 stakeholder 会收到飞书通知）"
        className="inline-flex items-center gap-1 rounded-[var(--r-sm)] border border-[var(--line)] bg-[var(--surface)] px-2 py-1 text-[11px] font-semibold text-[var(--text-soft)] hover:bg-[var(--surface-alt)] hover:text-[var(--text)]"
      >
        <MessageSquareText className="h-3 w-3" />
        评价
      </button>
      {open && (
        <div
          className={cn(
            "absolute top-full z-50 mt-2 max-h-[calc(100vh-8rem)] w-[calc(100vw-2rem)] max-w-[22rem] overflow-y-auto rounded-[var(--r-md)] border border-[var(--line)] bg-[var(--surface)] p-3 shadow-[var(--shadow-lg)] sm:max-h-none sm:w-[22rem] sm:overflow-visible",
            align === "right" ? "right-0" : "left-0",
          )}
        >
          <div className="rounded-md border bg-muted/30 p-3 space-y-2">
            <Label htmlFor="annotation-body" className="text-xs font-semibold">
              你的评价
            </Label>
            <Textarea
              id="annotation-body"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="比如：结构清楚，但缺少边界条件验证…"
              maxLength={BODY_MAX}
              rows={6}
              className="resize-none text-sm"
              disabled={submitting}
            />
            <div className="text-right text-[10px] text-[var(--text-fade)]">
              {body.length} / {BODY_MAX}
            </div>
          </div>
          <div className="mt-3 flex justify-end gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => {
                setOpen(false);
                reset();
              }}
              disabled={submitting}
            >
              取消
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={() => void submit()}
              disabled={submitting || body.trim().length === 0}
              className="bg-[var(--accent)] text-[var(--accent-ink)] hover:opacity-90"
            >
              {submitting ? "发送中…" : "发送"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
