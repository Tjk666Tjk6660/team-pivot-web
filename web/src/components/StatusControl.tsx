import { useEffect, useRef, useState, type ReactNode } from "react";
import { Archive, Check, ChevronDown, Pause, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { STATUS_LABELS, StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";

type Tone = "concluded" | "archived" | "paused" | "discussing" | "project";

type Transition = {
  to: string;
  label: string;
  needsReason: boolean;
  desc: string;
  tone: Tone;
  icon: ReactNode;
};

const TRANSITIONS: Record<string, Transition[]> = {
  open: [
    {
      to: "concluded", label: "标记为已结论", needsReason: false,
      desc: "由你或 AI 撰写最终结论", tone: "concluded",
      icon: <Check className="h-3.5 w-3.5" />,
    },
    {
      to: "pending", label: "暂时搁置", needsReason: false,
      desc: "不需要现在讨论，可以随时激活", tone: "paused",
      icon: <Pause className="h-3.5 w-3.5" />,
    },
    {
      to: "closed", label: "关闭讨论", needsReason: false,
      desc: "保留完整记录，不出现在今日", tone: "archived",
      icon: <Archive className="h-3.5 w-3.5" />,
    },
  ],
  concluded: [
    {
      to: "open", label: "重新打开", needsReason: true,
      desc: "需要补充原因（≥ 3 字），讨论会回到「等我回应」", tone: "discussing",
      icon: <RotateCcw className="h-3.5 w-3.5" />,
    },
  ],
  closed: [
    {
      to: "open", label: "重新打开", needsReason: true,
      desc: "需要补充原因（≥ 3 字），讨论会回到「等我回应」", tone: "discussing",
      icon: <RotateCcw className="h-3.5 w-3.5" />,
    },
  ],
  pending: [
    {
      to: "open", label: "重新激活", needsReason: false,
      desc: "回到讨论中，等你和大家继续推进", tone: "discussing",
      icon: <RotateCcw className="h-3.5 w-3.5" />,
    },
  ],
  produced: [],
};

const REASON_MIN = 3;

function statusKeyFromValue(value: string | null): string {
  if (!value) return "open";
  if (Object.prototype.hasOwnProperty.call(TRANSITIONS, value)) return value;
  return "open";
}

function toneFor(status: string | null): Tone {
  if (!status) return "discussing";
  return STATUS_LABELS[status]?.tone ?? "discussing";
}

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

  const current = statusKeyFromValue(status);
  const options = TRANSITIONS[current] ?? [];
  const currentLabel = STATUS_LABELS[current]?.text ?? "讨论中";
  const currentTone = toneFor(current);

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

  const interactive = options.length > 0;

  return (
    <div className="relative inline-block" ref={menuRef}>
      {interactive ? (
        <button
          type="button"
          onClick={() => setMenuOpen((o) => !o)}
          className="inline-flex items-center gap-1.5 rounded-[var(--r-sm)] py-[5px] pl-3 pr-2.5 text-[11.5px] font-bold tracking-[0.04em] font-meta whitespace-nowrap"
          style={{
            background: `var(--status-${currentTone}-bg)`,
            color: `var(--status-${currentTone}-fg)`,
            border: `1px solid color-mix(in srgb, var(--status-${currentTone}-fg) 35%, var(--line))`,
          }}
          title="更改状态"
        >
          <span
            aria-hidden
            className="h-1.5 w-1.5 shrink-0 rounded-full"
            style={{ background: "currentColor" }}
          />
          {currentLabel}
          <ChevronDown
            className={`ml-0.5 h-3 w-3 shrink-0 transition-transform ${menuOpen ? "rotate-180" : ""}`}
          />
        </button>
      ) : (
        <StatusBadge status={status} />
      )}

      {menuOpen && interactive && (
        <div
          className="absolute left-0 top-full z-[60] mt-1.5 w-[min(20rem,calc(100vw-2rem))] overflow-hidden rounded-[var(--r-md)] p-1.5 sm:left-auto sm:right-0 sm:w-[320px]"
          style={{
            background: "var(--surface)",
            border: "1px solid var(--line-strong)",
            boxShadow: "var(--shadow-lg)",
          }}
        >
          <div
            className="px-2.5 pb-1.5 pt-1 text-[10.5px] font-bold uppercase tracking-[0.18em] font-meta"
            style={{ color: "var(--text-mute)" }}
          >
            当前：{currentLabel} → 可转到
          </div>
          {options.map((o) => (
            <button
              key={o.to}
              type="button"
              onClick={() => (o.needsReason ? setPending(o) : applyDirect(o))}
              disabled={submitting}
              className="flex w-full items-start gap-2.5 rounded-[var(--r-sm)] px-2 py-2 text-left transition-colors hover:bg-[var(--accent-bg)] disabled:opacity-50"
            >
              <span
                aria-hidden
                className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-[7px]"
                style={{
                  background: `var(--status-${o.tone}-bg)`,
                  color: `var(--status-${o.tone}-fg)`,
                }}
              >
                {o.icon}
              </span>
              <span className="flex min-w-0 flex-1 flex-col">
                <span
                  className="flex items-center gap-1.5 text-[13px] font-semibold"
                  style={{ color: "var(--text)" }}
                >
                  {o.label}
                  {o.needsReason && (
                    <span
                      className="rounded-[3px] px-1.5 py-[1px] text-[9.5px] font-bold tracking-[0.06em] font-meta"
                      style={{
                        background: "var(--accent-bg)",
                        color: "var(--accent)",
                      }}
                    >
                      需原因
                    </span>
                  )}
                </span>
                <span
                  className="mt-0.5 text-[11.5px] leading-[1.5]"
                  style={{
                    fontFamily: "var(--font-serif)",
                    color: "var(--text-mute)",
                  }}
                >
                  {o.desc}
                </span>
              </span>
            </button>
          ))}
        </div>
      )}

      <Dialog open={!!pending} onOpenChange={(o) => !o && setPending(null)}>
        <DialogContent
          style={{
            background: "var(--surface)",
            border: "1px solid var(--line-strong)",
            color: "var(--text)",
          }}
        >
          <DialogHeader>
            <DialogTitle
              style={{
                fontFamily: "var(--font-serif)",
                letterSpacing: "var(--letter-tight)",
                color: "var(--text)",
              }}
            >
              {pending?.label}
            </DialogTitle>
            <DialogDescription
              style={{
                fontFamily: "var(--font-serif)",
                color: "var(--text-soft)",
              }}
            >
              请说明原因（至少 {REASON_MIN} 字）
            </DialogDescription>
          </DialogHeader>
          <Textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={4}
            autoFocus
            className="rounded-[var(--r-sm)] font-mono text-[13px]"
            style={{
              background: "var(--surface-alt)",
              border: "1.5px solid var(--accent)",
              color: "var(--text)",
            }}
          />
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setPending(null)}
              disabled={submitting}
              className="rounded-[var(--r-sm)]"
              style={{
                background: "transparent",
                border: "1px solid var(--line-strong)",
                color: "var(--text-soft)",
              }}
            >
              取消
            </Button>
            <Button
              onClick={applyWithReason}
              disabled={submitting || reason.trim().length < REASON_MIN}
              className="rounded-[var(--r-sm)] font-semibold shadow-none"
              style={{
                background: "var(--accent)",
                color: "var(--accent-ink)",
                border: "1px solid var(--accent)",
              }}
            >
              {submitting ? "提交中…" : "确认"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

