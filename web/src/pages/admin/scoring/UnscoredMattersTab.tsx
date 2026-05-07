import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlertCircle, Loader2, RotateCw, Search } from "lucide-react";
import { toast } from "sonner";
import {
  AdminRequiredError,
  fetchUnscoredMatters,
  triggerScoringRerun,
  type UnscoredMatter,
} from "@/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 50;

const onAdminLost = () => {
  toast.error("管理员权限已失效，请刷新或重新登录");
};

/** "需关注" tab — finished matters that don't have a successful scoring run.
 *
 *  Per matter, surface the most recent skip/failure reason classified into
 *  short Chinese label + actionable hint, so admin can triage without
 *  digging through logs. The reason classification happens server-side —
 *  see _classify_reason in admin_scoring.py.
 */
export function UnscoredMattersTab() {
  const [items, setItems] = useState<UnscoredMatter[]>([]);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [scoringDisabled, setScoringDisabled] = useState(false);
  const [offset, setOffset] = useState(0);
  const [pollKey, setPollKey] = useState(0);
  const [matterQuery, setMatterQuery] = useState("");
  const [matterQueryDraft, setMatterQueryDraft] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      const r = await fetchUnscoredMatters({
        matter_query: matterQuery || undefined,
        limit: PAGE_SIZE,
        offset,
      });
      setItems(r.items);
      setTotal(r.total);
      setHasMore(r.has_more);
      setScoringDisabled(r.scoring_disabled);
    } catch (e) {
      if (e instanceof AdminRequiredError) onAdminLost();
      else toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matterQuery, offset, pollKey]);

  const applyQuery = () => {
    setMatterQuery(matterQueryDraft.trim());
    setOffset(0);
  };

  const onRerun = async (matterId: string) => {
    try {
      const r = await triggerScoringRerun(matterId);
      toast.success(r.message);
      // Refresh after a beat — worker takes ~1-5 min, but the row should
      // disappear from this list as soon as it gets a queued run.
      setTimeout(() => setPollKey((k) => k + 1), 1500);
    } catch (e) {
      if (e instanceof AdminRequiredError) onAdminLost();
      else toast.error(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <Card>
      <CardContent className="p-0">
        {scoringDisabled && <ScoringDisabledBanner />}

        <div className="flex flex-wrap items-end gap-3 border-b border-[var(--line)] px-4 py-3">
          <div className="flex-1 min-w-[260px]">
            <div className="text-sm font-semibold">未评分的 matter</div>
            <div className="text-xs text-[var(--text-mute)]">
              已 finished 但还没成功评分。点重跑会立即入队，约 1-5 分钟出结果
            </div>
          </div>
          <div className="flex items-center gap-1">
            <Input
              placeholder="输入想搜索的 matter"
              value={matterQueryDraft}
              onChange={(e) => setMatterQueryDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") applyQuery();
              }}
              className="h-8 w-[240px]"
            />
            <Button size="sm" variant="outline" onClick={applyQuery}>
              <Search className="h-3.5 w-3.5" />
            </Button>
            {matterQuery && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setMatterQuery("");
                  setMatterQueryDraft("");
                  setOffset(0);
                }}
              >
                清除
              </Button>
            )}
          </div>
          <span className="text-xs text-[var(--text-mute)] tabular-nums">
            共 {total} 条
          </span>
        </div>

        {loading && items.length === 0 ? (
          <div className="flex items-center justify-center gap-2 px-4 py-8 text-sm text-[var(--text-mute)]">
            <Loader2 className="h-4 w-4 animate-spin" />
            加载中…
          </div>
        ) : items.length === 0 ? (
          <div className="px-4 py-12 text-center text-sm text-[var(--text-mute)]">
            {matterQuery
              ? `没有匹配 "${matterQuery}" 的未评分 matter`
              : "🎉 所有 finished matter 都有评分了"}
          </div>
        ) : (
          <div>
            {items.map((m) => (
              <UnscoredRow
                key={m.matter_id}
                matter={m}
                onRerun={() => onRerun(m.matter_id)}
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
    </Card>
  );
}

function ScoringDisabledBanner() {
  return (
    <div
      className="flex items-start gap-3 border-b border-[var(--line)] bg-[var(--warn-bg)] px-4 py-3 text-sm"
      style={{ color: "var(--warn-600)" }}
    >
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="flex-1">
        <div className="font-semibold">评分功能未启用</div>
        <div className="mt-0.5 text-xs">
          全局开关关着，所有 finished matter 都不会自动评分。下面列表显示的是
          一旦启用即可入队的 matter。
        </div>
      </div>
      <Button asChild size="sm" variant="outline">
        <Link to="../settings">前往设置</Link>
      </Button>
    </div>
  );
}

function UnscoredRow({
  matter,
  onRerun,
}: {
  matter: UnscoredMatter;
  onRerun: () => void;
}) {
  const reasonColor = reasonColorFor(matter.reason_code);
  return (
    <div className="border-t border-[var(--line)] first:border-t-0">
      <div className="flex items-center gap-3 px-4 py-3">
        <div className="flex flex-col min-w-0 flex-1">
          <span
            className="font-medium truncate"
            title={matter.matter_title ?? matter.matter_id}
          >
            {matter.matter_title ?? matter.matter_id}
          </span>
          <span className="font-mono text-[10.5px] text-[var(--text-mute)] truncate">
            {matter.matter_category}/{matter.matter_id}
          </span>
        </div>

        <div className="flex flex-col items-start gap-0.5 w-[260px] shrink-0">
          <span
            className={cn(
              "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
            )}
            style={{ background: reasonColor.bg, color: reasonColor.fg }}
            title={matter.reason_detail || undefined}
          >
            {matter.reason_label}
            {matter.reason_detail && (
              <span className="ml-1 font-mono text-[10px] opacity-70">
                · {matter.reason_detail}
              </span>
            )}
          </span>
          <span className="text-[10.5px] text-[var(--text-mute)]">
            {matter.action_hint}
          </span>
        </div>

        <span className="text-xs text-[var(--text-mute)] tabular-nums shrink-0 w-[7rem] text-right">
          {matter.finished_at ? formatTime(matter.finished_at) : "—"}
        </span>

        <Button
          size="sm"
          variant="outline"
          onClick={onRerun}
          className="shrink-0"
          title="立即入队评分"
        >
          <RotateCw className="mr-1 h-3.5 w-3.5" />
          立即评分
        </Button>
      </div>
    </div>
  );
}

function reasonColorFor(code: string): { bg: string; fg: string } {
  // never_triggered / matter_index_missing 是"未触发"或"数据问题"，柔和提示色
  // no_owner / owner_unresolved / no_category / no_candidates 是配置问题，警告色
  // worker_error / race_lost / orphan / superseded_by_rerun 是运行时问题，错误色
  if (code === "never_triggered" || code === "matter_index_missing") {
    return { bg: "var(--surface-alt)", fg: "var(--text-soft)" };
  }
  if (
    code === "no_owner" ||
    code === "owner_unresolved" ||
    code === "no_category" ||
    code === "no_candidates"
  ) {
    return { bg: "var(--warn-bg)", fg: "var(--warn-600)" };
  }
  return { bg: "var(--accent-bg)", fg: "var(--accent)" };
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
