import { useEffect, useState } from "react";
import { toast } from "sonner";
import { ArrowRight, Loader2 } from "lucide-react";
import {
  transferMatterOwner,
  type MatterMeta,
  type StatusChange,
  type TransferMatterOwnerResponse,
} from "@/api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { OwnerPicker } from "./OwnerPicker";
import { OwnerChip } from "./OwnerChip";

export function TransferOwnerDialog({
  open,
  matter,
  sessionOpenId,
  sessionName,
  onClose,
  onTransferred,
}: {
  open: boolean;
  matter: MatterMeta;
  sessionOpenId: string;
  sessionName: string;
  onClose: () => void;
  onTransferred: (result: TransferMatterOwnerResponse) => void;
}) {
  const [toOwner, setToOwner] = useState("");
  const [toOwnerName, setToOwnerName] = useState("");
  const [reason, setReason] = useState("");
  const [advance, setAdvance] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    setToOwner("");
    setToOwnerName("");
    setReason("");
    setAdvance(false);
  }, [open, matter.id]);

  const canAdvance = matter.current_status === "planning";
  const trimmedReason = reason.trim();
  const disabled = submitting || !toOwner || !trimmedReason;

  const submit = async () => {
    if (disabled) return;
    setSubmitting(true);
    try {
      const status_change: StatusChange | null =
        advance && canAdvance
          ? { from: "planning", to: "executing" }
          : null;
      const result = await transferMatterOwner(matter.id, {
        to_owner: toOwner,
        reason: trimmedReason,
        status_change,
      });
      onTransferred(result);
      toast.success("已转交负责人");
      onClose();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>转交负责人</DialogTitle>
          <DialogDescription>
            记录这件事当前由谁继续推进，变更会写入时间轴。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid gap-2">
            <div className="text-xs font-semibold text-[var(--text-mute)]">
              当前负责人
            </div>
            <OwnerChip
              name={matter.owner_display}
              avatarUrl={matter.owner_avatar_url}
              unassigned={!matter.owner}
              size="md"
            />
          </div>

          <div className="grid gap-2">
            <div className="text-xs font-semibold text-[var(--text-mute)]">
              新负责人
            </div>
            <OwnerPicker
              value={toOwner}
              onChange={(openId, displayName) => {
                setToOwner(openId);
                setToOwnerName(displayName);
              }}
              sessionOpenId={sessionOpenId}
              sessionName={sessionName}
              displayName={toOwnerName}
              placeholder="选择新的负责人"
              dropdownMode="inline"
            />
          </div>

          <div className="grid gap-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-[var(--text-mute)]">
                变更原因
              </span>
              <span className="text-[11px] text-[var(--text-fade)]">
                {trimmedReason.length}/200
              </span>
            </div>
            <Textarea
              value={reason}
              maxLength={200}
              onChange={(e) => setReason(e.target.value)}
              placeholder="为什么转交给对方继续推进？"
            />
          </div>

          {canAdvance && (
            <label className="flex cursor-pointer items-center gap-2 rounded-[var(--r-sm)] border border-[var(--line)] bg-[var(--surface-alt)] px-3 py-2 text-sm text-[var(--text)]">
              <input
                type="checkbox"
                checked={advance}
                onChange={(e) => setAdvance(e.target.checked)}
                className="h-4 w-4 accent-[var(--accent)]"
              />
              <span className="inline-flex items-center gap-1.5">
                同时推进至 executing
                <ArrowRight className="h-3.5 w-3.5 text-[var(--text-mute)]" />
              </span>
            </label>
          )}
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button type="button" disabled={disabled} onClick={submit}>
            {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
            确认转交
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
