import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { Bot, ChevronRight, Sparkles, Star, X } from "lucide-react";
import {
  appendMatterComment,
  appendMatterFile,
  appendMatterResult,
  fetchMatter,
  fetchMe,
  createDraft,
  deleteDraft,
  fetchDrafts,
  markMatterRead,
  streamAIChat,
  updateDraft,
  type Draft,
  type DocType,
  type MatterDetail as MatterDetailData,
  type NewFileIn,
} from "@/api";
import { Button } from "@/components/ui/button";
import { AIPane } from "@/components/AIPane";
import { StatusBadge } from "@/components/StatusBadge";
import { TimelineStrip } from "@/components/matter/TimelineStrip";
import { FileCard } from "@/components/matter/FileCard";
import {
  CreateFileForm,
  type FormSnapshot,
} from "@/components/matter/CreateFileDialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { shortFile, TYPE_VISUAL } from "@/components/matter/timeline-config";
import { STATUS_DESC } from "@/components/matter/timeline-config";
import { HomeWelcomePane } from "@/pages/HomeWelcomePane";
import { useDashboard } from "@/pages/Dashboard";
import { cn } from "@/lib/utils";

export function MatterDetailEmpty() {
  return <HomeWelcomePane />;
}

export function MatterDetailPane() {
  const { matter_id } = useParams<{ matter_id: string }>();
  const { reloadLists, toggleMatterFavorite, ai } = useDashboard();
  const [data, setData] = useState<MatterDetailData | null | undefined>(undefined);
  const [sessionOpenId, setSessionOpenId] = useState<string>("");
  const [sessionName, setSessionName] = useState<string>("");
  const [pendingCreate, setPendingCreate] = useState<
    { type: DocType; quote: string | null } | null
  >(null);
  const [matterDrafts, setMatterDrafts] = useState<Draft[]>([]);
  const [pendingDraftId, setPendingDraftId] = useState<string | null>(null);
  const [pendingInitial, setPendingInitial] = useState<Partial<FormSnapshot> | null>(
    null,
  );
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [resultConfirmOpen, setResultConfirmOpen] = useState(false);

  const draftFromPayload = (d: Draft): Partial<FormSnapshot> => {
    const mp = (d.matter_payload ?? {}) as Record<string, unknown>;
    const sc = mp.status_change as FormSnapshot["status_change"] | undefined;
    return {
      body: d.body_md,
      summary: typeof mp.summary === "string" ? mp.summary : "",
      owner: typeof mp.owner === "string" ? mp.owner : "",
      ownerDisplayName:
        typeof mp.owner_display === "string" ? mp.owner_display : "",
      refer: Array.isArray(mp.refer) ? (mp.refer as string[]) : [],
      verifications: Array.isArray(mp.verifications)
        ? (mp.verifications as FormSnapshot["verifications"])
        : [],
      status_change: sc,
    };
  };

  const findDraft = (
    drafts: Draft[],
    type: DocType,
    quote: string | null,
  ): Draft | null => {
    for (const d of drafts) {
      const mp = d.matter_payload;
      if (!mp) continue;
      const mpQuote = (mp as { quote?: unknown }).quote;
      const sameType = (mp as { doc_type?: unknown }).doc_type === type;
      const sameQuote =
        quote === null
          ? mpQuote == null || mpQuote === ""
          : mpQuote === quote;
      if (sameType && sameQuote) return d;
    }
    return null;
  };

  const openPending = (type: DocType, quote: string | null) => {
    if (pendingCreate && pendingCreate.type === type && pendingCreate.quote === quote) {
      setPendingCreate(null);
      setPendingDraftId(null);
      setPendingInitial(null);
      return;
    }
    const existing = findDraft(matterDrafts, type, quote);
    setPendingCreate({ type, quote });
    setPendingDraftId(existing?.id ?? null);
    setPendingInitial(existing ? draftFromPayload(existing) : null);
  };

  const requestCreate = (type: DocType, quote: string) => openPending(type, quote);
  const [highlight, setHighlight] = useState<string | null>(null);
  const [aiOpen, setAiOpen] = useState(false);
  const [pendingAIOrigin, setPendingAIOrigin] = useState<string | null>(null);
  const [aiFillToken, setAiFillToken] = useState(0);
  const cardRefs = useRef<Record<string, HTMLDivElement | null>>({});

  const openAIForFile = (file: string) => {
    setPendingAIOrigin(file);
    setAiOpen(true);
  };

  // Keep reloadLists in a ref so callbacks/effects depending on matter_id
  // don't re-run when the Dashboard re-renders and hands down a new reference.
  const reloadListsRef = useRef(reloadLists);
  useEffect(() => {
    reloadListsRef.current = reloadLists;
  }, [reloadLists]);

  const load = useCallback(() => {
    if (!matter_id) return;
    fetchMatter(matter_id)
      .then(setData)
      .catch((e) => {
        toast.error(e instanceof Error ? e.message : String(e));
        setData(null);
      });
    fetchDrafts()
      .then((drafts) =>
        setMatterDrafts(
          drafts.filter(
            (d) =>
              d.type === "reply" &&
              d.thread_key === matter_id &&
              d.matter_payload != null,
          ),
        ),
      )
      .catch(() => setMatterDrafts([]));
  }, [matter_id]);

  useEffect(() => {
    load();
  }, [load]);

  // Mark read once per opened matter, then refresh sidebar unread badges.
  // Isolated from `load` so the reloadLists identity churn doesn't loop.
  useEffect(() => {
    if (!matter_id) return;
    markMatterRead(matter_id)
      .then(() => reloadListsRef.current())
      .catch(() => {});
  }, [matter_id]);

  // 兜底：SSE 推送在移动端浏览器 / 飞书 WebView 切到后台时会被挂起，
  // 页面回到前台 / bfcache 恢复 / tab 重新聚焦时主动补拉一次，保证最终一致。
  useEffect(() => {
    if (!matter_id) return;
    const lastRefreshRef = { current: 0 };
    const refresh = () => {
      if (document.visibilityState !== "visible") return;
      const now = Date.now();
      if (now - lastRefreshRef.current < 800) return;
      lastRefreshRef.current = now;
      load();
      markMatterRead(matter_id)
        .then(() => reloadListsRef.current())
        .catch(() => {});
    };
    document.addEventListener("visibilitychange", refresh);
    window.addEventListener("pageshow", refresh);
    window.addEventListener("focus", refresh);
    return () => {
      document.removeEventListener("visibilitychange", refresh);
      window.removeEventListener("pageshow", refresh);
      window.removeEventListener("focus", refresh);
    };
  }, [matter_id, load]);

  useEffect(() => {
    fetchMe()
      .then((me) => {
        setSessionOpenId(me?.open_id ?? "");
        setSessionName(me?.name ?? "");
      })
      .catch(() => {
        setSessionOpenId("");
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

  const generateSummaryViaChat = async (draft: {
    type: DocType;
    body: string;
    quote: string | null;
  }): Promise<string> => {
    const replyTarget =
      draft.quote ??
      (timeline.length > 0 ? timeline[timeline.length - 1].file : null);
    if (!replyTarget) {
      throw new Error("matter 暂无文件可作为上下文，无法生成 summary");
    }
    const userMsg = [
      `请为下面这篇新增的 ${draft.type} 文件生成一句不超过 80 字的中文 summary。`,
      `要求：`,
      `- 直接输出这一句话本身，不要加引号，也不要任何前后解释。`,
      `- 用最精简的语言概括这篇文件推进 / 判断 / 结论了什么。`,
      ``,
      `新文件正文：`,
      "```",
      draft.body,
      "```",
    ].join("\n");

    let accumulated = "";
    for await (const delta of streamAIChat(
      matter.category ?? "",
      matter.id,
      [{ role: "user", content: userMsg }],
      replyTarget,
      [],
    )) {
      accumulated += delta;
    }
    return accumulated;
  };

  const buildMatterPayload = (
    type: DocType,
    quote: string | null,
    snap: FormSnapshot,
  ): Record<string, unknown> => {
    const payload: Record<string, unknown> = {
      doc_type: type,
      summary: snap.summary,
    };
    if (quote) payload.quote = quote;
    if (snap.owner) payload.owner = snap.owner;
    if (snap.ownerDisplayName) payload.owner_display = snap.ownerDisplayName;
    if (snap.refer.length > 0) payload.refer = snap.refer;
    if (snap.verifications.length > 0) payload.verifications = snap.verifications;
    if (snap.status_change) payload.status_change = snap.status_change;
    if (snap.outcome) payload.outcome = snap.outcome;
    return payload;
  };

  const saveDraftFromForm = async (snap: FormSnapshot) => {
    if (!matter_id || !pendingCreate) return;
    const matter_payload = buildMatterPayload(
      pendingCreate.type,
      pendingCreate.quote,
      snap,
    );
    try {
      if (pendingDraftId) {
        const d = await updateDraft(pendingDraftId, {
          body_md: snap.body,
          matter_payload,
        });
        setMatterDrafts((prev) =>
          prev.map((x) => (x.id === d.id ? d : x)),
        );
      } else {
        const d = await createDraft({
          type: "reply",
          thread_key: matter_id,
          body_md: snap.body,
          matter_payload,
        });
        setPendingDraftId(d.id);
        setMatterDrafts((prev) => [...prev, d]);
      }
    } catch (e) {
      console.warn("保存草稿失败", e);
    }
  };

  const handleConfirmDelete = async () => {
    if (pendingDraftId) {
      try {
        await deleteDraft(pendingDraftId);
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "删除草稿失败");
        setConfirmDeleteOpen(false);
        return;
      }
      setMatterDrafts((prev) => prev.filter((d) => d.id !== pendingDraftId));
    }
    setPendingDraftId(null);
    setPendingInitial(null);
    setPendingCreate(null);
    setConfirmDeleteOpen(false);
  };

  const submitNewFile = async (body: NewFileIn): Promise<boolean> => {
    if (!matter_id) return false;
    try {
      if (body.type === "result") {
        await appendMatterResult(matter_id, {
          summary: body.summary,
          body: body.body,
          outcome: body.outcome ?? "finished",
        });
      } else {
        await appendMatterFile(matter_id, body);
      }
      toast.success(
        body.status_change
          ? `已发布 ${body.type} · 事项 ${body.status_change.from} → ${body.status_change.to}`
          : `已发布 ${body.type}`,
      );
      if (pendingDraftId) {
        const idToClear = pendingDraftId;
        deleteDraft(idToClear).catch(() => {});
        setMatterDrafts((prev) => prev.filter((d) => d.id !== idToClear));
        setPendingDraftId(null);
        setPendingInitial(null);
      }
      await afterWrite();
      return true;
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
      return false;
    }
  };

  const handleUseDraftAsReply = async (
    content: string,
    replyTo: string,
  ): Promise<boolean> => {
    if (!matter_id || !pendingCreate) return false;
    const nextInitial: Partial<FormSnapshot> = {
      ...(pendingInitial ?? {}),
      body: content,
    };
    const matter_payload = buildMatterPayload(
      pendingCreate.type,
      pendingCreate.quote,
      {
        summary: nextInitial.summary ?? "",
        body: content,
        owner: nextInitial.owner ?? "",
        ownerDisplayName: nextInitial.ownerDisplayName ?? "",
        refer: nextInitial.refer ?? [],
        verifications: nextInitial.verifications ?? [],
        status_change: nextInitial.status_change,
        outcome: nextInitial.outcome,
      },
    );
    try {
      if (pendingDraftId) {
        const d = await updateDraft(pendingDraftId, {
          body_md: content,
          matter_payload,
          reply_to: replyTo || null,
        });
        setMatterDrafts((prev) => prev.map((x) => (x.id === d.id ? d : x)));
      } else {
        const d = await createDraft({
          type: "reply",
          thread_key: matter_id,
          body_md: content,
          matter_payload,
          reply_to: replyTo || null,
        });
        setPendingDraftId(d.id);
        setMatterDrafts((prev) => [...prev, d]);
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "保存 AI 草稿失败");
      return false;
    }
    setPendingInitial(nextInitial);
    setAiFillToken((v) => v + 1);
    return true;
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

  const threadKey = matter.category ? `${matter.category}/${matter.id}` : matter.id;
  const aiThreadState = ai.getThreadState(threadKey);
  const aiOriginItem = aiThreadState.replyTarget
    ? timeline.find((t) => t.file === aiThreadState.replyTarget) ?? null
    : null;

  return (
    <div className="relative flex h-full min-h-0">
      {/* 左：主内容 */}
      <div className="min-w-0 flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-5xl px-3 py-3 sm:px-5 sm:py-5">
        {/* 顶部 bar：面包屑 + AI 总结 */}
        <div className="mb-4 flex items-center justify-between gap-3">
          <nav className="flex min-w-0 items-center gap-1.5 text-sm text-slate-500">
            <Link to="/" className="shrink-0 hover:text-slate-800">事项</Link>
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-slate-300" />
            {matter.category && (
              <>
                <span className="shrink-0 truncate text-slate-600">{matter.category}</span>
                <ChevronRight className="h-3.5 w-3.5 shrink-0 text-slate-300" />
              </>
            )}
            <span className="truncate text-slate-800">{matter.title}</span>
          </nav>
          <Button
            type="button"
            variant={aiOpen ? "secondary" : "default"}
            size="sm"
            className={cn(
              "h-9 shrink-0 rounded-xl px-3.5 text-xs font-semibold",
              !aiOpen && "bg-blue-600 text-white shadow-[0_8px_22px_rgba(37,99,235,0.24)] hover:bg-blue-700",
            )}
            onClick={() => setAiOpen((o) => !o)}
          >
            <Sparkles className="mr-1.5 h-3.5 w-3.5" />
            AI 总结
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
                  onClick={() => {
                    // optimistic flip locally (Dashboard does the authoritative optimistic on the list)
                    setData((prev) =>
                      prev
                        ? { ...prev, matter: { ...prev.matter, favorite: !prev.matter.favorite } }
                        : prev,
                    );
                    void toggleMatterFavorite(matter_id).catch(() => {
                      setData((prev) =>
                        prev
                          ? {
                              ...prev,
                              matter: { ...prev.matter, favorite: !prev.matter.favorite },
                            }
                          : prev,
                      );
                    });
                  }}
                  title={matter.favorite ? "取消收藏" : "收藏"}
                >
                  <Star
                    className={cn(
                      "h-4 w-4",
                      matter.favorite ? "fill-amber-400 text-amber-500" : "text-slate-400",
                    )}
                  />
                  {matter.favorite ? "已收藏" : "收藏"}
                </Button>
              )}
              {canGenerateResult && (
                <Button
                  className="h-9 rounded-xl bg-purple-600 px-3 text-xs font-semibold text-white hover:bg-purple-700"
                  onClick={() => setResultConfirmOpen(true)}
                >
                  生成 Result
                </Button>
              )}
              {canGenerateInsight && (
                <Button
                  variant="outline"
                  className="h-9 rounded-xl px-3 text-xs font-semibold text-slate-700"
                  onClick={() => openPending("insight", null)}
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
              activeType={
                pendingCreate && pendingCreate.quote === item.file
                  ? pendingCreate.type
                  : null
              }
              onCreate={requestCreate}
              onAddComment={(body) => submitComment(item.file, body)}
              onJump={onJump}
              registerRef={(el) => {
                cardRefs.current[item.file] = el;
              }}
              highlighted={highlight === item.file}
            />
          ))}
          {pendingCreate && (
            <article
              className={cn(
                "rounded-2xl border border-slate-200 border-l-[6px] [border-left-style:dashed] bg-white p-4 shadow-sm sm:p-5",
                TYPE_VISUAL[pendingCreate.type].side,
              )}
            >
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <span
                  className={cn(
                    "inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ring-1",
                    TYPE_VISUAL[pendingCreate.type].chip,
                  )}
                >
                  {TYPE_VISUAL[pendingCreate.type].label}
                </span>
                <span className="text-[11px] text-slate-500">
                  {pendingCreate.quote ? (
                    <>
                      新增 · 基于{" "}
                      <span className="font-mono text-slate-700">
                        {shortFile(pendingCreate.quote)}
                      </span>
                    </>
                  ) : (
                    <>页面级 · 无 quote</>
                  )}
                </span>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="ml-auto h-7 rounded-lg border-blue-200 px-2.5 text-[11px] font-semibold text-blue-700 hover:bg-blue-50"
                  onClick={() => {
                    if (pendingCreate.quote) {
                      openAIForFile(pendingCreate.quote);
                    } else {
                      setAiOpen(true);
                    }
                  }}
                  title="打开 AI 助手"
                >
                  <Sparkles className="mr-1 h-3 w-3" />
                  AI 助手
                </Button>
              </div>
              <CreateFileForm
                key={`${pendingCreate.quote ?? "__page__"}:${pendingCreate.type}:${aiFillToken}`}
                context={
                  pendingCreate.quote
                    ? {
                        kind: "card",
                        type: pendingCreate.type,
                        quote: pendingCreate.quote,
                      }
                    : {
                        kind: "page",
                        type: pendingCreate.type as "insight" | "result",
                      }
                }
                matterStatus={matter.current_status}
                sessionOpenId={sessionOpenId}
                sessionName={sessionName || sessionOpenId}
                timeline={timeline}
                initial={pendingInitial ?? undefined}
                onSubmit={submitNewFile}
                onSuccess={() => {
                  setPendingCreate(null);
                  setPendingDraftId(null);
                  setPendingInitial(null);
                }}
                onGenerateSummary={generateSummaryViaChat}
                onFormBlur={saveDraftFromForm}
                onDeleteDraft={
                  pendingDraftId ? () => setConfirmDeleteOpen(true) : undefined
                }
              />
            </article>
          )}
          {matter.current_status === "reviewed" && (
            <div className="rounded-xl border border-slate-200 bg-slate-100/60 p-4 text-center text-xs text-slate-500">
              事项生命周期已收口（reviewed）。原则上不再新增文件。
            </div>
          )}
        </section>
      </div>
      </div>

      {/* 右：AI 助手（桌面端拆分布局） */}
      {aiOpen && (
        <aside className="hidden w-[480px] shrink-0 flex-col border-l border-slate-200 bg-white lg:flex">
          <div className="flex items-center justify-between border-b border-slate-200/80 px-4 py-3">
            <div className="flex items-center gap-2 text-sm font-medium text-slate-800">
              <Bot className="h-4 w-4 text-blue-600" />
              AI 助手
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-8 w-8 rounded-lg text-slate-500 hover:bg-slate-100"
              onClick={() => setAiOpen(false)}
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
          {aiOriginItem && (() => {
            const oCfg = TYPE_VISUAL[aiOriginItem.type];
            return (
              <div className="border-b border-slate-200/80 bg-slate-50/60 px-4 py-3">
                <div className="mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
                  起点帖子
                </div>
                <button
                  type="button"
                  onClick={() => onJump(aiOriginItem.file)}
                  className={cn(
                    "block w-full rounded-lg border border-slate-200 border-l-[4px] bg-white p-2.5 text-left shadow-sm transition-colors hover:border-blue-300",
                    oCfg.side,
                  )}
                  title="跳转到该文件"
                >
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span
                      className={cn(
                        "inline-flex items-center rounded-md px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ring-1",
                        oCfg.chip,
                      )}
                    >
                      {oCfg.label}
                    </span>
                    <span className="font-mono text-[11px] text-slate-700">
                      {shortFile(aiOriginItem.file)}
                    </span>
                    <span className="text-[10px] text-slate-400">· {aiOriginItem.creator}</span>
                  </div>
                  <p className="mt-1 line-clamp-2 text-[12px] text-slate-700">{aiOriginItem.summary}</p>
                </button>
              </div>
            );
          })()}
          <div className="min-h-0 flex-1 p-4">
            <AIPane
              category={matter.category ?? ""}
              slug={matter.id}
              threadKey={threadKey}
              threadTitle={matter.title}
              onUseDraftAsReply={handleUseDraftAsReply}
              hasReplyDraft={!!pendingDraftId}
              pendingReplyTarget={pendingAIOrigin}
              onPendingReplyTargetConsumed={() => setPendingAIOrigin(null)}
            />
          </div>
        </aside>
      )}

      <Dialog open={resultConfirmOpen} onOpenChange={setResultConfirmOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>⚠ 生成 Result 是事项正式收口</DialogTitle>
            <DialogDescription className="text-xs">
              发布 Result 后：
            </DialogDescription>
          </DialogHeader>
          <ul className="list-disc space-y-0.5 pl-5 text-xs text-slate-600">
            <li>
              matter 状态变更为 <span className="font-mono">finished</span> 或{" "}
              <span className="font-mono">cancelled</span>
            </li>
            <li>不再允许新增 act / verify / 执行性 think</li>
            <li>
              只剩 <span className="font-mono">insight</span> 可追加
            </li>
          </ul>
          <DialogFooter>
            <Button variant="outline" onClick={() => setResultConfirmOpen(false)}>
              取消
            </Button>
            <Button
              className="bg-purple-600 text-white hover:bg-purple-700"
              onClick={() => {
                setResultConfirmOpen(false);
                openPending("result", null);
              }}
            >
              继续生成
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={confirmDeleteOpen} onOpenChange={setConfirmDeleteOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>删除草稿？</DialogTitle>
            <DialogDescription>
              删除后这份未发布的草稿内容将丢失，不可恢复。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmDeleteOpen(false)}>
              取消
            </Button>
            <Button
              className="bg-red-600 text-white hover:bg-red-700"
              onClick={() => void handleConfirmDelete()}
            >
              删除草稿
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
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
