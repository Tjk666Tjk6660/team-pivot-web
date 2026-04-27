import { useState } from "react";
import { toast } from "sonner";
import type { Outcome } from "@/api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

export function ResultConfirmDialog({
  open,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  onCancel: () => void;
  onConfirm: (body: {
    summary: string;
    body?: string;
    outcome: Outcome;
  }) => Promise<void>;
}) {
  const [phase, setPhase] = useState<"confirm" | "form">("confirm");
  const [outcome, setOutcome] = useState<Outcome>("finished");
  const [summary, setSummary] = useState("");
  const [body, setBody] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const reset = () => {
    setPhase("confirm");
    setOutcome("finished");
    setSummary("");
    setBody("");
    setSubmitting(false);
  };

  const handleCancel = () => {
    reset();
    onCancel();
  };

  const submit = async () => {
    if (!summary.trim()) {
      toast.error("summary 必填");
      return;
    }
    setSubmitting(true);
    try {
      await onConfirm({
        summary: summary.trim(),
        body: body.trim() || undefined,
        outcome,
      });
      reset();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && handleCancel()}>
      <DialogContent className="max-w-lg">
        {phase === "confirm" ? (
          <>
            <DialogHeader>
              <DialogTitle>⚠ 生成 Result 是事项正式收口</DialogTitle>
              <DialogDescription className="text-xs">
                发布 Result 后：
              </DialogDescription>
            </DialogHeader>
            <ul className="list-disc space-y-0.5 pl-5 text-xs text-[var(--text-soft)]">
              <li>
                matter 状态变更为 <span className="font-mono">finished</span> 或{" "}
                <span className="font-mono">cancelled</span>
              </li>
              <li>不再允许新增 act / verify / 执行性 think</li>
              <li>
                只剩 <span className="font-mono">insight</span> 可追加
              </li>
            </ul>
            <DialogFooter>
              <Button variant="outline" onClick={handleCancel}>
                取消
              </Button>
              <Button
                className="bg-[var(--violet-600)] text-white hover:opacity-90"
                onClick={() => setPhase("form")}
              >
                继续生成
              </Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <DialogHeader>
              <DialogTitle>生成 Result</DialogTitle>
              <DialogDescription className="text-xs">
                outcome 决定最终状态：<span className="font-mono">executing → {outcome}</span>
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-3 text-sm">
              <div>
                <div className="mb-1 text-xs font-medium text-[var(--text-soft)]">
                  outcome<span className="ml-0.5 text-[var(--danger-500)]">*</span>
                </div>
                <div className="flex gap-5">
                  <label className="flex items-center gap-1.5">
                    <input
                      type="radio"
                      checked={outcome === "finished"}
                      onChange={() => setOutcome("finished")}
                    />
                    完成（finished）
                  </label>
                  <label className="flex items-center gap-1.5">
                    <input
                      type="radio"
                      checked={outcome === "cancelled"}
                      onChange={() => setOutcome("cancelled")}
                    />
                    取消（cancelled）
                  </label>
                </div>
              </div>

              <div>
                <div className="mb-1 text-xs font-medium text-[var(--text-soft)]">
                  summary<span className="ml-0.5 text-[var(--danger-500)]">*</span>
                </div>
                <Input
                  value={summary}
                  onChange={(e) => setSummary(e.target.value)}
                  placeholder="写下事项的最终判断"
                />
              </div>

              <div>
                <div className="mb-1 text-xs font-medium text-[var(--text-soft)]">body</div>
                <Textarea
                  rows={4}
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  placeholder="可选 · Markdown 正文"
                />
              </div>

              <div
                className={cn(
                  "rounded-md px-3 py-2 text-xs ring-1",
                  outcome === "finished"
                    ? "bg-[var(--status-concluded-bg)] text-[var(--status-concluded-fg)] ring-[var(--line)]"
                    : "bg-[var(--status-archived-bg)] text-[var(--status-archived-fg)] ring-[var(--line)]",
                )}
              >
                发布后触发状态 <span className="font-mono">executing → {outcome}</span>
              </div>
            </div>

            <DialogFooter>
              <Button variant="outline" onClick={handleCancel} disabled={submitting}>
                取消
              </Button>
              <Button onClick={() => void submit()} disabled={submitting}>
                {submitting ? "发布中…" : "发布并结束 matter"}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
