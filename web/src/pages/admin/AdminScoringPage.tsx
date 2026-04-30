import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Loader2, RotateCw, Search } from "lucide-react";
import { toast, Toaster } from "sonner";
import {
  AdminRequiredError,
  fetchMe,
  fetchScoringRuns,
  triggerScoringRerun,
  type Me,
  type ScoringRunSummary,
} from "@/api";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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

export function AdminScoringPage() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);

  useEffect(() => {
    fetchMe().then(setMe).catch(() => setMe(null));
  }, []);

  // 角色丢失提示 — 不再有密码 modal，给个 toast 让上层路由处理。
  const onAdminLost = () => {
    toast.error("管理员权限已失效，请刷新或重新登录");
  };

  const isAdmin = !!me?.roles?.includes("admin") && me.status === "active";

  return (
    <div className="min-h-screen" style={{ background: "var(--bg)" }}>
      <Toaster position="top-center" richColors />
      <header
        className="px-6 py-4 backdrop-blur"
        style={{
          borderBottom: "1px solid var(--line)",
          background: "rgba(255, 253, 248, 0.94)",
        }}
      >
        <div className="mx-auto flex max-w-7xl items-center gap-4">
          <Button
            asChild
            variant="ghost"
            size="sm"
            className="h-8 rounded-md hover:bg-[var(--surface-alt)]"
            style={{ color: "var(--text-soft)" }}
          >
            <Link to="/admin">
              <ArrowLeft className="h-4 w-4" /> 返回管理员
            </Link>
          </Button>
          <div className="min-w-0">
            <h1
              className="text-[16px] font-semibold"
              style={{
                fontFamily: "var(--font-serif)",
                letterSpacing: "var(--letter-tight)",
                color: "var(--text)",
              }}
            >
              评分管理
            </h1>
            <p
              className="mt-0.5 text-[11.5px] font-meta"
              style={{ color: "var(--text-mute)" }}
            >
              跨 matter 浏览所有评分任务 · 重跑 · 查看证据
            </p>
          </div>
        </div>
      </header>

      {me === undefined ? (
        <main className="mx-auto max-w-3xl px-6 py-12">
          <p style={{ color: "var(--text-mute)" }}>加载中…</p>
        </main>
      ) : !isAdmin ? (
        <RoleDeniedNotice me={me} />
      ) : (
        <main className="mx-auto max-w-7xl px-6 py-6">
          <RunsTable onAdminLost={onAdminLost} />
        </main>
      )}
    </div>
  );
}

function RoleDeniedNotice({ me }: { me: Me | null }) {
  return (
    <main className="mx-auto max-w-2xl px-6 py-16">
      <Card className="overflow-hidden border-[var(--line)] shadow-[var(--shadow-sm)]">
        <CardHeader>
          <CardTitle className="text-[20px]">需要管理员权限</CardTitle>
          <CardDescription>
            {me === null
              ? "你尚未登录。请先登录后再访问评分管理。"
              : me.status !== "active"
                ? "账号当前不处于活跃状态，无法访问评分管理。"
                : "这个页面仅管理员可访问。"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button asChild>
            <Link to="/">返回首页</Link>
          </Button>
        </CardContent>
      </Card>
    </main>
  );
}

function RunsTable({ onAdminLost }: { onAdminLost: () => void }) {
  const [items, setItems] = useState<ScoringRunSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState("");
  const [matterFilter, setMatterFilter] = useState("");
  const [matterFilterDraft, setMatterFilterDraft] = useState("");
  const [offset, setOffset] = useState(0);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [activeMatterId, setActiveMatterId] = useState<string | null>(null);
  const [pollKey, setPollKey] = useState(0);

  const load = async () => {
    setLoading(true);
    try {
      const r = await fetchScoringRuns({
        status: statusFilter || undefined,
        matter_id: matterFilter || undefined,
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
      // Trigger immediate refresh
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
          <div className="space-y-1 flex-1 min-w-[200px]">
            <Label className="text-xs" htmlFor="matter-filter">
              matter_id 包含
            </Label>
            <div className="flex gap-1">
              <Input
                id="matter-filter"
                placeholder="精确 matter_id ..."
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

        {/* Table */}
        {loading && items.length === 0 ? (
          <div className="flex items-center justify-center gap-2 px-4 py-8 text-sm text-[var(--text-mute)]">
            <Loader2 className="h-4 w-4 animate-spin" />
            加载中…
          </div>
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
                  onView={() => {
                    setActiveRunId(r.run_id);
                    setActiveMatterId(r.matter_id);
                  }}
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
          onClose={() => {
            setActiveRunId(null);
            setActiveMatterId(null);
          }}
          onAdminLost={onAdminLost}
          onRerunRequested={() => {
            // Drawer triggered a rerun — refresh the underlying list
            setPollKey((k) => k + 1);
          }}
        />
      )}
      {activeMatterId === null /* lint silencer */ && null}
    </Card>
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
