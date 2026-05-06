import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";
import {
  transferMatterOwner,
  type MatterMeta,
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
  sessionPivotUserId,
  sessionName,
  onClose,
  onTransferred,
}: {
  open: boolean;
  matter: MatterMeta;
  sessionPivotUserId: string;
  sessionName: string;
  onClose: () => void;
  onTransferred: (result: TransferMatterOwnerResponse) => void;
}) {
  const [toOwner, setToOwner] = useState("");
  const [toOwnerName, setToOwnerName] = useState("");
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    setToOwner("");
    setToOwnerName("");
    setReason("");
  }, [open, matter.id]);

  const trimmedReason = reason.trim();
  const disabled = submitting || !toOwner || !trimmedReason;

  const submit = async () => {
    if (disabled) return;
    setSubmitting(true);
    try {
      const result = await transferMatterOwner(matter.id, {
        to_owner: toOwner,
        reason: trimmedReason,
      });
      onTransferred(result);
      toast.success("已更改负责人");
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
          <DialogTitle>更改负责人</DialogTitle>
          <DialogDescription>
            记录这件事当前由谁继续推进，变更会写入时间轴，并通过飞书 IM 私聊通知新负责人。
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
              onChange={(pivotUserId, displayName) => {
                setToOwner(pivotUserId);
                setToOwnerName(displayName);
              }}
              sessionPivotUserId={sessionPivotUserId}
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
              placeholder="为什么更改为对方继续推进？"
            />
          </div>

        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button type="button" disabled={disabled} onClick={submit}>
            {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
            确认更改
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
