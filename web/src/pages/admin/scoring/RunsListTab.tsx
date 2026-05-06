import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Loader2, RotateCw, Search } from "lucide-react";
import { toast } from "sonner";
import {
  AdminRequiredError,
  fetchScoringRuns,
  triggerScoringRerun,
  type ScoringRunSummary,
} from "@/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScoreConfidenceBadge } from "@/components/scoring/ScoreConfidenceBadge";
import { MatterScoresView } from "@/components/scoring/MatterScoresView";

const PAGE_SIZE = 20;

const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "全部状态" },
  { value: "success", label: "成功" },
  { value: "failed", label: "失败" },
  { value: "skipped", label: "跳过" },
  { value: "queued", label: "排队中" },
  { value: "running", label: "运行中" },
];

const onAdminLost = () => {
  toast.error("管理员权限已失效，请刷新或重新登录");
};

export function RunsListTab() {
  const [items, setItems] = useState<ScoringRunSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState("");
  const [matterFilter, setMatterFilter] = useState("");
  const [matterFilterDraft, setMatterFilterDraft] = useState("");
  const [offset, setOffset] = useState(0);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [pollKey, setPollKey] = useState(0);

  const load = async () => {
    setLoading(true);
    try {
      const r = await fetchScoringRuns({
        status: statusFilter || undefined,
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
  }, [statusFilter, matterFilter, offset, pollKey]);

  // Auto-refresh while there are queued/running rows on screen.
  useEffect(() => {
    const hasInFlight = items.some(
      (r) => r.status === "queued" || r.status === "running",
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

  const applyMatterFilter = () => {
    setMatterFilter(matterFilterDraft.trim());
    setOffset(0);
  };

  const noFilter = !statusFilter && !matterFilter;
  const showOnboarding = !loading && items.length === 0 && noFilter && total === 0;

  return (
    <Card>
      <CardContent className="p-0">
        {/* Filters */}
        <div className="flex flex-wrap items-end gap-3 border-b border-[var(--line)] px-4 py-3">
          <div className="space-y-1">
            <Label className="text-xs">状态</Label>
            <select
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value);
                setOffset(0);
              }}
              className="h-8 rounded-[var(--r-sm)] border border-[var(--line)] bg-[var(--surface)] px-2 text-sm"
            >
              {STATUS_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
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
            共 {total} 条
          </div>
        </div>

        {/* Table / empty */}
        {loading && items.length === 0 ? (
          <div className="flex items-center justify-center gap-2 px-4 py-8 text-sm text-[var(--text-mute)]">
            <Loader2 className="h-4 w-4 animate-spin" />
            加载中…
          </div>
        ) : showOnboarding ? (
          <EmptyOnboarding />
        ) : items.length === 0 ? (
          <div className="px-4 py-12 text-center text-sm text-[var(--text-mute)]">
            没有匹配的评分任务
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-[var(--surface-alt)] text-xs text-[var(--text-mute)]">
              <tr>
                <th className="px-3 py-2 text-left">Matter</th>
                <th className="px-3 py-2 text-left">Owner</th>
                <th className="px-3 py-2 text-right">总分</th>
                <th className="px-3 py-2 text-left">置信</th>
                <th className="px-3 py-2 text-left">状态</th>
                <th className="px-3 py-2 text-left">时间</th>
                <th className="px-3 py-2 text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <RunRow
                  key={r.run_id}
                  run={r}
                  onView={() => setActiveRunId(r.run_id)}
                  onRerun={() => onRerun(r.matter_id)}
                />
              ))}
            </tbody>
          </table>
        )}

        {/* Pagination */}
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

/** Shown when there are zero runs in the system AND no filter is set —
 *  helps a fresh admin understand why the list is empty + nudges them to
 *  the settings tab if scoring isn't enabled yet. */
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

function RunRow({
  run,
  onView,
  onRerun,
}: {
  run: ScoringRunSummary;
  onView: () => void;
  onRerun: () => void;
}) {
  return (
    <tr
      className="border-t border-[var(--line)] hover:bg-[var(--surface-alt)] cursor-pointer"
      onClick={onView}
    >
      <td className="px-3 py-2">
        <div className="flex flex-col min-w-0">
          <span className="font-medium truncate">
            {run.matter_title ?? run.matter_id}
          </span>
          <span className="font-mono text-[10.5px] text-[var(--text-mute)] truncate">
            {run.matter_category}/{run.matter_id}
          </span>
        </div>
      </td>
      <td className="px-3 py-2">
        <div className="flex items-center gap-1.5">
          {run.subject_avatar_url ? (
            <img
              src={run.subject_avatar_url}
              alt=""
              className="h-5 w-5 rounded-full"
            />
          ) : (
            <span className="h-5 w-5 rounded-full bg-[var(--surface-alt)]" />
          )}
          <span className="truncate">{run.subject_display ?? "—"}</span>
        </div>
      </td>
      <td className="px-3 py-2 text-right tabular-nums font-semibold">
        {run.score ? (
          run.score.override_overall !== null ? (
            <span
              title={`AI 原始 ${run.score.overall.toFixed(1)}`}
              className="inline-flex items-center gap-0.5"
            >
              {run.score.override_overall.toFixed(1)}
              <span className="text-[10px] text-[var(--accent)]">✏</span>
            </span>
          ) : (
            run.score.overall.toFixed(1)
          )
        ) : (
          "—"
        )}
      </td>
      <td className="px-3 py-2">
        {run.score ? (
          <ScoreConfidenceBadge confidence={run.score.confidence} size="sm" />
        ) : (
          <span className="text-[var(--text-mute)]">—</span>
        )}
      </td>
      <td className="px-3 py-2">
        <StatusPill status={run.status} error={run.error} />
      </td>
      <td className="px-3 py-2 text-xs text-[var(--text-mute)] tabular-nums">
        {formatTime(run.started_at)}
      </td>
      <td className="px-3 py-2 text-right">
        <div className="flex justify-end gap-1" onClick={(e) => e.stopPropagation()}>
          <Button size="sm" variant="ghost" onClick={onView}>
            详情
          </Button>
          <Button size="sm" variant="ghost" onClick={onRerun} title="重跑">
            <RotateCw className="h-3.5 w-3.5" />
          </Button>
        </div>
      </td>
    </tr>
  );
}

function StatusPill({
  status,
  error,
}: {
  status: ScoringRunSummary["status"];
  error: string | null;
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
      {error && (status === "failed" || status === "skipped") && (
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

function formatTime(seconds: number): string {
  const d = new Date(seconds * 1000);
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}`;
}
