import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronRight, Loader2, RotateCw, Search } from "lucide-react";
import { toast } from "sonner";
import {
  AdminRequiredError,
  fetchMatterScoringGroups,
  triggerScoringRerun,
  type MatterGroupRunBrief,
  type MatterGroupSubjectScore,
  type MatterScoringGroup,
  type ScoringRunSummary,
} from "@/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ScoreConfidenceBadge } from "@/components/scoring/ScoreConfidenceBadge";
import { MatterScoresView } from "@/components/scoring/MatterScoresView";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 20;

const onAdminLost = () => {
  toast.error("管理员权限已失效，请刷新或重新登录");
};

export function RunsListTab() {
  const [items, setItems] = useState<MatterScoringGroup[]>([]);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [matterFilter, setMatterFilter] = useState("");
  const [matterFilterDraft, setMatterFilterDraft] = useState("");
  const [offset, setOffset] = useState(0);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [pollKey, setPollKey] = useState(0);
  const [expandedMatters, setExpandedMatters] = useState<Set<string>>(
    () => new Set(),
  );

  const load = async () => {
    setLoading(true);
    try {
      const r = await fetchMatterScoringGroups({
        matter_query: matterFilter || undefined,
        limit: PAGE_SIZE,
        offset,
      });
      setItems(r.items);
      setTotal(r.total);
      setHasMore(r.has_more);
    } catch (e) {
      if (e instanceof AdminRequiredError) {
        onAdminLost();
      } else {
        toast.error(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matterFilter, offset, pollKey]);

  // Auto-refresh while any matter has an in-flight (queued/running) latest run.
  useEffect(() => {
    const hasInFlight = items.some(
      (g) =>
        g.latest_run?.status === "queued" || g.latest_run?.status === "running",
    );
    if (!hasInFlight) return;
    const t = window.setInterval(() => setPollKey((k) => k + 1), 3000);
    return () => window.clearInterval(t);
  }, [items]);

  const onRerun = async (matterId: string) => {
    try {
      const r = await triggerScoringRerun(matterId);
      toast.success(r.message);
      setPollKey((k) => k + 1);
    } catch (e) {
      if (e instanceof AdminRequiredError) {
        onAdminLost();
      } else {
        toast.error(e instanceof Error ? e.message : String(e));
      }
    }
  };

  const toggleExpand = (matterId: string) => {
    setExpandedMatters((prev) => {
      const next = new Set(prev);
      if (next.has(matterId)) next.delete(matterId);
      else next.add(matterId);
      return next;
    });
  };

  const applyMatterFilter = () => {
    setMatterFilter(matterFilterDraft.trim());
    setOffset(0);
  };

  const noFilter = !matterFilter;
  const showOnboarding = !loading && items.length === 0 && noFilter && total === 0;

  return (
    <Card>
      <CardContent className="p-0">
        <div className="flex flex-wrap items-end gap-3 border-b border-[var(--line)] px-4 py-3">
          <div className="flex-1 min-w-[200px]">
            <div className="flex gap-1">
              <Input
                id="matter-filter"
                placeholder="输入想搜索的 matter"
                value={matterFilterDraft}
                onChange={(e) => setMatterFilterDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") applyMatterFilter();
                }}
                className="h-8"
              />
              <Button size="sm" variant="outline" onClick={applyMatterFilter}>
                <Search className="h-3.5 w-3.5" />
              </Button>
              {matterFilter && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setMatterFilter("");
                    setMatterFilterDraft("");
                    setOffset(0);
                  }}
                >
                  清除
                </Button>
              )}
            </div>
          </div>
          <div className="ml-auto text-xs text-[var(--text-mute)]">
            共 {total} 个 matter
          </div>
        </div>

        {loading && items.length === 0 ? (
          <div className="flex items-center justify-center gap-2 px-4 py-8 text-sm text-[var(--text-mute)]">
            <Loader2 className="h-4 w-4 animate-spin" />
            加载中…
          </div>
        ) : showOnboarding ? (
          <EmptyOnboarding />
        ) : items.length === 0 ? (
          <div className="px-4 py-12 text-center text-sm text-[var(--text-mute)]">
            没有匹配的 matter
          </div>
        ) : (
          <div>
            {items.map((g) => (
              <MatterRow
                key={g.matter_id}
                group={g}
                expanded={expandedMatters.has(g.matter_id)}
                onToggleExpand={() => toggleExpand(g.matter_id)}
                onViewRun={(rid) => setActiveRunId(rid)}
                onRerun={() => onRerun(g.matter_id)}
              />
            ))}
          </div>
        )}

        {(offset > 0 || hasMore) && (
          <div className="flex items-center justify-between border-t border-[var(--line)] px-4 py-2 text-xs">
            <Button
              size="sm"
              variant="outline"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              上一页
            </Button>
            <span className="text-[var(--text-mute)]">
              {offset + 1} - {Math.min(offset + PAGE_SIZE, total)} / {total}
            </span>
            <Button
              size="sm"
              variant="outline"
              disabled={!hasMore}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              下一页
            </Button>
          </div>
        )}
      </CardContent>

      {activeRunId && (
        <MatterScoresView
          runId={activeRunId}
          onClose={() => setActiveRunId(null)}
          onAdminLost={onAdminLost}
          onRerunRequested={() => setPollKey((k) => k + 1)}
        />
      )}
    </Card>
  );
}

function EmptyOnboarding() {
  return (
    <div className="flex flex-col items-center gap-3 px-4 py-12 text-center text-sm">
      <p className="text-[var(--text-mute)]">还没有评分任务</p>
      <p className="text-xs text-[var(--text-mute)] max-w-md">
        Matter 进入 finished 状态后会自动入队评分。如果功能尚未启用，请先到「设置」开启。
      </p>
      <Button asChild variant="outline" size="sm">
        <Link to="settings">前往设置</Link>
      </Button>
    </div>
  );
}

function MatterRow({
  group,
  expanded,
  onToggleExpand,
  onViewRun,
  onRerun,
}: {
  group: MatterScoringGroup;
  expanded: boolean;
  onToggleExpand: () => void;
  onViewRun: (runId: string) => void;
  onRerun: () => void;
}) {
  const latest = group.latest_run;
  const totalRuns = group.history.length;
  const hasHistory = totalRuns > 1;
  const latestRunId = latest?.run_id;

  const onRowClick = () => {
    if (latestRunId) onViewRun(latestRunId);
  };

  return (
    <div className="border-t border-[var(--line)] first:border-t-0">
      <div
        className="flex items-center gap-3 px-4 py-3 hover:bg-[var(--surface-alt)] cursor-pointer"
        onClick={onRowClick}
      >
        {/* expand chevron */}
        <button
          type="button"
          className={cn(
            "flex h-6 w-6 items-center justify-center rounded text-[var(--text-mute)] hover:bg-[var(--surface)]",
            !hasHistory && "opacity-0 pointer-events-none",
          )}
          onClick={(e) => {
            e.stopPropagation();
            onToggleExpand();
          }}
          title={expanded ? "收起历史" : `展开 ${totalRuns} 次 rerun 历史`}
        >
          <ChevronRight
            className={cn(
              "h-4 w-4 transition-transform",
              expanded && "rotate-90",
            )}
          />
        </button>

        {/* matter title */}
        <div className="flex flex-col min-w-0 flex-1">
          <span className="font-medium truncate">
            {group.matter_title ?? group.matter_id}
          </span>
          <span className="font-mono text-[10.5px] text-[var(--text-mute)] truncate">
            {group.matter_category}/{group.matter_id}
          </span>
        </div>

        {/* subject chips (latest successful run) — bounded width so adding
            many subjects doesn't push timestamp/actions off the row. */}
        <div className="flex items-center justify-start basis-[480px] shrink-0">
          <SubjectScoreChips
            scores={group.subject_scores}
            skipped={group.skipped_subjects}
          />
        </div>

        {/* status pill + history hint */}
        <div className="flex flex-col items-start gap-0.5 w-28 shrink-0">
          {latest ? (
            <StatusPill status={latest.status} error={latest.error} />
          ) : (
            <span className="text-xs text-[var(--text-mute)]">—</span>
          )}
          {hasHistory && (
            <button
              type="button"
              className="text-[10.5px] text-[var(--text-mute)] hover:text-[var(--accent)] tabular-nums"
              onClick={(e) => {
                e.stopPropagation();
                onToggleExpand();
              }}
            >
              {totalRuns} 次 · {summarizeCounts(group.history_counts)}
            </button>
          )}
        </div>

        {/* timestamp */}
        <span className="text-xs text-[var(--text-mute)] tabular-nums shrink-0 w-32 text-right">
          {latest ? formatTime(latest.started_at) : ""}
        </span>

        {/* actions */}
        <div className="flex shrink-0 gap-1" onClick={(e) => e.stopPropagation()}>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => latestRunId && onViewRun(latestRunId)}
            disabled={!latestRunId}
          >
            详情
          </Button>
          <Button size="sm" variant="ghost" onClick={onRerun} title="重跑">
            <RotateCw className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {expanded && hasHistory && (
        <RunHistoryPanel
          runs={group.history}
          onViewRun={onViewRun}
        />
      )}
    </div>
  );
}

// Display cap: at most 3 scored subjects show as full chips. The rest collapse
// into a single "+N 人" overflow pill with a hover popover. Skipped subjects
// likewise collapse into a single batch pill when 2 or more — admins glance
// the list, drill into details for full breakdown.
const SUBJECT_VISIBLE_LIMIT = 3;
const SKIPPED_BATCH_THRESHOLD = 2;

function confidenceRank(c: string): number {
  if (c === "high") return 3;
  if (c === "medium") return 2;
  if (c === "low") return 1;
  return 0;
}

function effectiveScore(s: MatterGroupSubjectScore): number {
  return s.override_overall !== null ? s.override_overall : s.overall;
}

function SubjectScoreChips({
  scores,
  skipped,
}: {
  scores: MatterGroupSubjectScore[];
  skipped: { display: string | null; pinyin: string }[];
}) {
  if (scores.length === 0 && skipped.length === 0) {
    return <span className="text-xs text-[var(--text-mute)]">—</span>;
  }

  // Sort by confidence high→medium→low, then effective score desc — admins
  // care most about the high-signal scored subjects first.
  const sorted = [...scores].sort((a, b) => {
    const cr = confidenceRank(b.confidence) - confidenceRank(a.confidence);
    if (cr !== 0) return cr;
    return effectiveScore(b) - effectiveScore(a);
  });
  const visible = sorted.slice(0, SUBJECT_VISIBLE_LIMIT);
  const overflow = sorted.slice(SUBJECT_VISIBLE_LIMIT);
  const skippedCollapsed = skipped.length >= SKIPPED_BATCH_THRESHOLD;

  return (
    <div className="flex flex-wrap items-center gap-1.5 max-w-[480px]">
      {visible.map((s) => (
        <ScoreChip key={s.subject_user_id} subject={s} />
      ))}
      {overflow.length > 0 && (
        <OverflowPill subjects={overflow} />
      )}
      {!skippedCollapsed &&
        skipped.map((s) => (
          <SkippedChip
            key={`skip-${s.pinyin}`}
            label={s.display ?? s.pinyin}
          />
        ))}
      {skippedCollapsed && <SkippedBatchPill subjects={skipped} />}
    </div>
  );
}

function ScoreChip({ subject: s }: { subject: MatterGroupSubjectScore }) {
  const score = effectiveScore(s);
  const overridden = s.override_overall !== null;
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full bg-[var(--surface-alt)] py-0.5 pl-0.5 pr-2 text-xs"
      title={
        overridden
          ? `${s.subject_display ?? "?"} · 人工修正 (AI 原始 ${s.overall.toFixed(1)})`
          : `${s.subject_display ?? "?"} · ${s.confidence}`
      }
    >
      {s.subject_avatar_url ? (
        <img
          src={s.subject_avatar_url}
          alt=""
          className="h-4 w-4 rounded-full"
        />
      ) : (
        <span className="h-4 w-4 rounded-full bg-[var(--surface)]" />
      )}
      <span className="truncate max-w-[4.5rem]">
        {s.subject_display ?? "?"}
      </span>
      <span className="font-semibold tabular-nums">
        {score.toFixed(1)}
        {overridden && (
          <span className="ml-0.5 text-[10px] text-[var(--accent)]">✏</span>
        )}
      </span>
      <ScoreConfidenceBadge confidence={s.confidence} size="sm" />
    </span>
  );
}

function SkippedChip({ label }: { label: string }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full border border-dashed border-[var(--line)] px-2 py-0.5 text-xs text-[var(--text-mute)]"
      title="证据不足跳过"
    >
      <span className="truncate max-w-[4.5rem]">{label}</span>
      <span className="text-[10px]">—</span>
    </span>
  );
}

/** "+N 人" overflow pill with hover popover listing the hidden scored
 *  subjects. Pure CSS hover — no extra dep. Click-through stops on the
 *  popover so it doesn't trigger the row's onClick. */
function OverflowPill({
  subjects,
}: {
  subjects: MatterGroupSubjectScore[];
}) {
  return (
    <span className="relative group inline-flex">
      <span className="inline-flex items-center gap-0.5 rounded-full bg-[var(--surface-alt)] px-2 py-0.5 text-xs font-medium text-[var(--text-soft)] cursor-default">
        +{subjects.length} 人
      </span>
      <div
        className="invisible group-hover:visible absolute left-0 top-full mt-1 z-20 min-w-[200px] rounded-md border border-[var(--line)] bg-[var(--surface)] p-1.5 shadow-[var(--shadow-md)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-1 pb-1 text-[10px] font-semibold uppercase tracking-wide text-[var(--text-mute)]">
          其余出分人员
        </div>
        <div className="space-y-0.5">
          {subjects.map((s) => {
            const score = effectiveScore(s);
            const overridden = s.override_overall !== null;
            return (
              <div
                key={s.subject_user_id}
                className="flex items-center gap-2 rounded px-1.5 py-1 text-xs hover:bg-[var(--surface-alt)]"
              >
                {s.subject_avatar_url ? (
                  <img
                    src={s.subject_avatar_url}
                    alt=""
                    className="h-4 w-4 rounded-full"
                  />
                ) : (
                  <span className="h-4 w-4 rounded-full bg-[var(--surface-alt)]" />
                )}
                <span className="flex-1 truncate">
                  {s.subject_display ?? "?"}
                </span>
                <span className="font-semibold tabular-nums">
                  {score.toFixed(1)}
                  {overridden && (
                    <span className="ml-0.5 text-[10px] text-[var(--accent)]">✏</span>
                  )}
                </span>
                <ScoreConfidenceBadge confidence={s.confidence} size="sm" />
              </div>
            );
          })}
        </div>
      </div>
    </span>
  );
}

/** "跳过 N 人" batch pill with hover popover listing the skipped subjects. */
function SkippedBatchPill({
  subjects,
}: {
  subjects: { display: string | null; pinyin: string }[];
}) {
  return (
    <span className="relative group inline-flex">
      <span className="inline-flex items-center gap-0.5 rounded-full border border-dashed border-[var(--line)] px-2 py-0.5 text-xs text-[var(--text-mute)] cursor-default">
        跳过 {subjects.length} 人
      </span>
      <div
        className="invisible group-hover:visible absolute left-0 top-full mt-1 z-20 min-w-[160px] rounded-md border border-[var(--line)] bg-[var(--surface)] p-1.5 shadow-[var(--shadow-md)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-1 pb-1 text-[10px] font-semibold uppercase tracking-wide text-[var(--text-mute)]">
          证据不足跳过
        </div>
        <div className="space-y-0.5">
          {subjects.map((s) => (
            <div
              key={`pop-skip-${s.pinyin}`}
              className="px-1.5 py-1 text-xs text-[var(--text-soft)]"
            >
              {s.display ?? s.pinyin}
            </div>
          ))}
        </div>
      </div>
    </span>
  );
}

function RunHistoryPanel({
  runs,
  onViewRun,
}: {
  runs: MatterGroupRunBrief[];
  onViewRun: (runId: string) => void;
}) {
  return (
    <div className="border-t border-dashed border-[var(--line)] bg-[var(--surface-alt)] px-4 py-2">
      <div className="mb-1.5 text-[10.5px] font-semibold uppercase tracking-wide text-[var(--text-mute)]">
        重跑历史（最新 → 最早）
      </div>
      <div className="space-y-1">
        {runs.map((r) => (
          <button
            key={r.run_id}
            type="button"
            onClick={() => onViewRun(r.run_id)}
            className="flex w-full items-center gap-3 rounded px-2 py-1 text-xs hover:bg-[var(--surface)]"
          >
            <StatusPill status={r.status} error={r.error} compact />
            <span className="font-mono text-[10.5px] text-[var(--text-mute)] tabular-nums w-32 text-left">
              {formatTime(r.started_at)}
            </span>
            <span className="text-[var(--text-mute)] truncate flex-1 text-left">
              {triggeredByLabel(r.triggered_by)}
              {r.error && ` · ${r.error}`}
            </span>
            <span className="font-mono text-[10px] text-[var(--text-mute)]">
              {r.run_id.slice(0, 8)}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

function StatusPill({
  status,
  error,
  compact,
}: {
  status: ScoringRunSummary["status"];
  error: string | null;
  compact?: boolean;
}) {
  const palette: Record<typeof status, { bg: string; fg: string; label: string }> = {
    success: { bg: "var(--ok-bg)", fg: "var(--ok-600)", label: "✅ 成功" },
    failed: { bg: "var(--warn-bg)", fg: "var(--warn-600)", label: "❌ 失败" },
    queued: {
      bg: "var(--surface-alt)",
      fg: "var(--text-mute)",
      label: "⏳ 排队",
    },
    running: {
      bg: "var(--accent-bg)",
      fg: "var(--accent)",
      label: "⏳ 运行中",
    },
    skipped: {
      bg: "var(--surface-alt)",
      fg: "var(--text-mute)",
      label: "⚪ 跳过",
    },
  };
  const c = palette[status];
  return (
    <div className="flex flex-col">
      <span
        className="inline-flex w-fit items-center rounded-full px-2 py-0.5 text-xs font-medium"
        style={{ background: c.bg, color: c.fg }}
      >
        {c.label}
      </span>
      {!compact && error && (status === "failed" || status === "skipped") && (
        <span
          className="mt-0.5 text-[10.5px] truncate max-w-[200px]"
          style={{ color: "var(--warn-600)" }}
          title={error}
        >
          {error}
        </span>
      )}
    </div>
  );
}

function summarizeCounts(
  counts: Partial<Record<ScoringRunSummary["status"], number>>,
): string {
  const parts: string[] = [];
  if (counts.success) parts.push(`${counts.success} 成`);
  if (counts.failed) parts.push(`${counts.failed} 失`);
  if (counts.skipped) parts.push(`${counts.skipped} 跳`);
  if (counts.running) parts.push(`${counts.running} 运`);
  if (counts.queued) parts.push(`${counts.queued} 排`);
  return parts.join(" / ");
}

function triggeredByLabel(t: string): string {
  if (t === "auto") return "自动";
  if (t === "admin:rerun") return "管理员重跑";
  return t;
}

function formatTime(seconds: number): string {
  const d = new Date(seconds * 1000);
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}`;
}
