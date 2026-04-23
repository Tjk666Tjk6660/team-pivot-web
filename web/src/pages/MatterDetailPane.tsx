import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ChevronLeft, Sparkles, Star } from "lucide-react";
import {
  appendMatterComment,
  appendMatterFile,
  appendMatterResult,
  fetchMatter,
  fetchMe,
  type DocType,
  type MatterDetail as MatterDetailData,
  type NewFileIn,
  type Outcome,
} from "@/api";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/StatusBadge";
import { TimelineStrip } from "@/components/matter/TimelineStrip";
import { FileCard } from "@/components/matter/FileCard";
import { CreateFileDialog, type CreateDialogContext } from "@/components/matter/CreateFileDialog";
import { ResultConfirmDialog } from "@/components/matter/ResultConfirmDialog";
import { STATUS_DESC } from "@/components/matter/timeline-config";
import { HomeWelcomePane } from "@/pages/HomeWelcomePane";
import { useDashboard } from "@/pages/Dashboard";
import { cn } from "@/lib/utils";

export function MatterDetailEmpty() {
  return <HomeWelcomePane />;
}

export function MatterDetailPane() {
  const { matter_id } = useParams<{ matter_id: string }>();
  const { reloadLists, threadMeta, toggleMatterFavorite } = useDashboard();
  const [data, setData] = useState<MatterDetailData | null | undefined>(undefined);
  const [sessionPinyin, setSessionPinyin] = useState<string>("");
  const [sessionName, setSessionName] = useState<string>("");
  const [createCtx, setCreateCtx] = useState<CreateDialogContext | null>(null);
  const [resultOpen, setResultOpen] = useState(false);
  const [highlight, setHighlight] = useState<string | null>(null);
  const cardRefs = useRef<Record<string, HTMLDivElement | null>>({});

  const load = useCallback(() => {
    if (!matter_id) return;
    fetchMatter(matter_id)
      .then(setData)
      .catch((e) => {
        toast.error(e instanceof Error ? e.message : String(e));
        setData(null);
      });
  }, [matter_id]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    fetchMe()
      .then((me) => {
        setSessionPinyin(me?.pinyin ?? "");
        setSessionName(me?.name ?? "");
      })
      .catch(() => {
        setSessionPinyin("");
        setSessionName("");
      });
  }, []);

  const onJump = (file: string) => {
    const el = cardRefs.current[file];
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    setHighlight(file);
    window.setTimeout(() => setHighlight(null), 1600);
  };

  if (data === undefined) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Loading…
      </div>
    );
  }
  if (data === null) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-destructive">
        Matter not found
      </div>
    );
  }

  const { matter, timeline } = data;
  const allowed = STATUS_DESC[matter.current_status];
  const canGenerateResult = matter.current_status === "executing";
  const canGenerateInsight =
    matter.current_status === "finished" || matter.current_status === "cancelled";

  const afterWrite = async () => {
    await Promise.resolve();
    load();
    await reloadLists();
  };

  const submitNewFile = async (body: NewFileIn) => {
    if (!matter_id) return;
    try {
      await appendMatterFile(matter_id, body);
      toast.success(
        body.status_change
          ? `已发布 ${body.type} · 事项 ${body.status_change.from} → ${body.status_change.to}`
          : `已发布 ${body.type}`,
      );
      setCreateCtx(null);
      await afterWrite();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    }
  };

  const submitResult = async (body: {
    summary: string;
    body?: string;
    outcome: Outcome;
  }) => {
    if (!matter_id) return;
    try {
      await appendMatterResult(matter_id, body);
      toast.success(`已发布 result · 事项 executing → ${body.outcome}`);
      setResultOpen(false);
      await afterWrite();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    }
  };

  const submitComment = async (targetFile: string, body: string) => {
    if (!matter_id) return;
    try {
      await appendMatterComment(matter_id, { target_file: targetFile, body });
      toast.success("已追加评论");
      await afterWrite();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="relative h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-5xl px-3 py-3 sm:px-5 sm:py-5">
        {/* mobile back link */}
        <div className="mb-3 lg:hidden">
          <Button asChild variant="ghost" size="sm" className="h-8 px-2 text-xs">
            <Link to="/">
              <ChevronLeft className="h-4 w-4" />
              返回 matter 列表
            </Link>
          </Button>
        </div>

        {/* ==== Header ==== */}
        <header className="mb-4 rounded-[1.3rem] border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <div className="mb-1 flex items-center gap-2 text-[11px] uppercase tracking-wide text-slate-400">
                <span>matter</span>
                <span>·</span>
                <span className="font-mono">{matter.id}</span>
              </div>
              <h1 className="text-xl font-semibold tracking-tight text-slate-900 sm:text-[22px]">
                {matter.title}
              </h1>
              <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
                <span>{timeline.length} 个文件</span>
                {matter.last_file_type && matter.last_summary && (
                  <>
                    <span>·</span>
                    <span className="max-w-[28rem] truncate">
                      最近 <span className="font-mono">{matter.last_file_type}</span> — {matter.last_summary}
                    </span>
                  </>
                )}
              </div>
            </div>
            <div className="flex shrink-0 flex-wrap items-center gap-2">
              <StatusBadge status={matter.current_status} />
              {matter_id && (
                <Button
                  variant="outline"
                  size="sm"
                  className="h-9 rounded-xl px-3 text-xs"
                  onClick={() => void toggleMatterFavorite(matter_id)}
                  title={threadMeta[matter_id]?.favorite ? "取消收藏" : "收藏"}
                >
                  <Star
                    className={cn(
                      "h-4 w-4",
                      threadMeta[matter_id]?.favorite ? "fill-amber-400 text-amber-500" : "text-slate-400",
                    )}
                  />
                  {threadMeta[matter_id]?.favorite ? "已收藏" : "收藏"}
                </Button>
              )}
              {canGenerateResult && (
                <Button
                  className="h-9 rounded-xl bg-purple-600 px-3 text-xs font-semibold text-white hover:bg-purple-700"
                  onClick={() => setResultOpen(true)}
                >
                  生成 Result
                </Button>
              )}
              {canGenerateInsight && (
                <Button
                  variant="outline"
                  className="h-9 rounded-xl px-3 text-xs font-semibold text-slate-700"
                  onClick={() => setCreateCtx({ kind: "page", type: "insight" })}
                >
                  生成 Insight
                </Button>
              )}
            </div>
          </div>

          <div className="mt-3 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
            <span className="font-semibold text-slate-700">状态语义：</span>
            {allowed}
          </div>

          {/* AI observe / next 占位条 */}
          <AIPlaceholderBar kind="observe" />
          <AIPlaceholderBar kind="next" />
        </header>

        {/* ==== 时间轴 ==== */}
        <section className="mb-4 rounded-[1.3rem] border border-slate-200 bg-white p-4 shadow-sm">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-[13px] font-semibold text-slate-800">
              时间轴 · {timeline.length}
            </h2>
            <span className="text-[11px] text-slate-500">
              按 created_at 升序 · 点圆点跳转到文件卡片
            </span>
          </div>
          <TimelineStrip items={timeline} highlight={highlight} onJump={onJump} />
        </section>

        {/* ==== 文件流 ==== */}
        <section className="space-y-3">
          {timeline.map((item, i) => (
            <FileCard
              key={item.file}
              item={item}
              index={i}
              matterStatus={matter.current_status}
              onCreate={(type: DocType, quote: string) =>
                setCreateCtx({ kind: "card", type, quote })
              }
              onAddComment={(body) => submitComment(item.file, body)}
              onJump={onJump}
              registerRef={(el) => {
                cardRefs.current[item.file] = el;
              }}
              highlighted={highlight === item.file}
            />
          ))}
          {matter.current_status === "reviewed" && (
            <div className="rounded-xl border border-slate-200 bg-slate-100/60 p-4 text-center text-xs text-slate-500">
              事项生命周期已收口（reviewed）。原则上不再新增文件。
            </div>
          )}
        </section>
      </div>

      <CreateFileDialog
        open={createCtx !== null}
        context={createCtx}
        matterStatus={matter.current_status}
        sessionPinyin={sessionPinyin}
        sessionName={sessionName || sessionPinyin}
        timeline={timeline}
        onClose={() => setCreateCtx(null)}
        onSubmit={submitNewFile}
      />

      <ResultConfirmDialog
        open={resultOpen}
        onCancel={() => setResultOpen(false)}
        onConfirm={submitResult}
      />
    </div>
  );
}

function AIPlaceholderBar({ kind }: { kind: "observe" | "next" }) {
  const cfg =
    kind === "observe"
      ? { label: "AI 观察 / 巡视", hint: "AI 会在此持续巡视事项进展（占位）" }
      : { label: "AI 下一步建议", hint: "AI 会在此基于上下文给出下一步建议（占位）" };
  return (
    <div className="mt-3 flex items-center gap-2 rounded-lg border border-dashed border-slate-300 bg-slate-50/50 px-3 py-2 text-[11px] text-slate-500">
      <span className="flex h-4 w-4 items-center justify-center rounded-full bg-slate-200 text-[10px] font-medium text-slate-600">
        <Sparkles className="h-2.5 w-2.5" />
      </span>
      <span className="font-medium text-slate-600">{cfg.label}</span>
      <span className="text-slate-400">· {cfg.hint}</span>
    </div>
  );
}
