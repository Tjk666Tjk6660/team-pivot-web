import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";

type Transition = { to: string; label: string; needsReason: boolean };

const TRANSITIONS: Record<string, Transition[]> = {
  open: [
    { to: "concluded", label: "标记为已结论", needsReason: false },
    { to: "closed", label: "关闭讨论", needsReason: false },
    { to: "pending", label: "暂时搁置", needsReason: false },
  ],
  concluded: [{ to: "open", label: "重新打开", needsReason: true }],
  closed: [{ to: "open", label: "重新打开", needsReason: true }],
  pending: [{ to: "open", label: "重新激活", needsReason: false }],
  produced: [],
};

const REASON_MIN = 3;

export function StatusControl({
  status,
  onChange,
}: {
  status: string | null;
  onChange: (to: string, reason?: string) => Promise<void>;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [pending, setPending] = useState<Transition | null>(null);
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  const current = status ?? "open";
  const options = TRANSITIONS[current] ?? [];

  useEffect(() => {
    if (!menuOpen) return;
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setMenuOpen(false); };
    document.addEventListener("mousedown", handler);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", handler);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  const applyDirect = async (t: Transition) => {
    setSubmitting(true);
    try {
      await onChange(t.to);
      setMenuOpen(false);
      toast.success("状态已更新");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  const applyWithReason = async () => {
    if (!pending) return;
    if (reason.trim().length < REASON_MIN) {
      toast.error(`原因至少 ${REASON_MIN} 字`);
      return;
    }
    setSubmitting(true);
    try {
      await onChange(pending.to, reason.trim());
      setPending(null); setReason(""); setMenuOpen(false);
      toast.success("状态已更新");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="relative inline-block" ref={menuRef}>
      <button
        type="button"
        onClick={() => options.length > 0 && setMenuOpen((o) => !o)}
        disabled={options.length === 0}
        className={options.length > 0 ? "cursor-pointer" : "cursor-default"}
        title={options.length === 0 ? undefined : "更改状态"}
      >
        <StatusBadge status={status} />
      </button>
      {menuOpen && options.length > 0 && (
        <div className="absolute left-0 top-full z-30 mt-1 min-w-44 rounded-md border bg-white dark:bg-zinc-900 shadow-md">
          {options.map((t) => (
            <button
              key={t.to}
              type="button"
              onClick={() => (t.needsReason ? setPending(t) : applyDirect(t))}
              disabled={submitting}
              className="block w-full px-3 py-2 text-left text-sm hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50"
            >
              {t.label}
            </button>
          ))}
        </div>
      )}
      <Dialog open={!!pending} onOpenChange={(o) => !o && setPending(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{pending?.label}</DialogTitle>
            <DialogDescription>
              请说明原因（至少 {REASON_MIN} 字）
            </DialogDescription>
          </DialogHeader>
          <Textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={4}
            autoFocus
          />
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setPending(null)}
              disabled={submitting}
            >
              取消
            </Button>
            <Button
              onClick={applyWithReason}
              disabled={submitting || reason.trim().length < REASON_MIN}
            >
              {submitting ? "提交中…" : "确认"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
