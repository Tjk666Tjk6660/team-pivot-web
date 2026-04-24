import { useMemo, useState } from "react";
import { toast } from "sonner";
import { Plus } from "lucide-react";
import type {
  DocType,
  Judgement,
  MatterStatus,
  NewFileIn,
  StatusChange,
  TimelineItem,
  Verification,
} from "@/api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { MAX_REFER, shortFile } from "./timeline-config";
import { OwnerPicker } from "./OwnerPicker";

export type CreateFormContext =
  | { kind: "card"; type: DocType; quote: string }
  | { kind: "page"; type: "insight" };

type FormState = {
  summary: string;
  body: string;
  owner: string;
  ownerDisplayName: string;
  refer: string[];
  verifications: Verification[];
  thinkChange: "none" | string;
  actPromote: boolean;
  insightReview: boolean;
};

function initialFormState(
  ctx: CreateFormContext,
  sessionOpenId: string,
  sessionName: string,
  actFiles: TimelineItem[],
): FormState {
  const verifications: Verification[] =
    ctx.kind === "card" &&
    ctx.type === "verify" &&
    actFiles.some((a) => a.file === ctx.quote)
      ? [{ target: ctx.quote, judgement: "passed", comment: "" }]
      : [];
  return {
    summary: "",
    body: "",
    owner: sessionOpenId,
    ownerDisplayName: sessionName,
    refer: [],
    verifications,
    thinkChange: "none",
    actPromote: false,
    insightReview: false,
  };
}

export function CreateFileForm({
  context,
  matterStatus,
  sessionOpenId,
  sessionName,
  timeline,
  onCancel,
  onSubmit,
  onSuccess,
}: {
  context: CreateFormContext;
  matterStatus: MatterStatus;
  sessionOpenId: string;
  sessionName: string;
  timeline: TimelineItem[];
  onCancel?: () => void;
  onSubmit: (body: NewFileIn) => Promise<boolean>;
  onSuccess?: () => void;
}) {
  const actFiles = useMemo(
    () => timeline.filter((t) => t.type === "act"),
    [timeline],
  );
  const [form, setForm] = useState<FormState>(() =>
    initialFormState(context, sessionOpenId, sessionName, actFiles),
  );
  const [submitting, setSubmitting] = useState(false);

  const type: DocType = context.type;
  const quote = context.kind === "card" ? context.quote : null;

  const isAct = type === "act";
  const isVerify = type === "verify";
  const isThink = type === "think";
  const isInsight = type === "insight";

  const submit = async () => {
    if (!form.summary.trim()) {
      toast.error("summary 必填");
      return;
    }
    if (isVerify) {
      if (form.verifications.length === 0) {
        toast.error("verify 至少需要 1 条 verification");
        return;
      }
      for (const v of form.verifications) {
        if (!v.comment.trim()) {
          toast.error("每条 verification.comment 必填");
          return;
        }
      }
    }

    let status_change: StatusChange | undefined;
    if (isThink && form.thinkChange !== "none") {
      const [from, to] = form.thinkChange.split("->") as [MatterStatus, MatterStatus];
      status_change = { from, to };
    } else if (isAct && form.actPromote) {
      status_change = { from: "planning", to: "executing" };
    } else if (isInsight && form.insightReview) {
      if (matterStatus !== "finished" && matterStatus !== "cancelled") {
        toast.error("推进到 reviewed 前置必须是 finished / cancelled");
        return;
      }
      status_change = { from: matterStatus, to: "reviewed" };
    }

    if ((isAct || isVerify) && !form.owner.trim()) {
      toast.error("owner 必填");
      return;
    }
    const body: NewFileIn = {
      type,
      summary: form.summary.trim(),
      body: form.body.trim() || undefined,
      owner: isAct || isVerify ? form.owner : undefined,
      quote: quote ?? undefined,
      refer: form.refer.length > 0 ? form.refer : undefined,
      status_change,
    };
    if (isVerify) body.verifications = form.verifications;

    setSubmitting(true);
    try {
      const ok = await onSubmit(body);
      if (ok) onSuccess?.();
    } finally {
      setSubmitting(false);
    }
  };

  const toggleRefer = (file: string) => {
    setForm((prev) => {
      if (prev.refer.includes(file)) {
        return { ...prev, refer: prev.refer.filter((f) => f !== file) };
      }
      if (prev.refer.length >= MAX_REFER) {
        toast.error(`refer 多选上限 ${MAX_REFER}`);
        return prev;
      }
      return { ...prev, refer: [...prev.refer, file] };
    });
  };

  return (
    <div className="space-y-3 text-sm">
      <FieldRow label="quote" hint={quote ? "入口自动带入，只读" : "页面级动作 · 无 quote"}>
        <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 font-mono text-xs text-slate-700">
          {quote ? shortFile(quote) : "（空）"}
        </div>
      </FieldRow>

      {(isAct || isVerify) && (
        <FieldRow
          label="owner"
          required
          hint={isAct ? "执行责任人（可 ≠ 作者）" : "对这次判断负责的人"}
        >
          <OwnerPicker
            value={form.owner}
            onChange={(openId, name) =>
              setForm((p) => ({ ...p, owner: openId, ownerDisplayName: name }))
            }
            sessionOpenId={sessionOpenId}
            sessionName={sessionName}
            displayName={form.ownerDisplayName}
          />
        </FieldRow>
      )}

      <FieldRow label="summary" required hint="一句话说明目的 / 判断">
        <Input
          value={form.summary}
          onChange={(e) => setForm((p) => ({ ...p, summary: e.target.value }))}
          maxLength={200}
          placeholder="一句话摘要"
        />
      </FieldRow>

      <FieldRow label="body" hint="Markdown 正文（可选）">
        <Textarea
          rows={4}
          value={form.body}
          onChange={(e) => setForm((p) => ({ ...p, body: e.target.value }))}
          placeholder={isAct ? "## Summary / What To Do / Notes …" : "写下详细内容 …"}
        />
      </FieldRow>

      {!isVerify && (
        <FieldRow label="refer" hint={`可选 · 多选上限 ${MAX_REFER}`}>
          <div className="flex flex-wrap gap-1.5">
            {timeline
              .filter((x) => x.file !== quote)
              .map((x) => {
                const selected = form.refer.includes(x.file);
                return (
                  <button
                    type="button"
                    key={x.file}
                    onClick={() => toggleRefer(x.file)}
                    className={cn(
                      "rounded-full border px-2 py-0.5 font-mono text-[11px]",
                      selected
                        ? "border-indigo-400 bg-indigo-100 text-indigo-800"
                        : "border-slate-300 text-slate-600 hover:border-slate-400",
                    )}
                  >
                    {shortFile(x.file)}
                  </button>
                );
              })}
            {timeline.length <= 1 && (
              <span className="text-xs text-slate-400">（无其它文件）</span>
            )}
          </div>
        </FieldRow>
      )}

      {isVerify && (
        <FieldRow label="verifications" required hint="每条 target 必须是本 matter 的 act">
          <VerificationsEditor
            verifications={form.verifications}
            setVerifications={(v) => setForm((p) => ({ ...p, verifications: v }))}
            actFiles={actFiles}
          />
        </FieldRow>
      )}

      {isThink && (
        <FieldRow label="附加状态迁移" hint="think 是 paused 进出的唯一触发通道（可选）">
          <div className="flex flex-col gap-1 text-sm">
            <RadioRow
              checked={form.thinkChange === "none"}
              onChange={() => setForm((p) => ({ ...p, thinkChange: "none" }))}
              label="不切换状态"
            />
            {(matterStatus === "planning" || matterStatus === "executing") && (
              <RadioRow
                checked={form.thinkChange === `${matterStatus}->paused`}
                onChange={() =>
                  setForm((p) => ({ ...p, thinkChange: `${matterStatus}->paused` }))
                }
                label={`同时暂停（${matterStatus} → paused）`}
              />
            )}
            {matterStatus === "paused" && (
              <>
                <RadioRow
                  checked={form.thinkChange === "paused->planning"}
                  onChange={() => setForm((p) => ({ ...p, thinkChange: "paused->planning" }))}
                  label="恢复为规划（paused → planning）"
                />
                <RadioRow
                  checked={form.thinkChange === "paused->executing"}
                  onChange={() => setForm((p) => ({ ...p, thinkChange: "paused->executing" }))}
                  label="恢复为执行（paused → executing）"
                />
              </>
            )}
          </div>
        </FieldRow>
      )}

      {isAct && matterStatus === "planning" && (
        <FieldRow label="附加状态迁移">
          <label className="flex items-center gap-1.5 text-sm">
            <input
              type="checkbox"
              checked={form.actPromote}
              onChange={(e) => setForm((p) => ({ ...p, actPromote: e.target.checked }))}
            />
            正式进入执行（planning → executing）
          </label>
        </FieldRow>
      )}

      {isInsight && (
        <FieldRow label="附加状态迁移">
          <label className="flex items-center gap-1.5 text-sm">
            <input
              type="checkbox"
              checked={form.insightReview}
              onChange={(e) => setForm((p) => ({ ...p, insightReview: e.target.checked }))}
            />
            同时推进到 reviewed（{matterStatus} → reviewed）
          </label>
        </FieldRow>
      )}

      <div className="flex items-center justify-end gap-2 pt-2">
        {onCancel && (
          <Button variant="outline" size="sm" onClick={onCancel} disabled={submitting}>
            取消
          </Button>
        )}
        <Button size="sm" onClick={() => void submit()} disabled={submitting}>
          {submitting ? "发布中…" : "发布"}
        </Button>
      </div>
    </div>
  );
}

export function CreateFileDialog({
  open,
  matterStatus,
  sessionOpenId,
  sessionName,
  timeline,
  onClose,
  onSubmit,
}: {
  open: boolean;
  matterStatus: MatterStatus;
  sessionOpenId: string;
  sessionName: string;
  timeline: TimelineItem[];
  onClose: () => void;
  onSubmit: (body: NewFileIn) => Promise<boolean>;
}) {
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>生成 insight</DialogTitle>
          <DialogDescription>
            类型 <span className="font-mono">insight</span> · 复盘沉淀；可勾选同时推进到 reviewed
          </DialogDescription>
        </DialogHeader>
        {open && (
          <CreateFileForm
            context={{ kind: "page", type: "insight" }}
            matterStatus={matterStatus}
            sessionOpenId={sessionOpenId}
            sessionName={sessionName}
            timeline={timeline}
            onCancel={onClose}
            onSubmit={onSubmit}
            onSuccess={onClose}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function FieldRow({
  label,
  required,
  hint,
  children,
}: {
  label: string;
  required?: boolean;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-1 flex items-center gap-2 text-xs">
        <span className="font-medium text-slate-700">
          {label}
          {required && <span className="ml-0.5 text-red-500">*</span>}
        </span>
        {hint && <span className="text-slate-400">{hint}</span>}
      </div>
      {children}
    </div>
  );
}

function RadioRow({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: () => void;
  label: string;
}) {
  return (
    <label className="flex items-center gap-1.5">
      <input type="radio" checked={checked} onChange={onChange} />
      {label}
    </label>
  );
}

function VerificationsEditor({
  verifications,
  setVerifications,
  actFiles,
}: {
  verifications: Verification[];
  setVerifications: (v: Verification[]) => void;
  actFiles: TimelineItem[];
}) {
  if (actFiles.length === 0) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">
        当前 matter 没有 act — 无法创建 verify。请先在 planning / executing 下追加 act。
      </div>
    );
  }
  const update = (i: number, patch: Partial<Verification>) =>
    setVerifications(verifications.map((v, idx) => (idx === i ? { ...v, ...patch } : v)));
  const remove = (i: number) =>
    setVerifications(verifications.filter((_, idx) => idx !== i));
  const add = () =>
    setVerifications([
      ...verifications,
      { target: actFiles[0].file, judgement: "passed", comment: "" },
    ]);

  return (
    <div className="space-y-2 rounded-md border border-slate-200 p-2">
      {verifications.map((v, i) => (
        <div key={i} className="grid grid-cols-12 gap-2 rounded-md bg-slate-50 p-2">
          <select
            className="col-span-5 rounded-md border border-slate-300 bg-white px-2 py-1 font-mono text-[11px]"
            value={v.target}
            onChange={(e) => update(i, { target: e.target.value })}
          >
            {actFiles.map((a) => (
              <option key={a.file} value={a.file}>
                {shortFile(a.file)}
              </option>
            ))}
          </select>
          <select
            className="col-span-3 rounded-md border border-slate-300 bg-white px-2 py-1 text-xs"
            value={v.judgement}
            onChange={(e) => update(i, { judgement: e.target.value as Judgement })}
          >
            <option value="passed">passed</option>
            <option value="failed">failed</option>
            <option value="cancelled">cancelled</option>
          </select>
          <Input
            className="col-span-3 h-7 text-xs"
            value={v.comment}
            onChange={(e) => update(i, { comment: e.target.value })}
            placeholder="comment*"
          />
          <button
            type="button"
            onClick={() => remove(i)}
            className="col-span-1 text-xs text-slate-400 hover:text-red-500"
            title="移除"
          >
            ×
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={add}
        className="inline-flex items-center gap-1 rounded-md border border-slate-300 px-2 py-1 text-[11px] text-slate-600 hover:bg-slate-50"
      >
        <Plus className="h-3 w-3" />
        追加 target
      </button>
    </div>
  );
}
