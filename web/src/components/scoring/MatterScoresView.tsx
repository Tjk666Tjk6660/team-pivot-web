import { useEffect, useState } from "react";
import { Eye, Loader2, RotateCw, Settings2 } from "lucide-react";
import { toast } from "sonner";
import {
  AdminRequiredError,
  fetchScoringRunDetail,
  triggerScoringRerun,
  type ScoringRunDetail,
} from "@/api";
import { Button } from "@/components/ui/button";
import { ScoreConfidenceBadge } from "./ScoreConfidenceBadge";
import { DimensionBars } from "./DimensionBars";
import { EvidenceDialog } from "./EvidenceDialog";
import { OverrideDialog } from "./OverrideDialog";
import { RunMetadataDialog } from "./RunMetadataDialog";

type Props = {
  runId: string;
  onClose: () => void;
  onAdminLost: () => void;
  onRerunRequested?: () => void;
};

export function MatterScoresView({
  runId,
  onClose,
  onAdminLost,
  onRerunRequested,
}: Props) {
  const [detail, setDetail] = useState<ScoringRunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [metaOpen, setMetaOpen] = useState(false);
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [rerunning, setRerunning] = useState(false);

  const load = () => {
    setLoading(true);
    fetchScoringRunDetail(runId)
      .then((d) => setDetail(d))
      .catch((e) => {
        if (e instanceof AdminRequiredError) {
          onAdminLost();
        } else {
          toast.error(e instanceof Error ? e.message : String(e));
        }
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  const onRerun = async () => {
    if (!detail) return;
    setRerunning(true);
    try {
      const r = await triggerScoringRerun(detail.run.matter_id);
      toast.success(r.message);
      onRerunRequested?.();
    } catch (e) {
      if (e instanceof AdminRequiredError) {
        onAdminLost();
      } else {
        toast.error(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setRerunning(false);
    }
  };

  return (
    <>
      <aside
        className="fixed inset-y-0 right-0 z-50 w-full max-w-2xl overflow-y-auto bg-[var(--bg)] shadow-[var(--shadow-lg)] border-l border-[var(--line)]"
        role="dialog"
        aria-label="评分详情"
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-[var(--line)] bg-[var(--surface)] px-5 py-3">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold">
              {detail?.run.matter_title ?? detail?.run.matter_id ?? "评分详情"}
            </h2>
            {detail && (
              <p className="mt-0.5 text-xs text-[var(--text-mute)]">
                matter_id: {detail.run.matter_id} · 状态:{" "}
                <span style={{ color: STATUS_COLOR[detail.run.status] }}>
                  {STATUS_LABEL[detail.run.status]}
                </span>
              </p>
            )}
          </div>
          <button
            type="button"
            aria-label="关闭"
            className="rounded p-1 text-[var(--text-mute)] hover:bg-[var(--surface-alt)] hover:text-[var(--text)]"
            onClick={onClose}
          >
            ✕
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          {loading ? (
            <div className="flex items-center gap-2 text-sm text-[var(--text-mute)]">
              <Loader2 className="h-4 w-4 animate-spin" />
              加载中…
            </div>
          ) : !detail ? (
            <p className="text-sm text-[var(--text-mute)]">无数据</p>
          ) : (
            <>
              <RunHeader
                detail={detail}
                rerunning={rerunning}
                onRerun={onRerun}
                onShowMeta={() => setMetaOpen(true)}
                onShowOverride={() => setOverrideOpen(true)}
              />
              {detail.score ? (
                <ScoreCard
                  detail={detail}
                  onShowEvidence={() => setEvidenceOpen(true)}
                />
              ) : detail.run.status === "success" ? (
                <EmptyScoreNotice
                  message="AI 判断证据不足，本次评分跳过（subject 加入 skipped_subjects）"
                />
              ) : detail.run.status === "queued" ||
                detail.run.status === "running" ? (
                <EmptyScoreNotice message="评分生成中…（约 1-2 分钟）" />
              ) : detail.run.status === "skipped" ? (
                <EmptyScoreNotice
                  message={`run 跳过（${detail.run.error || "未知原因"}）`}
                />
              ) : (
                <EmptyScoreNotice
                  message={`run 失败：${detail.run.error || "未知错误"}`}
                  variant="error"
                />
              )}
            </>
          )}
        </div>
      </aside>

      {evidenceOpen && detail?.score && (
        <EvidenceDialog
          matterId={detail.run.matter_id}
          matterTitle={detail.run.matter_title}
          subjectDisplay={detail.run.subject_display}
          overall={detail.score.overall}
          confidence={detail.score.confidence}
          rationale={detail.score.rationale}
          dimensions={detail.score.dimensions}
          evidence={detail.evidence}
          onClose={() => setEvidenceOpen(false)}
        />
      )}

      {metaOpen && detail && (
        <RunMetadataDialog
          run={detail.run}
          onClose={() => setMetaOpen(false)}
        />
      )}

      {overrideOpen && detail?.score && (
        <OverrideDialog
          runId={detail.run.run_id}
          currentOverall={detail.score.overall}
          currentOverride={detail.score.human_override}
          subjectDisplay={detail.run.subject_display}
          onClose={() => setOverrideOpen(false)}
          onSaved={(updated) => {
            // Patch the local detail so UI reflects override without refetch
            setDetail((prev) =>
              prev ? { ...prev, score: updated } : prev,
            );
            setOverrideOpen(false);
          }}
          onAdminLost={onAdminLost}
        />
      )}
    </>
  );
}

function RunHeader({
  detail,
  rerunning,
  onRerun,
  onShowMeta,
  onShowOverride,
}: {
  detail: ScoringRunDetail;
  rerunning: boolean;
  onRerun: () => void;
  onShowMeta: () => void;
  onShowOverride: () => void;
}) {
  const r = detail.run;
  const hasScore = detail.score !== null;
  return (
    <div className="rounded-[var(--r-md)] border border-[var(--line)] bg-[var(--surface)] px-4 py-3 space-y-2">
      <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-[var(--text-mute)]">
        <div>
          run_id:{" "}
          <span className="font-mono text-[10.5px] text-[var(--text-soft)]">
            {r.run_id.slice(0, 8)}…
          </span>
        </div>
        <div>
          模型:{" "}
          <span className="text-[var(--text-soft)]">{r.model ?? "—"}</span>
        </div>
        <div>开始: {formatTime(r.started_at)}</div>
        <div>
          {r.finished_at ? `完成: ${formatTime(r.finished_at)}` : "进行中…"}
        </div>
        {r.prompt_tokens && (
          <div>
            tokens: {r.prompt_tokens} ↗ / {r.completion_tokens ?? "—"} ↘
          </div>
        )}
        <div>
          触发: {TRIGGERED_LABEL[r.triggered_by] ?? r.triggered_by}
        </div>
      </div>
      <div className="flex flex-wrap gap-2 pt-1 border-t border-[var(--line)]">
        <Button
          size="sm"
          variant="outline"
          onClick={onRerun}
          disabled={rerunning}
          title="入队一次新的评分（绕过幂等）"
        >
          <RotateCw className={`mr-1 h-3.5 w-3.5 ${rerunning ? "animate-spin" : ""}`} />
          {rerunning ? "排队中…" : "重新生成"}
        </Button>
        <Button size="sm" variant="outline" onClick={onShowMeta}>
          <Settings2 className="mr-1 h-3.5 w-3.5" />
          元信息
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={onShowOverride}
          disabled={!hasScore}
          title={
            hasScore
              ? "人工修正总分（保留 AI 原始打分作为审计）"
              : "无 score 行可修正（run 失败 / 跳过）"
          }
        >
          ✏ 人工修正
        </Button>
      </div>
    </div>
  );
}

function ScoreCard({
  detail,
  onShowEvidence,
}: {
  detail: ScoringRunDetail;
  onShowEvidence: () => void;
}) {
  const { run, score, evidence } = detail;
  if (!score) return null;

  // When admin manually overrode, treat the override as the current /
  // displayed total. AI's original number is shown as a secondary annotation
  // for transparency. Confidence label keeps its AI-context meaning either
  // way (it's a property of the AI evaluation, not the override).
  const isOverridden =
    score.human_override !== null && score.human_override.overall !== null;
  const effectiveOverall = isOverridden
    ? (score.human_override!.overall as number)
    : score.overall;

  return (
    <div className="rounded-[var(--r-md)] border border-[var(--line)] bg-[var(--surface)] p-4 space-y-3">
      <div className="flex items-center gap-3">
        {run.subject_avatar_url ? (
          <img
            src={run.subject_avatar_url}
            alt=""
            className="h-10 w-10 rounded-full"
          />
        ) : (
          <span className="h-10 w-10 rounded-full bg-[var(--surface-alt)]" />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold">
              {run.subject_display ?? "(未知)"}
            </h3>
            {run.subject_status && run.subject_status !== "active" && (
              <span className="rounded bg-[var(--warn-bg)] px-1.5 text-[10px] text-[var(--warn-600)]">
                {run.subject_status === "deleted" ? "已离职" : run.subject_status}
              </span>
            )}
          </div>
        </div>
        <div className="text-right">
          <div className="text-2xl font-bold tabular-nums">
            ⭐ {effectiveOverall.toFixed(1)}
            <span className="ml-0.5 text-sm font-normal text-[var(--text-mute)]">
              / 5
            </span>
          </div>
          {isOverridden ? (
            <div className="mt-0.5 text-[11px] text-[var(--text-mute)]">
              ✏ 修正自 AI {score.overall.toFixed(1)} ({score.confidence})
            </div>
          ) : (
            <ScoreConfidenceBadge confidence={score.confidence} />
          )}
        </div>
      </div>

      {score.rationale && (
        <p className="rounded bg-[var(--surface-alt)] px-3 py-2 text-sm italic">
          "{score.rationale}"
        </p>
      )}

      <div className="rounded border border-[var(--line)] bg-[var(--surface-alt)] p-3">
        <DimensionBars dimensions={score.dimensions} />
      </div>

      <div className="flex justify-end">
        <Button size="sm" onClick={onShowEvidence}>
          <Eye className="mr-1 h-3.5 w-3.5" />
          查看证据 ({evidence.length})
        </Button>
      </div>

      {isOverridden && score.human_override!.note && (
        <div className="rounded border border-[var(--accent-soft)] bg-[var(--accent-bg)]/40 px-3 py-2 text-xs text-[var(--text-soft)]">
          <span className="font-semibold">修正原因:</span>{" "}
          {score.human_override!.note}
        </div>
      )}
    </div>
  );
}

function EmptyScoreNotice({
  message,
  variant = "info",
}: {
  message: string;
  variant?: "info" | "error";
}) {
  const colors =
    variant === "error"
      ? { bg: "var(--warn-bg)", fg: "var(--warn-600)" }
      : { bg: "var(--surface-alt)", fg: "var(--text-mute)" };
  return (
    <div
      className="rounded-[var(--r-md)] border border-[var(--line)] px-4 py-6 text-sm"
      style={{ background: colors.bg, color: colors.fg }}
    >
      {message}
    </div>
  );
}

const STATUS_COLOR: Record<string, string> = {
  queued: "var(--text-mute)",
  running: "var(--accent)",
  success: "var(--ok-600)",
  failed: "var(--warn-600)",
  skipped: "var(--text-mute)",
};

const STATUS_LABEL: Record<string, string> = {
  queued: "排队中",
  running: "运行中",
  success: "成功",
  failed: "失败",
  skipped: "跳过",
};

const TRIGGERED_LABEL: Record<string, string> = {
  auto: "自动",
  "admin:rerun": "管理员手动重跑",
  "admin:manual": "管理员手动触发",
};

function formatTime(seconds: number): string {
  const d = new Date(seconds * 1000);
  return d.toLocaleString();
}
