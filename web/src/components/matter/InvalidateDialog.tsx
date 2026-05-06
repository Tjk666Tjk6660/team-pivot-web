import { useState } from "react";
import { toast } from "sonner";
import type { InvalidationReason } from "@/api";
import { postMatterEvent } from "@/api";
import { Button } from "@/components/ui/button";

/** Modal for invalidating or restoring a file.
 *
 * Two modes via `mode` prop:
 *   - "invalidate": pick reason ∈ {misposted, inaccurate} + optional summary
 *   - "restore": optional summary; reason is forced to "restored"
 *
 * Server enforces author-only at the API layer; this modal assumes the caller
 * already gated visibility on `current_user.pinyin === item.creator`.
 *
 * On success, calls onDone() and the parent is expected to refetch matter
 * detail (typically through the SSE matter.updated handler).
 */
export function InvalidateDialog({
  matterId,
  targetFile,
  mode,
  onClose,
  onDone,
}: {
  matterId: string;
  targetFile: string;
  mode: "invalidate" | "restore";
  onClose: () => void;
  onDone: () => void;
}) {
  const [reason, setReason] = useState<"misposted" | "inaccurate">("misposted");
  const [summary, setSummary] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      const apiReason: InvalidationReason =
        mode === "restore" ? "restored" : reason;
      await postMatterEvent(matterId, {
        target_file: targetFile,
        reason: apiReason,
        summary: summary.trim() || null,
      });
      toast.success(mode === "restore" ? "已恢复" : "已失效");
      onDone();
      onClose();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-full max-w-md rounded-[var(--r-md)] border border-[var(--line)] bg-[var(--surface)] p-5 shadow-lg">
        <h2 className="mb-3 text-base font-semibold">
          {mode === "restore" ? "恢复此文档" : "失效此文档"}
        </h2>

        {mode === "invalidate" && (
          <div className="mb-3 flex flex-col gap-2 text-sm">
            <label className="text-[var(--text-soft)]">理由</label>
            <div className="flex flex-col gap-1.5">
              <label className="inline-flex cursor-pointer items-center gap-2">
                <input
                  type="radio"
                  name="invalidate-reason"
                  value="misposted"
                  checked={reason === "misposted"}
                  onChange={() => setReason("misposted")}
                />
                <span>误发</span>
                <span className="text-xs text-[var(--text-mute)]">
                  发错地方 / 文件本身不该出现
                </span>
              </label>
              <label className="inline-flex cursor-pointer items-center gap-2">
                <input
                  type="radio"
                  name="invalidate-reason"
                  value="inaccurate"
                  checked={reason === "inaccurate"}
                  onChange={() => setReason("inaccurate")}
                />
                <span>信息有误</span>
                <span className="text-xs text-[var(--text-mute)]">
                  内容判断已被推翻 / 数据失真
                </span>
              </label>
            </div>
          </div>
        )}

        <div className="mb-4 flex flex-col gap-1.5 text-sm">
          <label htmlFor="invalidate-summary" className="text-[var(--text-soft)]">
            说明（可选）
          </label>
          <textarea
            id="invalidate-summary"
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            maxLength={500}
            rows={3}
            placeholder={
              mode === "restore"
                ? "可附一句恢复理由"
                : "可附一句失效说明"
            }
            className="rounded-md border border-[var(--line-strong,var(--line))] bg-white p-2 text-sm"
          />
        </div>

        <div className="flex justify-end gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={onClose}
            disabled={submitting}
          >
            取消
          </Button>
          <Button
            type="button"
            onClick={handleSubmit}
            disabled={submitting}
            className={
              mode === "restore"
                ? "bg-[var(--accent)] text-white hover:bg-[var(--accent-strong)]"
                : "bg-[var(--warn-600,#d97706)] text-white hover:bg-[var(--warn-700,#b45309)]"
            }
          >
            {submitting
              ? "提交中…"
              : mode === "restore"
              ? "确认恢复"
              : "确认失效"}
          </Button>
        </div>
      </div>
    </div>
  );
}
