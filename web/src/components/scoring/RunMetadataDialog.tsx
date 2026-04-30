import { useState } from "react";
import type { ScoringRunSummary } from "@/api";

type Props = {
  run: ScoringRunSummary;
  onClose: () => void;
};

export function RunMetadataDialog({ run, onClose }: Props) {
  const [errorOpen, setErrorOpen] = useState(true);
  const isError = run.status === "failed" || (run.status === "skipped" && !!run.error);

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg max-h-[80vh] overflow-hidden rounded-[var(--r-md)] bg-[var(--surface)] shadow-[var(--shadow-lg)] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[var(--line)] px-5 py-3">
          <h3 className="text-base font-semibold">运行元信息</h3>
          <button
            type="button"
            aria-label="关闭"
            className="rounded p-1 text-[var(--text-mute)] hover:bg-[var(--surface-alt)]"
            onClick={onClose}
          >
            ✕
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-3 space-y-3 text-sm">
          <Field label="run_id" value={run.run_id} mono />
          <Field label="matter_id" value={run.matter_id} mono />
          <Field label="status" value={run.status} />
          <Field label="triggered_by" value={run.triggered_by} />
          <Field label="model" value={run.model || "(未配置)"} />
          <Field
            label="prompt_tokens"
            value={run.prompt_tokens?.toString() ?? "—"}
          />
          <Field
            label="completion_tokens"
            value={run.completion_tokens?.toString() ?? "—"}
          />
          <Field label="started_at" value={formatTime(run.started_at)} />
          <Field
            label="finished_at"
            value={run.finished_at ? formatTime(run.finished_at) : "(进行中)"}
          />
          <Field label="timeline_hash" value={run.timeline_hash} mono small />

          {isError && (
            <div className="rounded border border-[var(--warn-bg)] bg-[var(--warn-bg)]/30 p-2">
              <button
                type="button"
                className="flex w-full items-center justify-between text-left text-xs font-semibold text-[var(--warn-600)]"
                onClick={() => setErrorOpen((v) => !v)}
              >
                <span>error / raw 输出</span>
                <span>{errorOpen ? "▾" : "▸"}</span>
              </button>
              {errorOpen && (
                <pre className="mt-2 whitespace-pre-wrap break-words text-[10.5px] text-[var(--text)]">
                  {run.error}
                </pre>
              )}
            </div>
          )}
        </div>

        <div className="flex justify-end border-t border-[var(--line)] px-5 py-3">
          <button
            type="button"
            className="rounded px-3 py-1 text-sm hover:bg-[var(--surface-alt)]"
            onClick={onClose}
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  mono,
  small,
}: {
  label: string;
  value: string;
  mono?: boolean;
  small?: boolean;
}) {
  return (
    <div className="grid grid-cols-[140px_minmax(0,1fr)] gap-2">
      <span className="text-xs text-[var(--text-mute)]">{label}</span>
      <span
        className={`${mono ? "font-mono" : ""} ${
          small ? "text-[10.5px]" : "text-xs"
        } break-all`}
      >
        {value}
      </span>
    </div>
  );
}

function formatTime(seconds: number): string {
  const d = new Date(seconds * 1000);
  return d.toLocaleString();
}
