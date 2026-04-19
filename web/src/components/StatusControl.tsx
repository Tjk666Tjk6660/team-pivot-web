import { useState } from "react";
import { StatusBadge } from "./StatusBadge";

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
  const [open, setOpen] = useState(false);
  const [pendingTo, setPendingTo] = useState<Transition | null>(null);
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const current = status ?? "open";
  const options = TRANSITIONS[current] ?? [];

  const applyDirect = async (t: Transition) => {
    setSubmitting(true);
    setError(null);
    try {
      await onChange(t.to);
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  const applyWithReason = async () => {
    if (!pendingTo) return;
    if (reason.trim().length < REASON_MIN) {
      setError(`原因至少 ${REASON_MIN} 字`);
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await onChange(pendingTo.to, reason.trim());
      setPendingTo(null);
      setReason("");
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{ position: "relative", display: "inline-block" }}>
      <button
        onClick={() => setOpen((o) => !o)}
        disabled={options.length === 0}
        style={{
          border: "none",
          background: "transparent",
          cursor: options.length === 0 ? "default" : "pointer",
          padding: 0,
        }}
        title={options.length === 0 ? undefined : "更改状态"}
      >
        <StatusBadge status={status} />
      </button>

      {open && options.length > 0 && !pendingTo && (
        <div
          style={{
            position: "absolute",
            top: "100%",
            left: 0,
            marginTop: 4,
            background: "white",
            border: "1px solid #ddd",
            borderRadius: 6,
            boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
            zIndex: 10,
            minWidth: 180,
          }}
        >
          {options.map((t) => (
            <button
              key={t.to}
              onClick={() => (t.needsReason ? setPendingTo(t) : applyDirect(t))}
              disabled={submitting}
              style={{
                display: "block",
                width: "100%",
                padding: "8px 12px",
                border: "none",
                background: "transparent",
                textAlign: "left",
                cursor: "pointer",
                fontSize: 13,
              }}
            >
              {t.label}
            </button>
          ))}
          {error && <div style={{ color: "#c00", padding: "4px 12px", fontSize: 12 }}>{error}</div>}
        </div>
      )}

      {pendingTo && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.3)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 100,
          }}
          onClick={() => !submitting && setPendingTo(null)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: "white",
              padding: 24,
              borderRadius: 8,
              width: 420,
              maxWidth: "90vw",
            }}
          >
            <h3 style={{ margin: "0 0 12px" }}>{pendingTo.label}</h3>
            <p style={{ fontSize: 13, color: "#666", marginTop: 0 }}>
              请说明重新打开的原因（至少 {REASON_MIN} 字）
            </p>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={4}
              autoFocus
              style={{
                width: "100%",
                padding: 8,
                fontSize: 14,
                fontFamily: "inherit",
                boxSizing: "border-box",
              }}
            />
            {error && <div style={{ color: "#c00", marginTop: 8, fontSize: 13 }}>{error}</div>}
            <div style={{ marginTop: 16, display: "flex", gap: 12, justifyContent: "flex-end" }}>
              <button
                onClick={() => setPendingTo(null)}
                disabled={submitting}
                style={{ padding: "8px 16px" }}
              >
                取消
              </button>
              <button
                onClick={applyWithReason}
                disabled={submitting || reason.trim().length < REASON_MIN}
                style={{
                  padding: "8px 16px",
                  background: "#3370ff",
                  color: "white",
                  border: "none",
                  borderRadius: 4,
                  cursor: "pointer",
                }}
              >
                {submitting ? "提交中…" : "确认"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
