import { useEffect, useState } from "react";
import { Eye, Loader2, RotateCw, Settings2, Users2 } from "lucide-react";
import { toast } from "sonner";
import {
  AdminRequiredError,
  fetchScoringRunDetail,
  triggerScoringRerun,
  type ScoringRunDetail,
  type ScoringSubjectScore,
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
  // v2.1 (Phase 2): track which candidate's drawer is open by subject_user_id.
  // Phase 1 single-subject runs effectively have only one possible value here.
  const [evidenceFor, setEvidenceFor] = useState<string | null>(null);
  const [overrideFor, setOverrideFor] = useState<string | null>(null);
  const [metaOpen, setMetaOpen] = useState(false);
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

  const evidenceSubject = detail?.subject_scores.find(
    (s) => s.score.subject_user_id === evidenceFor,
  );
  const overrideSubject = detail?.subject_scores.find(
    (s) => s.score.subject_user_id === overrideFor,
  );

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
              />
              {detail.subject_scores.length > 0 ? (
                <SubjectScoresList
                  detail={detail}
                  onShowEvidence={(subjectId) => setEvidenceFor(subjectId)}
                  onShowOverride={(subjectId) => setOverrideFor(subjectId)}
                />
              ) : detail.run.status === "success" ? (
                <EmptyScoreNotice
                  message="AI 判断证据不足，本次评分跳过（subject 加入 skipped_subjects）"
                />
              ) : detail.run.status === "queued" ||
                detail.run.status === "running" ? (
                <EmptyScoreNotice message="评分生成中…（约 1-5 分钟）" />
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

      {evidenceSubject && detail && (
        <EvidenceDialog
          matterId={detail.run.matter_id}
          matterTitle={detail.run.matter_title}
          subjectDisplay={evidenceSubject.subject_display}
          overall={evidenceSubject.score.overall}
          confidence={evidenceSubject.score.confidence}
          rationale={evidenceSubject.score.rationale}
          dimensions={evidenceSubject.score.dimensions}
          evidence={evidenceSubject.evidence}
          onClose={() => setEvidenceFor(null)}
        />
      )}

      {metaOpen && detail && (
        <RunMetadataDialog
          run={detail.run}
          onClose={() => setMetaOpen(false)}
        />
      )}

      {overrideSubject && detail && (
        <OverrideDialog
          runId={detail.run.run_id}
          currentOverall={overrideSubject.score.overall}
          currentOverride={overrideSubject.score.human_override}
          subjectDisplay={overrideSubject.subject_display}
          onClose={() => setOverrideFor(null)}
          onSaved={(updated) => {
            // Patch the local detail so UI reflects override without refetch.
            // Replace the matching subject_scores entry; also update top-level
            // score field if this was the primary subject.
            setDetail((prev) => {
              if (!prev) return prev;
              const updatedSubjects = prev.subject_scores.map((s) =>
                s.score.subject_user_id === overrideSubject.score.subject_user_id
                  ? { ...s, score: updated }
                  : s,
              );
              const isPrimary =
                prev.run.subject_user_id === overrideSubject.score.subject_user_id;
              return {
                ...prev,
                subject_scores: updatedSubjects,
                score: isPrimary ? updated : prev.score,
              };
            });
            setOverrideFor(null);
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
}: {
  detail: ScoringRunDetail;
  rerunning: boolean;
  onRerun: () => void;
  onShowMeta: () => void;
}) {
  const r = detail.run;
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
      </div>
    </div>
  );
}

/** v2.1 (Phase 2): renders one ScoreCard per scored candidate. Phase 1 runs
 *  with a single subject collapse to a 1-card list with no group header. */
function SubjectScoresList({
  detail,
  onShowEvidence,
  onShowOverride,
}: {
  detail: ScoringRunDetail;
  onShowEvidence: (subjectUserId: string) => void;
  onShowOverride: (subjectUserId: string) => void;
}) {
  const scoredCount = detail.subject_scores.length;
  const skippedCount = detail.skipped_subjects.length;
  const totalCandidates = scoredCount + skippedCount;
  // Show the candidate-set context when more than one person was actually
  // considered (scored or skipped) — avoids noise on Phase 1 single-subject runs.
  const showCandidateContext = totalCandidates > 1;
  return (
    <div className="space-y-3">
      {showCandidateContext && (
        <div className="rounded-[var(--r-sm)] bg-[var(--surface-alt)] px-3 py-2 text-xs text-[var(--text-soft)]">
          <div className="flex items-center gap-1.5 font-semibold">
            <Users2 className="h-3.5 w-3.5" />
            评分候选 {totalCandidates} 人 · 出分 {scoredCount} 人
            {skippedCount > 0 && ` · 证据不足跳过 ${skippedCount} 人`}
          </div>
          <p className="mt-0.5 text-[var(--text-mute)]">
            候选人 = timeline 里出现过 think / act 的作者，每人独立打分。证据归因依据五条线索：文件作者、正文点名、@ 提醒、转交原因、验收动作。
          </p>
        </div>
      )}
      {detail.subject_scores.map((sub) => (
        <SubjectScoreCard
          key={sub.score.subject_user_id}
          sub={sub}
          isPrimary={sub.score.subject_user_id === detail.run.subject_user_id}
          showPrimaryBadge={showCandidateContext}
          onShowEvidence={() => onShowEvidence(sub.score.subject_user_id)}
          onShowOverride={() => onShowOverride(sub.score.subject_user_id)}
        />
      ))}
      {skippedCount > 0 && <SkippedSubjectsPanel detail={detail} />}
    </div>
  );
}

/** v2.2: AI-skipped candidates panel — shows "李帅、张三" instead of leaving
 *  them silently absent. Helps admin distinguish "AI thought about X but
 *  found no evidence" from "X never made it into the candidate set". */
function SkippedSubjectsPanel({ detail }: { detail: ScoringRunDetail }) {
  return (
    <div className="rounded-[var(--r-md)] border border-dashed border-[var(--line)] bg-[var(--surface-alt)] px-4 py-3">
      <div className="flex items-center gap-1.5 text-xs font-semibold text-[var(--text-soft)]">
        <Users2 className="h-3.5 w-3.5" />
        AI 跳过的候选（证据不足，全维度均无信号）
      </div>
      <ul className="mt-2 flex flex-wrap gap-1.5">
        {detail.skipped_subjects.map((s) => (
          <li
            key={s.pinyin}
            className="inline-flex items-center gap-1.5 rounded-full bg-[var(--surface)] py-0.5 pl-0.5 pr-2 text-xs text-[var(--text-soft)]"
            title={s.display ? s.pinyin : undefined}
          >
            {s.avatar_url ? (
              <img
                src={s.avatar_url}
                alt=""
                className="h-5 w-5 rounded-full"
              />
            ) : (
              <span className="h-5 w-5 rounded-full bg-[var(--surface-alt)]" />
            )}
            <span>{s.display ?? s.pinyin}</span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[11px] text-[var(--text-mute)]">
        想给这些人也评分？让他们在该 matter 里有更多动作（写 act / 被评论 /
        被 verify），然后用"重新生成"重跑。
      </p>
    </div>
  );
}

function SubjectScoreCard({
  sub,
  isPrimary,
  showPrimaryBadge,
  onShowEvidence,
  onShowOverride,
}: {
  sub: ScoringSubjectScore;
  isPrimary: boolean;
  showPrimaryBadge: boolean;
  onShowEvidence: () => void;
  onShowOverride: () => void;
}) {
  const { score, evidence, subject_display, subject_avatar_url } = sub;
  // When admin manually overrode, treat the override as the current /
  // displayed total. AI's original number is shown as a secondary annotation
  // for transparency.
  const isOverridden =
    score.human_override !== null && score.human_override.overall !== null;
  const effectiveOverall = isOverridden
    ? (score.human_override!.overall as number)
    : score.overall;

  return (
    <div className="rounded-[var(--r-md)] border border-[var(--line)] bg-[var(--surface)] p-4 space-y-3">
      <div className="flex items-center gap-3">
        {subject_avatar_url ? (
          <img
            src={subject_avatar_url}
            alt=""
            className="h-10 w-10 rounded-full"
          />
        ) : (
          <span className="h-10 w-10 rounded-full bg-[var(--surface-alt)]" />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold">
              {subject_display ?? "(未知)"}
            </h3>
            {showPrimaryBadge && isPrimary && (
              <span
                className="rounded bg-[var(--accent-bg)] px-1.5 text-[10px] font-medium text-[var(--accent)]"
                title="matter.owner —— run 主候选"
              >
                负责人
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

      <div className="flex justify-end gap-2">
        <Button size="sm" variant="outline" onClick={onShowOverride}>
          ✏ 人工修正
        </Button>
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
