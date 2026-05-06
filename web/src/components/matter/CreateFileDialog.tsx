import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Grip, Maximize2, Minimize2, Plus } from "lucide-react";
import {
  searchContacts,
  isTimelineFileItem,
  type DocType,
  type Judgement,
  type MatterStatus,
  type MentionBlock,
  type NewFileIn,
  type Outcome,
  type StatusChange,
  type TimelineFileItem,
  type TimelineItem,
  type Verification,
} from "@/api";
import {
  computeAtPublish,
  onUserEdit,
  type BodySource,
} from "@/lib/bodySource";
import type { GateResult } from "@/hooks/useConfirmPublishQuality";
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
import {
  MentionField,
  emptyMention,
  isMentionValid,
} from "@/components/MentionField";

export type CreateFormContext =
  | { kind: "card"; type: DocType; quote: string }
  | { kind: "page"; type: "insight" | "result"; reviewedTransition?: boolean };

type FormState = {
  summary: string;
  body: string;
  owner: string;
  ownerDisplayName: string;
  refer: string[];
  verifications: Verification[];
  thinkChange: "none" | string;
  actPromote: boolean;
  outcome: Outcome;
  mentions: MentionBlock;
  body_source: BodySource;
  body_source_snapshot?: string;
};

export type FormSnapshot = {
  summary: string;
  body: string;
  owner: string;
  ownerDisplayName: string;
  refer: string[];
  verifications: Verification[];
  status_change?: StatusChange;
  outcome?: Outcome;
  mentions?: MentionBlock;
  body_source?: BodySource;
  body_source_snapshot?: string;
};

function initialFormState(
  ctx: CreateFormContext,
  sessionPivotUserId: string,
  sessionName: string,
  actFiles: TimelineFileItem[],
  initial?: Partial<FormSnapshot>,
): FormState {
  const defaultVerifications: Verification[] =
    ctx.kind === "card" &&
    ctx.type === "verify" &&
    actFiles.some((a) => a.file === ctx.quote)
      ? [{ target: ctx.quote, judgement: "passed", comment: "" }]
      : [];
  const thinkChange = (() => {
    if (ctx.type !== "think") return "none";
    const sc = initial?.status_change;
    if (!sc) return "none";
    return `${sc.from}->${sc.to}`;
  })();
  const actPromote =
    ctx.type === "act" &&
    initial?.status_change?.from === "planning" &&
    initial?.status_change?.to === "executing";
  return {
    summary: initial?.summary ?? "",
    body: initial?.body ?? "",
    owner: initial?.owner ?? sessionPivotUserId,
    ownerDisplayName: initial?.ownerDisplayName ?? sessionName,
    refer: initial?.refer ?? [],
    verifications: initial?.verifications ?? defaultVerifications,
    thinkChange,
    actPromote,
    outcome: initial?.outcome ?? "finished",
    mentions: initial?.mentions ?? emptyMention(),
    body_source: initial?.body_source ?? "manual",
    body_source_snapshot: initial?.body_source_snapshot,
  };
}

export function CreateFileForm({
  context,
  matterStatus,
  sessionPivotUserId,
  sessionName,
  timeline,
  onCancel,
  onSubmit,
  onSuccess,
  onGenerateSummary,
  onFormBlur,
  onDeleteDraft,
  initial,
  confirmPublishQuality,
  onSendToAI,
  isAIBusy,
  busyTitle,
}: {
  context: CreateFormContext;
  matterStatus: MatterStatus;
  sessionPivotUserId: string;
  sessionName: string;
  timeline: TimelineItem[];
  onCancel?: () => void;
  onSubmit: (body: NewFileIn) => Promise<boolean>;
  onSuccess?: () => void;
  onGenerateSummary?: (draft: {
    type: DocType;
    body: string;
    quote: string | null;
  }) => Promise<string>;
  onFormBlur?: (snapshot: FormSnapshot) => void | Promise<void>;
  onDeleteDraft?: () => void | Promise<void>;
  initial?: Partial<FormSnapshot>;
  // Quality gate (only the parent has the dialog mounted; pass it down).
  // think/act/verify call this; result/insight bypass it (decided in submit()).
  confirmPublishQuality?: (args: {
    bodySource: BodySource;
    blockedByAIBusy: boolean;
    busyTitle?: string;
  }) => Promise<GateResult>;
  onSendToAI?: (body: string) => void;
  isAIBusy?: boolean;
  busyTitle?: string;
}) {
  const actFiles = useMemo(
    () => timeline.filter(isTimelineFileItem).filter((t) => t.type === "act"),
    [timeline],
  );
  const fileTimeline = useMemo(
    () => timeline.filter(isTimelineFileItem),
    [timeline],
  );
  const [form, setForm] = useState<FormState>(() =>
    initialFormState(context, sessionPivotUserId, sessionName, actFiles, initial),
  );
  const [stage, setStage] = useState<"idle" | "generating" | "publishing">("idle");
  const [bodyEditorFullscreen, setBodyEditorFullscreen] = useState(false);
  const submitting = stage !== "idle";

  // 圈人选中后用人名显示而不是 open_id slice。MentionField 在用户从下拉
  // 选人时会直接 mutate 这个对象(master 自带行为);从草稿恢复进来的
  // open_ids 没人名,下面 effect 调 searchContacts(oid) 批量补齐。
  const [resolvedNames, setResolvedNames] = useState<Record<string, string>>({});
  useEffect(() => {
    const missing = form.mentions.open_ids.filter((oid) => !(oid in resolvedNames));
    if (missing.length === 0) return;
    let cancelled = false;
    void (async () => {
      const fresh: Record<string, string> = {};
      for (const oid of missing) {
        try {
          const results = await searchContacts(oid);
          const found = results.find((c) => c.open_id === oid);
          if (found) fresh[oid] = found.name;
        } catch {
          /* 单个失败不阻塞整体 */
        }
      }
      if (cancelled || Object.keys(fresh).length === 0) return;
      setResolvedNames((prev) => ({ ...prev, ...fresh }));
    })();
    return () => {
      cancelled = true;
    };
    // 仅依赖 open_ids;resolvedNames 由 setState 自然驱动下一轮,加入 deps
    // 会形成无害但啰嗦的循环。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.mentions.open_ids]);

  const type: DocType = context.type;
  const quote = context.kind === "card" ? context.quote : null;

  const isAct = type === "act";
  const isVerify = type === "verify";
  const isThink = type === "think";
  const isInsight = type === "insight";
  const isResult = type === "result";
  // 推进到 reviewed:由调用方通过 context.reviewedTransition 显式声明；
  // 表单内部不再让用户勾选,避免"insight 发布"和"reviewed 状态迁移"耦合。
  const reviewedTransition =
    context.kind === "page" && context.reviewedTransition === true && isInsight;

  // matter 是否曾经进入过 executing 状态——通过扫 timeline 上的
  // status_change.to / from 判断。如果没有,paused → executing 这条恢复路径
  // 不该出现(matter 都没启动过执行,何来"恢复执行")。
  const everExecuted = useMemo(
    () =>
      timeline.some(
        (t) =>
          t.status_change?.to === "executing" ||
          t.status_change?.from === "executing",
      ),
    [timeline],
  );

  const computeStatusChange = (): StatusChange | undefined => {
    if (isThink && form.thinkChange !== "none") {
      const [from, to] = form.thinkChange.split("->") as [MatterStatus, MatterStatus];
      // matter 未经过 executing 时屏蔽 paused → executing,跟 UI 一致。
      if (from === "paused" && to === "executing" && !everExecuted) {
        return undefined;
      }
      return { from, to };
    }
    if (isAct && form.actPromote) {
      return { from: "planning", to: "executing" };
    }
    if (reviewedTransition) {
      if (matterStatus !== "finished" && matterStatus !== "cancelled") return undefined;
      return { from: matterStatus, to: "reviewed" };
    }
    if (isResult) {
      return { from: "executing", to: form.outcome };
    }
    return undefined;
  };

  const snapshot = (): FormSnapshot => ({
    summary: form.summary,
    body: form.body,
    owner: form.owner,
    ownerDisplayName: form.ownerDisplayName,
    refer: form.refer,
    verifications: form.verifications,
    status_change: computeStatusChange(),
    outcome: isResult ? form.outcome : undefined,
    mentions: form.mentions.open_ids.length > 0 ? form.mentions : undefined,
    body_source: form.body_source,
    body_source_snapshot: form.body_source_snapshot,
  });

  const handleContainerBlur = (e: React.FocusEvent<HTMLDivElement>) => {
    if (!onFormBlur) return;
    const next = e.relatedTarget as Node | null;
    if (next && e.currentTarget.contains(next)) return;
    void onFormBlur(snapshot());
  };

  const submit = async () => {
    if (!onGenerateSummary && !form.summary.trim()) {
      toast.error("summary 必填");
      return;
    }
    if (onGenerateSummary && !form.body.trim()) {
      toast.error("正文必填（AI 将根据正文生成 summary）");
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

    if (
      reviewedTransition &&
      matterStatus !== "finished" &&
      matterStatus !== "cancelled"
    ) {
      toast.error("推进到 reviewed 前置必须是 finished / cancelled");
      return;
    }
    if (
      isThink &&
      form.thinkChange === "paused->executing" &&
      !everExecuted
    ) {
      toast.error("matter 未经过 executing,不能从 paused 直接切换为 executing(请选恢复为规划)");
      return;
    }
    const status_change = computeStatusChange();

    if ((isAct || isVerify) && !form.owner.trim()) {
      toast.error("owner 必填");
      return;
    }
    if (!isMentionValid(form.mentions)) {
      toast.error("圈人后必须填一句话");
      return;
    }

    // Quality gate must run BEFORE the (potentially slow) summary AI call.
    // Order matters for two reasons:
    //   1. If the user cancels or sends to AI, we waste no AI summary call.
    //   2. We never enter the "generating" stage in those branches, so an
    //      early return doesn't leave the form stuck with submitting=true
    //      (this previously froze the form on "send_to_ai" → no buttons).
    //
    // result/insight bypass the gate per design §四 — they also do NOT carry
    // body_source into NewFileIn so the post frontmatter omits the field.
    const qualityGated = isThink || isAct || isVerify;
    let publishSource: BodySource | undefined;
    if (qualityGated && confirmPublishQuality) {
      const finalSource = computeAtPublish(
        {
          body_source: form.body_source,
          body_source_snapshot: form.body_source_snapshot,
        },
        form.body,
      );
      const gate = await confirmPublishQuality({
        bodySource: finalSource,
        blockedByAIBusy: !!isAIBusy,
        busyTitle,
      });
      if (gate === "cancel") return;
      if (gate === "send_to_ai") {
        onSendToAI?.(form.body);
        return;
      }
      publishSource = finalSource;
    }

    let summary = form.summary.trim();
    // form.summary 已有值时直接用——通常由 AIPane【生成草稿】流程在回填 body
    // 时同步回填 summary,跳过这次 AI 调用,免去发布时再等一次。
    // 仅当 summary 为空且有 onGenerateSummary 兜底(手动填卡片场景)才再调一次 AI。
    if (!summary && onGenerateSummary) {
      setStage("generating");
      try {
        summary = (
          await onGenerateSummary({
            type,
            body: form.body.trim(),
            quote,
          })
        ).trim();
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "生成 summary 失败");
        setStage("idle");
        return;
      }
      if (!summary) {
        toast.error("AI 生成的 summary 为空");
        setStage("idle");
        return;
      }
    }

    const body: NewFileIn = {
      type,
      summary,
      body: form.body.trim() || undefined,
      owner: isAct || isVerify ? form.owner : undefined,
      quote: quote ?? undefined,
      refer: form.refer.length > 0 ? form.refer : undefined,
      status_change,
    };
    if (isVerify) body.verifications = form.verifications;
    if (isResult) body.outcome = form.outcome;
    // 圈人 + 留言:matter 没有"顶级 mention"概念,挂在 mentions[0] 上
    // (server MentionIn 接 targets: list[str])。
    if (form.mentions.open_ids.length > 0) {
      body.mentions = [
        {
          body: form.mentions.comments.trim(),
          targets: form.mentions.open_ids,
        },
      ];
    }
    if (publishSource) body.body_source = publishSource;

    setStage("publishing");
    try {
      const ok = await onSubmit(body);
      if (ok) onSuccess?.();
    } finally {
      setStage("idle");
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

  const updateBody = (next: string) => {
    setForm((p) => {
      const nextSource = onUserEdit(
        {
          body_source: p.body_source,
          body_source_snapshot: p.body_source_snapshot,
        },
        next,
      );
      return { ...p, body: next, ...nextSource };
    });
  };

  return (
    <div className="space-y-3 text-sm" onBlur={handleContainerBlur}>
      {quote && (
        <FieldRow label="quote" hint="入口自动带入，只读">
          <div className="rounded-md border border-[var(--line)] bg-[var(--surface-alt)] px-3 py-2 font-mono text-xs text-[var(--text-soft)]">
            {shortFile(quote)}
          </div>
        </FieldRow>
      )}

      {isResult && (
        <FieldRow label="outcome" required hint="讨论最终客观结果；发布后 executing → outcome">
          <div className="flex gap-5 text-sm">
            <label className="flex items-center gap-1.5">
              <input
                type="radio"
                checked={form.outcome === "finished"}
                onChange={() => setForm((p) => ({ ...p, outcome: "finished" }))}
              />
              完成（finished）
            </label>
            <label className="flex items-center gap-1.5">
              <input
                type="radio"
                checked={form.outcome === "cancelled"}
                onChange={() => setForm((p) => ({ ...p, outcome: "cancelled" }))}
              />
              取消（cancelled）
            </label>
          </div>
        </FieldRow>
      )}

      {(isAct || isVerify) && (
        <FieldRow
          label="owner"
          required
          hint={isAct ? "执行责任人（可 ≠ 作者）" : "对这次判断负责的人"}
        >
          <OwnerPicker
            value={form.owner}
            onChange={(pivotUserId, name) =>
              setForm((p) => ({ ...p, owner: pivotUserId, ownerDisplayName: name }))
            }
            sessionPivotUserId={sessionPivotUserId}
            sessionName={sessionName}
            displayName={form.ownerDisplayName}
          />
        </FieldRow>
      )}

      {!onGenerateSummary && (
        <FieldRow label="summary" required hint="一句话说明目的 / 判断">
          <Input
            value={form.summary}
            onChange={(e) => setForm((p) => ({ ...p, summary: e.target.value }))}
            maxLength={200}
            placeholder="一句话摘要"
          />
        </FieldRow>
      )}

      <FieldRow
        label="body"
        required={!!onGenerateSummary}
        hint={
          onGenerateSummary
            ? "Markdown 正文 · 发布时 AI 将基于此生成 summary"
            : "Markdown 正文（可选）"
        }
      >
        <BodyMarkdownEditor
          value={form.body}
          onChange={updateBody}
          placeholder={isAct ? "## Summary / What To Do / Notes …" : "写下详细内容 …"}
          fullscreen={bodyEditorFullscreen}
          onFullscreenChange={setBodyEditorFullscreen}
        />
      </FieldRow>

      <MentionField
        value={form.mentions}
        onChange={(v) => setForm((p) => ({ ...p, mentions: v }))}
        resolvedNames={resolvedNames}
      />

      {!isVerify && !isResult && (
        <FieldRow label="refer" hint={`可选 · 多选上限 ${MAX_REFER}`}>
          <div className="flex flex-wrap gap-1.5">
            {fileTimeline
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
                        ? "border-[var(--accent)] bg-[var(--accent-bg)] text-[var(--accent)]"
                        : "border-[var(--line-strong)] text-[var(--text-soft)] hover:border-[var(--text-fade)]",
                    )}
                  >
                    {shortFile(x.file)}
                  </button>
                );
              })}
            {fileTimeline.length <= 1 && (
              <span className="text-xs text-[var(--text-fade)]">（无其它文件）</span>
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
                {everExecuted && (
                  <RadioRow
                    checked={form.thinkChange === "paused->executing"}
                    onChange={() => setForm((p) => ({ ...p, thinkChange: "paused->executing" }))}
                    label="恢复为执行（paused → executing）"
                  />
                )}
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

      {reviewedTransition && (
        <div className="rounded-md border border-[color-mix(in_srgb,var(--danger-500)_24%,var(--line))] bg-[color-mix(in_srgb,var(--danger-500)_10%,var(--surface))] px-3 py-2 text-xs text-[var(--danger-600)]">
          ⚠ 这条 insight 提交后会推进讨论到 <span className="font-mono">reviewed</span>
          （{matterStatus} → reviewed）。归档后不再允许新增任何文件，操作不可撤销。
        </div>
      )}

      {isResult && (
        <div className="rounded-md border border-[color-mix(in_srgb,var(--danger-500)_24%,var(--line))] bg-[color-mix(in_srgb,var(--danger-500)_10%,var(--surface))] px-3 py-2 text-xs text-[var(--danger-600)]">
          ⚠ 这条 result 提交后会收口讨论
          （<span className="font-mono">executing</span> → <span className="font-mono">{form.outcome}</span>）。
          收口后不再允许新增 act / verify / 执行性 think，只剩 insight 可追加，操作不可撤销。
        </div>
      )}

      <div className="flex items-center justify-end gap-2 pt-2">
        {onCancel && (
          <Button variant="outline" size="sm" onClick={onCancel} disabled={submitting}>
            取消
          </Button>
        )}
        <Button size="sm" onClick={() => void submit()} disabled={submitting}>
          {stage === "generating"
            ? "生成摘要中…"
            : stage === "publishing"
              ? "发布中…"
              : "发布"}
        </Button>
        {onDeleteDraft && (
          <Button
            variant="outline"
            size="sm"
            className="border-[color-mix(in_srgb,var(--danger-500)_24%,var(--line))] text-[var(--danger-600)] hover:bg-[color-mix(in_srgb,var(--danger-500)_10%,var(--surface))] hover:text-[var(--danger-600)]"
            onClick={() => void onDeleteDraft()}
            disabled={submitting}
          >
            删除草稿
          </Button>
        )}
      </div>
    </div>
  );
}

export function CreateFileDialog({
  open,
  matterStatus,
  sessionPivotUserId,
  sessionName,
  timeline,
  onClose,
  onSubmit,
}: {
  open: boolean;
  matterStatus: MatterStatus;
  sessionPivotUserId: string;
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
            类型 <span className="font-mono">insight</span> · 复盘沉淀。如需推进到 reviewed 归档，请用主页的【推进到 Reviewed】按钮。
          </DialogDescription>
        </DialogHeader>
        {open && (
          <CreateFileForm
            context={{ kind: "page", type: "insight" }}
            matterStatus={matterStatus}
            sessionPivotUserId={sessionPivotUserId}
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

function BodyMarkdownEditor({
  value,
  onChange,
  placeholder,
  fullscreen,
  onFullscreenChange,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  fullscreen: boolean;
  onFullscreenChange: (value: boolean) => void;
}) {
  useEffect(() => {
    if (!fullscreen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onFullscreenChange(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [fullscreen, onFullscreenChange]);

  const textarea = (
    <Textarea
      rows={fullscreen ? undefined : 5}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className={cn(
        "border-0 bg-transparent shadow-none focus-visible:ring-0",
        fullscreen
          ? "min-h-0 flex-1 resize-none rounded-none px-4 py-3 text-[15px] leading-7 sm:px-6"
          : "min-h-[9rem] resize-y rounded-none px-3 pb-8 pt-2 leading-6",
      )}
      autoFocus={fullscreen}
    />
  );

  if (fullscreen) {
    return (
      <div className="fixed inset-0 z-[70] flex min-h-0 flex-col bg-[var(--surface)]">
        <div className="flex min-h-12 items-center justify-between border-b border-[var(--line)] px-3 sm:px-5">
          <div className="min-w-0 text-sm font-semibold text-[var(--text)]">
            body
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-8 w-8 rounded-[var(--r-sm)] text-[var(--text-mute)] hover:bg-[var(--surface-alt)]"
            onClick={() => onFullscreenChange(false)}
            title="退出全屏"
            aria-label="退出全屏"
          >
            <Minimize2 className="h-4 w-4" />
          </Button>
        </div>
        {textarea}
      </div>
    );
  }

  return (
    <div className="group relative overflow-hidden rounded-[var(--r-sm)] border border-[var(--line-strong)] bg-[var(--surface)] transition-colors focus-within:border-[var(--accent)]">
      <div className="flex items-center justify-between border-b border-[var(--line-soft)] px-2 py-1">
        <div className="flex min-w-0 items-center gap-1.5 text-[11px] text-[var(--text-fade)]">
          <Grip className="h-3.5 w-3.5 shrink-0 text-[var(--text-mute)]" />
          <span className="truncate">拖动右下角可拉开</span>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-7 w-7 rounded-[var(--r-sm)] text-[var(--text-mute)] hover:bg-[var(--surface-alt)] hover:text-[var(--accent)]"
          onClick={() => onFullscreenChange(true)}
          title="全屏编辑"
          aria-label="全屏编辑"
        >
          <Maximize2 className="h-3.5 w-3.5" />
        </Button>
      </div>
      {textarea}
      <div
        className="pointer-events-none absolute bottom-2 right-2 flex h-5 w-5 items-end justify-end text-[var(--accent)] opacity-75 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100"
        aria-hidden
      >
        <Grip className="h-4 w-4 rotate-45" />
      </div>
    </div>
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
        <span className="font-medium text-[var(--text-soft)]">
          {label}
          {required && <span className="ml-0.5 text-[var(--danger-500)]">*</span>}
        </span>
        {hint && <span className="text-[var(--text-fade)]">{hint}</span>}
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
  actFiles: TimelineFileItem[];
}) {
  if (actFiles.length === 0) {
    return (
      <div className="rounded-md border border-[color-mix(in_srgb,var(--warn-500)_24%,var(--line))] bg-[color-mix(in_srgb,var(--warn-500)_10%,var(--surface))] p-2 text-xs text-[var(--warn-600)]">
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
    <div className="space-y-2 rounded-md border border-[var(--line)] p-2">
      {verifications.map((v, i) => (
        <div key={i} className="grid grid-cols-[1fr_auto] gap-2 rounded-md bg-[var(--surface-alt)] p-2 sm:grid-cols-12">
          <select
            className="col-span-1 min-w-0 rounded-md border border-[var(--line-strong)] bg-[var(--surface)] px-2 py-1 font-mono text-[11px] sm:col-span-5"
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
            className="col-span-1 min-w-0 rounded-md border border-[var(--line-strong)] bg-[var(--surface)] px-2 py-1 text-xs sm:col-span-3"
            value={v.judgement}
            onChange={(e) => update(i, { judgement: e.target.value as Judgement })}
          >
            <option value="passed">passed</option>
            <option value="failed">failed</option>
            <option value="cancelled">cancelled</option>
          </select>
          <Input
            className="col-span-1 h-8 min-w-0 text-xs sm:col-span-3 sm:h-7"
            value={v.comment}
            onChange={(e) => update(i, { comment: e.target.value })}
            placeholder="comment*"
          />
          <button
            type="button"
            onClick={() => remove(i)}
            className="col-span-1 row-span-3 min-h-8 self-stretch rounded-md text-xs text-[var(--text-fade)] hover:bg-[var(--surface)] hover:text-[var(--danger-500)] sm:row-span-1"
            title="移除"
          >
            ×
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={add}
        className="inline-flex items-center gap-1 rounded-md border border-[var(--line-strong)] px-2 py-1 text-[11px] text-[var(--text-soft)] hover:bg-[var(--surface-alt)]"
      >
        <Plus className="h-3 w-3" />
        追加 target
      </button>
    </div>
  );
}
