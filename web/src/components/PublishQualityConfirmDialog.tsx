import { Bot } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

export type PublishQualityConfirmDialogProps = {
  open: boolean;
  blockedByAIBusy: boolean;
  busyTitle?: string;
  onForcePublish: () => void;
  onSendToAI: () => void;
  onCancel: () => void;
};

export function PublishQualityConfirmDialog({
  open,
  blockedByAIBusy,
  busyTitle,
  onForcePublish,
  onSendToAI,
  onCancel,
}: PublishQualityConfirmDialogProps) {
  const sendButtonLabel = blockedByAIBusy ? "加入 AI 队列" : "进行 AI 讨论";
  const sendHint = blockedByAIBusy
    ? `内容已填入输入框，等当前对话${busyTitle ? `「${busyTitle}」` : ""}完成后再发送`
    : "把当前内容塞进 AI 助手输入框，继续讨论或让 AI 帮你改写";

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onCancel();
      }}
    >
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Bot className="h-5 w-5 text-[var(--accent)]" />
            内容质量提示
          </DialogTitle>
          <DialogDescription className="space-y-3 pt-2 text-sm leading-6 text-[var(--text-soft)]">
            <p>检测到这篇内容不是由当前 AI 助手和你讨论后输出的。</p>
            <p>
              请确认这篇文档能够代表你的真实想法，并且足够清晰可读、有思考沉淀、有结构化表达，以便持续提高团队讨论质量。
            </p>
            <p className="text-[var(--text-mute)]">
              对于低质量输入，后期我们会使用 AI 工具进行检测和评价。
            </p>
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="gap-2 pt-2">
          <Button
            type="button"
            variant="ghost"
            className="rounded-[var(--r-md)]"
            onClick={onCancel}
          >
            取消
          </Button>
          <div className="flex flex-col items-stretch gap-1.5 sm:flex-row sm:items-center sm:gap-2">
            <Button
              type="button"
              variant="outline"
              className="rounded-[var(--r-md)]"
              onClick={onSendToAI}
              title={sendHint}
            >
              {sendButtonLabel}
            </Button>
            <Button
              type="button"
              className="rounded-[var(--r-md)]"
              onClick={onForcePublish}
            >
              立即发布
            </Button>
          </div>
        </DialogFooter>
        {blockedByAIBusy && (
          <p className="text-xs leading-5 text-[var(--text-mute)]">
            {sendHint}
          </p>
        )}
      </DialogContent>
    </Dialog>
  );
}
