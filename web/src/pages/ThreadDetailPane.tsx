import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { AtSign, Bot, ChevronLeft, FileText, Maximize2, Minimize2, Sparkles, Star, X } from "lucide-react";
import {
  addMention,
  changeThreadStatus,
  createDraft,
  deleteDraft,
  fetchDrafts,
  fetchThread,
  fetchWorkspaceMirror,
  markThreadRead,
  publishDraft,
  setThreadFavorite,
  updateDraft,
  type MentionBlock,
  type MentionEntry,
  type Post,
  type ThreadDetail as ThreadDetailData,
  type WorkspaceMirrorConfig,
} from "@/api";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { StatusControl } from "@/components/StatusControl";
import { MentionField, emptyMention, isMentionValid } from "@/components/MentionField";
import { AIPane } from "@/components/AIPane";
import { formatSaveStatus, useDraftAutosave } from "@/hooks/useDraftAutosave";
import { formatFullDateTime, relativeTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import { useDashboard } from "@/pages/Dashboard";
import { HomeWelcomePane } from "@/pages/HomeWelcomePane";

const COLLAPSE_HEIGHT = 208;
const MOBILE_AI_TOP_OFFSET = 64;
const MOBILE_AI_PEEK_HEIGHT = 64;

function postAnchorId(filename: string): string {
  const base = filename.endsWith(".md") ? filename.slice(0, -3) : filename;
  return `post-${base}`;
}

export function ThreadDetailPane() {
  const { category, slug } = useParams<{ category: string; slug: string }>();
  const [searchParams] = useSearchParams();
  const { reloadLists, ai } = useDashboard();
  const [data, setData] = useState<ThreadDetailData | null | undefined>(undefined);
  const [aiOpen, setAiOpen] = useState(false);
  const [aiPaneWidth, setAiPaneWidth] = useState(520);
  const [mobileAiMode, setMobileAiMode] = useState<"closed" | "peek" | "full">("closed");
  const [mobileViewportHeight, setMobileViewportHeight] = useState(
    () => (typeof window === "undefined" ? 0 : Math.round(window.visualViewport?.height ?? window.innerHeight)),
  );
  const [mobileKeyboardInset, setMobileKeyboardInset] = useState(0);
  const [mobileAiDragHeight, setMobileAiDragHeight] = useState<number | null>(null);
  const [desktopFloatFrame, setDesktopFloatFrame] = useState({ top: 16, height: 720 });
  const [aiPendingReplyTarget, setAiPendingReplyTarget] = useState<string | null>(null);
  const [replyBody, setReplyBody] = useState("");
  const [replyMentions, setReplyMentions] = useState<MentionBlock>(emptyMention());
  const [replyDraftId, setReplyDraftId] = useState<string | null>(null);
  const [replyTo, setReplyTo] = useState<string | null>(null);
  const [replyReferences, setReplyReferences] = useState<string[]>([]);
  const [favoriteSaving, setFavoriteSaving] = useState(false);
  const [workspaceMirror, setWorkspaceMirror] = useState<WorkspaceMirrorConfig | null>(null);
  const composerRef = useRef<HTMLDivElement>(null);
  const detailLayoutRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const mobileAiDragRef = useRef<{ pointerId: number; startY: number; startHeight: number } | null>(null);

  const hasDraft = replyBody.trim().length > 0;
  const isDesktopViewport = () => typeof window !== "undefined" && window.innerWidth >= 1024;
  const desktopFloatGap = 16;
  const mobileAiMaxHeight = Math.max(mobileViewportHeight - MOBILE_AI_TOP_OFFSET, MOBILE_AI_PEEK_HEIGHT);
  const mobileAiRestHeight = mobileAiMode === "full" ? mobileAiMaxHeight : MOBILE_AI_PEEK_HEIGHT;
  const mobileAiHeight = mobileAiDragHeight ?? mobileAiRestHeight;
  const mobileAiShowsBody =
    mobileAiMode === "full" || (mobileAiDragHeight !== null && mobileAiHeight > MOBILE_AI_PEEK_HEIGHT + 24);
  const openMobileAi = () => setMobileAiMode("full");
  const minimizeMobileAi = () => {
    setMobileAiDragHeight(null);
    setMobileAiMode("peek");
  };
  const maximizeMobileAi = () => {
    setMobileAiDragHeight(null);
    setMobileAiMode("full");
  };

  const startAIPaneResize = (event: React.MouseEvent<HTMLDivElement>) => {
    event.preventDefault();
    const container = scrollContainerRef.current;
    if (!container) return;
    const rect = container.getBoundingClientRect();
    const minWidth = 420;
    const contentMinWidth = 620;
    const maxWidth = Math.min(920, Math.max(minWidth, rect.width - contentMinWidth - desktopFloatGap * 2));

    const onMove = (moveEvent: MouseEvent) => {
      const next = Math.min(
        Math.max(rect.right - moveEvent.clientX - desktopFloatGap, minWidth),
        maxWidth,
      );
      setAiPaneWidth(next);
      if (!aiOpen) setAiOpen(true);
    };

    const onUp = () => {
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };

    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  const load = () => {
    if (!category || !slug) return;
    fetchThread(category, slug)
      .then((d) => {
        setData(d);
        markThreadRead(category, slug).then(reloadLists).catch(() => {});
      })
      .catch((e) => {
        toast.error(e instanceof Error ? e.message : String(e));
        setData(null);
      });
  };

  useEffect(load, [category, slug]);

  useEffect(() => {
    fetchWorkspaceMirror()
      .then(setWorkspaceMirror)
      .catch(() => setWorkspaceMirror(null));
  }, []);

  // W1: feishu mention 卡片里 "查看该帖子" 按钮深链带 ?post=<anchor>#post-<anchor>，
  // 这里在数据加载完成后读 URL 参数并滚动到对应 post 元素。下一帧再滚，
  // 保证 <div id="post-..."> 已经 mount。
  useEffect(() => {
    if (!data) return;
    const target = searchParams.get("post");
    if (!target) return;
    const raf = requestAnimationFrame(() => {
      const el = document.getElementById(`post-${target}`);
      if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    return () => cancelAnimationFrame(raf);
  }, [data, searchParams]);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const updateFrame = () => {
      const el = scrollContainerRef.current;
      if (!el || !isDesktopViewport()) return;
      const top = el.scrollTop + desktopFloatGap;
      const height = Math.max(el.clientHeight - desktopFloatGap * 2, 520);
      setDesktopFloatFrame({ top, height });
    };

    updateFrame();
    const resizeObserver = scrollContainerRef.current
      ? new ResizeObserver(() => updateFrame())
      : null;
    if (scrollContainerRef.current && resizeObserver) {
      resizeObserver.observe(scrollContainerRef.current);
    }
    window.addEventListener("resize", updateFrame);
    return () => {
      window.removeEventListener("resize", updateFrame);
      resizeObserver?.disconnect();
    };
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const updateViewportHeight = () => {
      const viewport = window.visualViewport;
      const next = viewport?.height ?? window.innerHeight;
      const inset = viewport
        ? Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop)
        : 0;
      setMobileViewportHeight(Math.round(next));
      setMobileKeyboardInset(Math.round(inset));
    };

    updateViewportHeight();
    window.addEventListener("resize", updateViewportHeight);
    window.visualViewport?.addEventListener("resize", updateViewportHeight);
    return () => {
      window.removeEventListener("resize", updateViewportHeight);
      window.visualViewport?.removeEventListener("resize", updateViewportHeight);
    };
  }, []);

  useEffect(() => {
    setReplyBody("");
    setReplyMentions(emptyMention());
    setReplyDraftId(null);
    setReplyTo(null);
    setReplyReferences([]);
    setAiPendingReplyTarget(null);
    setAiOpen(false);
    setMobileAiMode("closed");
    if (!category || !slug) return;
    const threadKey = `${category}/${slug}`;
    fetchDrafts()
      .then((items) => {
        const existing = items.find((d) => d.type === "reply" && d.thread_key === threadKey);
        if (!existing || !existing.body_md.trim()) return;
        setReplyBody(existing.body_md);
        setReplyDraftId(existing.id);
        if (existing.mentions) setReplyMentions(existing.mentions);
        if (existing.reply_to) setReplyTo(existing.reply_to);
        setReplyReferences(existing.references ?? []);
      })
      .catch(() => {});
  }, [category, slug]);

  useEffect(() => {
    if (mobileAiMode === "closed") {
      setMobileAiDragHeight(null);
    }
  }, [mobileAiMode]);

  useEffect(() => {
    if (mobileAiDragHeight === null) return;
    setMobileAiDragHeight((current) => {
      if (current === null) return null;
      return Math.min(Math.max(current, MOBILE_AI_PEEK_HEIGHT), mobileAiMaxHeight);
    });
  }, [mobileAiDragHeight, mobileAiMaxHeight]);

  const openAIReply = (post: Post) => {
    if (!category || !slug) return;
    setAiPendingReplyTarget(`${category}/${slug}/${post.filename}`);
    if (isDesktopViewport()) {
      setAiOpen(true);
      return;
    }
    openMobileAi();
  };

  const openThreadAIAssistant = () => {
    if (!category || !slug || data === undefined || data === null || data.posts.length === 0) return;
    const [firstPost] = data.posts;
    ai.setReplyTarget(category, slug, threadKey, `${category}/${slug}/${firstPost.filename}`);
    ai.setInput(
      threadKey,
      [
        "请按文件的时间顺序完整阅读这个主题中的全部文件（可调用 read_thread_index 查目录，再逐个 read_post）。",
        "先逐个概括每个文件分别讲了什么、推进了什么、回应了什么。",
        "然后基于时间线总结这些文件之间最主要的关系，包括：谁在回应谁、哪些内容是在延续、补充、反驳或收敛前面的讨论。",
        "最后用清晰的结构总结这个主题的整体讨论逻辑走线，以及目前形成了哪些结论、分歧和待解决问题。",
      ].join("\n"),
    );
    setAiPendingReplyTarget(null);
    if (isDesktopViewport()) {
      setAiOpen(true);
      return;
    }
    maximizeMobileAi();
  };

  const startMobileAiDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    if (isDesktopViewport() || mobileAiMode === "closed") return;
    mobileAiDragRef.current = {
      pointerId: event.pointerId,
      startY: event.clientY,
      startHeight: mobileAiHeight,
    };
    setMobileAiDragHeight(mobileAiHeight);
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const moveMobileAiDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    const drag = mobileAiDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const deltaY = event.clientY - drag.startY;
    const nextHeight = Math.min(
      Math.max(drag.startHeight - deltaY, MOBILE_AI_PEEK_HEIGHT),
      mobileAiMaxHeight,
    );
    setMobileAiDragHeight(nextHeight);
  };

  const endMobileAiDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    const drag = mobileAiDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const finalHeight = mobileAiDragHeight ?? mobileAiHeight;
    const threshold = MOBILE_AI_PEEK_HEIGHT + (mobileAiMaxHeight - MOBILE_AI_PEEK_HEIGHT) / 2;
    setMobileAiDragHeight(null);
    setMobileAiMode(finalHeight >= threshold ? "full" : "peek");
    mobileAiDragRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  const cancelMobileAiDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!mobileAiDragRef.current || mobileAiDragRef.current.pointerId !== event.pointerId) return;
    setMobileAiDragHeight(null);
    mobileAiDragRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  const onUseDraftAsReply = async (
    content: string,
    aiReplyTo: string,
  ): Promise<boolean> => {
    if (!category || !slug) return false;
    const threadKey = `${category}/${slug}`;
    const replyToFilename = aiReplyTo.startsWith(`${category}/${slug}/`)
      ? aiReplyTo.slice(`${category}/${slug}/`.length)
      : aiReplyTo;

    let nextDraftId = replyDraftId;
    try {
      if (replyDraftId) {
        await updateDraft(replyDraftId, {
          body_md: content,
          reply_to: replyToFilename,
          references: replyReferences,
        });
      } else {
        const d = await createDraft({
          type: "reply",
          body_md: content,
          thread_key: threadKey,
          reply_to: replyToFilename,
          references: replyReferences,
        });
        nextDraftId = d.id;
      }
    } catch {
      return false;
    }

    if (nextDraftId !== replyDraftId) setReplyDraftId(nextDraftId);
    setReplyBody(content);
    setReplyTo(replyToFilename);
    if (isDesktopViewport()) {
      setAiOpen(true);
    } else {
      setMobileAiMode("full");
    }
    return true;
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
        Thread not found
      </div>
    );
  }

  const threadKey = `${category}/${slug}`;
  const favorite = data.meta.favorite;
  const proposalPost = data.posts.find((post) => ((post.frontmatter.type as string) ?? "") === "proposal")
    ?? data.posts[0]
    ?? null;
  const replyPosts = proposalPost
    ? data.posts.filter((post) => post.filename !== proposalPost.filename)
    : data.posts;

  const replyFormProps = {
    category: category!,
    slug: slug!,
    body: replyBody,
    setBody: setReplyBody,
    mentions: replyMentions,
    setMentions: setReplyMentions,
    draftId: replyDraftId,
    setDraftId: setReplyDraftId,
    replyTo,
    setReplyTo,
    references: replyReferences,
    setReferences: setReplyReferences,
    onPosted: () => {
      setReplyBody("");
      setReplyMentions(emptyMention());
      setReplyDraftId(null);
      setReplyTo(null);
      setReplyReferences([]);
      setMobileAiMode("closed");
      load();
      reloadLists();
    },
  };

  return (
    <div
      ref={scrollContainerRef}
      className="relative h-full overflow-y-auto"
      onScroll={() => {
        if (isDesktopViewport()) {
          const el = scrollContainerRef.current;
          if (el) {
            setDesktopFloatFrame({
              top: el.scrollTop + desktopFloatGap,
              height: Math.max(el.clientHeight - desktopFloatGap * 2, 520),
            });
          }
        }
      }}
    >
      <div
        className={cn(
          "px-3 py-3 sm:px-5 sm:py-5",
          aiOpen
            ? "mx-0 max-w-none lg:pr-4"
            : "mx-auto max-w-[72rem]",
        )}
        style={aiOpen && isDesktopViewport() ? { paddingRight: aiPaneWidth + desktopFloatGap * 2 } : undefined}
      >
        <div className="mb-3 lg:hidden">
          <Button asChild variant="ghost" size="sm" className="h-8 px-2 text-xs">
            <Link to="/">
              <ChevronLeft className="h-4 w-4" />
              返回讨论列表
            </Link>
          </Button>
        </div>

        <div ref={detailLayoutRef} className="lg:flex lg:items-start lg:gap-4">
          <div className="min-w-0 flex-1 space-y-5">
            <div className="flex items-center justify-between gap-3 px-1">
              <div className="min-w-0">
                <div className="hidden min-w-0 items-center gap-2 text-xs text-slate-500 lg:flex">
                  <Link to="/" className="hover:text-slate-800">讨论</Link>
                  <span>/</span>
                  <span>{category}</span>
                  <span>/</span>
                  <span className="truncate text-slate-700">{data.meta.title}</span>
                </div>
                <div className="lg:hidden">
                  <div className="truncate text-sm font-semibold text-slate-900">{data.meta.title}</div>
                  <div className="mt-0.5 text-[11px] text-slate-500">{category}</div>
                </div>
              </div>
              <Button
                type="button"
                variant="default"
                size="sm"
                className="h-9 shrink-0 rounded-xl bg-blue-600 px-3.5 text-xs font-semibold text-white shadow-[0_8px_22px_rgba(37,99,235,0.24)] hover:bg-blue-700"
                onClick={openThreadAIAssistant}
              >
                <Sparkles className="mr-1.5 h-3.5 w-3.5" />
                AI 总结
              </Button>
            </div>

            {proposalPost && (
              <div id={postAnchorId(proposalPost.filename)} className="scroll-mt-4">
                <ProposalHeroCard
                  post={proposalPost}
                  category={category!}
                  slug={slug!}
                  threadStatus={data.meta.status}
                  postCount={data.meta.post_count}
                  favorite={favorite}
                  favoriteSaving={favoriteSaving}
                  githubFileUrl={buildGitHubFileUrl(
                    workspaceMirror?.repo_url ?? null,
                    workspaceMirror?.head ?? workspaceMirror?.branch ?? null,
                    category!,
                    slug!,
                    proposalPost.filename,
                  )}
                  onToggleFavorite={async () => {
                    if (!category || !slug) return;
                    setFavoriteSaving(true);
                    try {
                      const next = !favorite;
                      await setThreadFavorite(category, slug, next);
                      setData((current) => current ? {
                        ...current,
                        meta: { ...current.meta, favorite: next },
                      } : current);
                      await reloadLists();
                    } catch (e) {
                      toast.error(e instanceof Error ? e.message : String(e));
                    } finally {
                      setFavoriteSaving(false);
                    }
                  }}
                  onStatusChange={async (to, reason) => {
                    if (!category || !slug) return;
                    await changeThreadStatus(category, slug, to, reason);
                    load();
                    reloadLists();
                  }}
                  onAIReply={() => openAIReply(proposalPost)}
                  onMentioned={load}
                />
              </div>
            )}

            <section className="space-y-3">
              <div className="flex items-center justify-between px-1">
                <div className="text-[15px] font-semibold text-slate-800">
                  回复 · {replyPosts.length}
                </div>
                <div className="text-xs text-slate-500">
                  按时间顺序显示
                </div>
              </div>

              {replyPosts.length > 0 ? (
                replyPosts.map((post, index) => (
                  <div
                    key={post.filename}
                    id={postAnchorId(post.filename)}
                    className="scroll-mt-4"
                  >
                    <ReplyPostCard
                      post={post}
                      postNumber={proposalPost ? index + 2 : index + 1}
                      category={category!}
                      slug={slug!}
                      githubFileUrl={buildGitHubFileUrl(
                        workspaceMirror?.repo_url ?? null,
                        workspaceMirror?.head ?? workspaceMirror?.branch ?? null,
                        category!,
                        slug!,
                        post.filename,
                      )}
                      onAIReply={() => openAIReply(post)}
                      onMentioned={load}
                    />
                  </div>
                ))
              ) : (
                <div className="rounded-2xl border border-dashed border-slate-200 bg-white/50 px-5 py-6 text-sm text-slate-500">
                  还没有回复。你可以直接在下面写回复，或者切到 AI 助手先整理思路。
                </div>
              )}
            </section>

            <section
              ref={composerRef}
              className={mobileAiMode !== "closed"
                ? "paper-panel overflow-hidden rounded-[1.3rem] border border-blue-200/90 shadow-[0_10px_30px_rgba(37,99,235,0.08)]"
                : "paper-panel overflow-hidden rounded-[1.3rem] border"}
            >
              <div className="flex items-center gap-1 border-b border-slate-200/80 px-4 py-3">
                <ComposerTab
                  label="回复"
                  active={mobileAiMode === "closed"}
                  onClick={() => setMobileAiMode("closed")}
                />
                <ComposerTab
                  label="AI 助手"
                  active={mobileAiMode !== "closed"}
                  className="lg:hidden"
                  onClick={() => {
                    if (!aiPendingReplyTarget && data.posts.length > 0) {
                      const last = data.posts[data.posts.length - 1];
                      setAiPendingReplyTarget(`${category}/${slug}/${last.filename}`);
                    }
                    setMobileAiMode((current) => (current === "closed" ? "full" : "closed"));
                  }}
                />
                <div className="ml-auto hidden items-center gap-2 text-xs text-slate-500 sm:flex">
                  <>
                    <FileText className="h-3.5 w-3.5" />
                    {replyTo ? `回复到 ${replyTo}` : "直接补充新的回复"}
                  </>
                </div>
              </div>

              <div className="p-4 sm:p-5">
                <ReplyForm {...replyFormProps} />
              </div>
            </section>
          </div>

          <aside className="hidden lg:block lg:self-start lg:shrink-0" />
        </div>
      </div>

      {aiOpen && isDesktopViewport() && (
        <>
          <div
            className="group absolute z-40 hidden w-6 cursor-col-resize lg:block"
            style={{
              right: aiPaneWidth + desktopFloatGap - 3,
              top: desktopFloatFrame.top,
              height: desktopFloatFrame.height,
            }}
            onMouseDown={startAIPaneResize}
          >
            <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-transparent transition-colors group-hover:bg-blue-300" />
          </div>

          <div
            className="pointer-events-none absolute right-0 z-40 hidden translate-x-0 opacity-100 transition-all duration-200 ease-out lg:block"
            style={{
              top: desktopFloatFrame.top,
              width: aiPaneWidth,
              height: desktopFloatFrame.height,
            }}
          >
            <div className="pointer-events-auto mr-4 flex h-full min-h-0 flex-col overflow-hidden rounded-[1.3rem] border border-slate-200 bg-white shadow-[0_10px_30px_rgba(15,23,42,0.08)]">
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
              <div className="min-h-0 flex-1 p-4 pb-5">
                <AIPane
                  category={category!}
                  slug={slug!}
                  threadKey={threadKey}
                  threadTitle={data.meta.title}
                  pendingReplyTarget={aiPendingReplyTarget}
                  onPendingReplyTargetConsumed={() => setAiPendingReplyTarget(null)}
                  onUseDraftAsReply={onUseDraftAsReply}
                  hasReplyDraft={hasDraft}
                />
              </div>
            </div>
          </div>
        </>
      )}

      {!isDesktopViewport() && mobileAiMode !== "closed" && (
        <div className="fixed inset-x-0 z-50 sm:hidden" style={{ bottom: mobileKeyboardInset }}>
          <div
            className={cn(
              "overflow-hidden border border-slate-200 bg-white shadow-[0_-12px_30px_rgba(15,23,42,0.12)] transition-all duration-200 ease-out",
              mobileAiMode === "peek" && "rounded-t-[1.5rem]",
              mobileAiMode === "full" && "rounded-t-[1.5rem]",
            )}
            style={{ height: mobileAiHeight }}
          >
            <div
              className="flex w-full touch-none items-center justify-between border-b border-slate-200/80 px-4 py-3 text-left"
              onPointerDown={startMobileAiDrag}
              onPointerMove={moveMobileAiDrag}
              onPointerUp={endMobileAiDrag}
              onPointerCancel={cancelMobileAiDrag}
            >
              <div className="flex min-w-0 flex-1 items-center gap-3">
                <div className="h-1.5 w-10 rounded-full bg-slate-200" />
                <div className="flex items-center gap-2 text-sm font-medium text-slate-800">
                  <Bot className="h-4 w-4 text-blue-600" />
                  AI 助手
                </div>
              </div>
              <div className="ml-3 flex items-center gap-1">
                {mobileAiMode === "full" ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 rounded-lg text-slate-500 hover:bg-slate-100"
                    onPointerDown={(event) => event.stopPropagation()}
                    onClick={(event) => {
                      event.stopPropagation();
                      minimizeMobileAi();
                    }}
                  >
                    <Minimize2 className="h-4 w-4" />
                  </Button>
                ) : (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 rounded-lg text-slate-500 hover:bg-slate-100"
                    onPointerDown={(event) => event.stopPropagation()}
                    onClick={(event) => {
                      event.stopPropagation();
                      maximizeMobileAi();
                    }}
                  >
                    <Maximize2 className="h-4 w-4" />
                  </Button>
                )}
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 rounded-lg text-slate-500 hover:bg-slate-100"
                  onPointerDown={(event) => event.stopPropagation()}
                  onClick={(event) => {
                    event.stopPropagation();
                    setMobileAiMode("closed");
                  }}
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>
            </div>

            {mobileAiShowsBody && (
              <div className="h-[calc(100%-3.5rem)] p-4 pb-5">
                <AIPane
                  category={category!}
                  slug={slug!}
                  threadKey={threadKey}
                  threadTitle={data.meta.title}
                  pendingReplyTarget={aiPendingReplyTarget}
                  onPendingReplyTargetConsumed={() => setAiPendingReplyTarget(null)}
                  onUseDraftAsReply={onUseDraftAsReply}
                  hasReplyDraft={hasDraft}
                />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function ComposerTab({
  label,
  active,
  className,
  onClick,
}: {
  label: string;
  active: boolean;
  className?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        className,
        active
          ? "rounded-lg bg-blue-50 px-3 py-1.5 text-sm font-medium text-blue-700"
          : "rounded-lg px-3 py-1.5 text-sm text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700",
      )}
    >
      {label}
    </button>
  );
}

function ProposalHeroCard({
  post,
  category,
  slug,
  threadStatus,
  postCount,
  favorite,
  favoriteSaving,
  githubFileUrl,
  onToggleFavorite,
  onStatusChange,
  onAIReply,
  onMentioned,
}: {
  post: Post;
  category: string;
  slug: string;
  threadStatus: string | null;
  postCount: number;
  favorite: boolean;
  favoriteSaving: boolean;
  githubFileUrl: string | null;
  onToggleFavorite: () => Promise<void>;
  onStatusChange: (to: string, reason?: string) => Promise<void>;
  onAIReply: () => void;
  onMentioned: () => void;
}) {
  const author = post.author_display ?? (post.frontmatter.author as string) ?? "unknown";
  const created = post.frontmatter.created as string | null ?? null;
  const bodyRef = useRef<HTMLDivElement>(null);
  const [overflows, setOverflows] = useState(false);
  const [collapsed, setCollapsed] = useState(true);

  useLayoutEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    setOverflows(el.scrollHeight > el.clientHeight + 2);
  }, [post.body]);

  return (
    <article className="paper-panel rounded-[1.2rem] border p-4 sm:rounded-[1.3rem] sm:p-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-3 sm:gap-4">
          <PostTypeBadge type="proposal" />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-slate-500 sm:text-sm">
              <span>第 1 条记录</span>
              <span>作者：</span>
              <span className="font-medium text-slate-900">{author}</span>
              {created ? <span>{formatFullDateTime(created)}</span> : null}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-500 sm:text-xs">
              <span className="font-mono">{post.filename}</span>
              <span>{postCount} 条帖子</span>
              <span className="hidden sm:inline">{category}</span>
              <span className="hidden sm:inline">产品讨论人</span>
            </div>
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <StatusControl status={threadStatus} onChange={onStatusChange} />
          <Button
            variant={favorite ? "secondary" : "ghost"}
            size="sm"
            className="h-9 rounded-lg px-3 text-xs text-slate-700"
            disabled={favoriteSaving}
            onClick={() => { void onToggleFavorite(); }}
          >
            <Star className={`h-4 w-4 ${favorite ? "fill-current text-amber-500" : ""}`} />
            {favorite ? "已收藏" : "收藏"}
          </Button>
        </div>
      </div>

      <div className="mt-5 border-t border-slate-200/80 pt-5">
        {post.mentions.length > 0 && (
          <div className="mb-4 space-y-2">
            {post.mentions.map((mention, index) => (
              <MentionChip key={index} mention={mention} />
            ))}
          </div>
        )}

        <div
          ref={bodyRef}
          style={collapsed ? { maxHeight: COLLAPSE_HEIGHT, overflow: "hidden" } : undefined}
          className="prose-pivot max-w-none text-[13.5px] leading-7 text-slate-700 sm:text-[15px]"
        >
          <Markdown remarkPlugins={[remarkGfm]}>{post.body}</Markdown>
        </div>

        {overflows && (
          <button
            type="button"
            onClick={() => setCollapsed((value) => !value)}
            className="mt-2 text-xs text-primary hover:underline"
          >
            {collapsed ? "展开全文 ↓" : "收起全文 ↑"}
          </button>
        )}
      </div>

      <div className="mt-5 flex flex-col gap-3 border-t border-slate-200/80 pt-4 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-2">
          <PostMentionPopover category={category} slug={slug} post={post} onMentioned={onMentioned} />
          <Button
            variant="ghost"
            size="sm"
            className="h-8 rounded-lg px-3 text-xs font-medium text-slate-700 hover:bg-slate-100"
            onClick={onAIReply}
          >
            <Bot className="mr-1.5 h-3.5 w-3.5" />
            AI 回复
          </Button>
        </div>
        {githubFileUrl ? (
          <a
            href={githubFileUrl}
            target="_blank"
            rel="noreferrer"
            className="text-xs font-mono text-slate-500 underline decoration-slate-300 underline-offset-2 hover:text-slate-900"
          >
            {post.filename}
          </a>
        ) : (
          <span className="text-xs font-mono text-slate-500">{post.filename}</span>
        )}
      </div>
    </article>
  );
}

function ReplyPostCard({
  post,
  postNumber,
  category,
  slug,
  githubFileUrl,
  onAIReply,
  onMentioned,
}: {
  post: Post;
  postNumber: number;
  category: string;
  slug: string;
  githubFileUrl: string | null;
  onAIReply: () => void;
  onMentioned: () => void;
}) {
  const author = post.author_display ?? (post.frontmatter.author as string) ?? "unknown";
  const type = (post.frontmatter.type as string) ?? "";
  const created = post.frontmatter.created as string | null ?? null;
  const bodyRef = useRef<HTMLDivElement>(null);
  const [overflows, setOverflows] = useState(false);
  const [collapsed, setCollapsed] = useState(true);

  useLayoutEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    setOverflows(el.scrollHeight > el.clientHeight + 2);
  }, [post.body]);

  return (
    <article className="rounded-[1.05rem] border border-slate-200/90 bg-white px-4 py-4 shadow-[0_4px_16px_rgba(15,23,42,0.025)] sm:rounded-[1.15rem] sm:px-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-3">
            <PostTypeBadge type={type === "reply" ? "reply" : "post"} compact />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-slate-500 sm:text-sm">
                <span>{`第 ${postNumber} 条记录`}</span>
                <span>作者：</span>
                <span className="font-medium text-slate-900">{author}</span>
                {created ? <span className="text-xs text-slate-500">{formatFullDateTime(created)}</span> : null}
              </div>
              {githubFileUrl ? (
                <a
                  href={githubFileUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-1 inline-block text-xs font-mono text-slate-500 underline decoration-slate-300 underline-offset-2 hover:text-slate-900"
                >
                  {post.filename}
                </a>
              ) : (
                <span className="mt-1 inline-block text-xs font-mono text-slate-500">{post.filename}</span>
              )}
            </div>
          </div>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <PostMentionPopover category={category} slug={slug} post={post} onMentioned={onMentioned} />
          <Button
            variant="ghost"
            size="sm"
            className="h-8 rounded-lg px-3 text-xs font-medium text-slate-700 hover:bg-slate-100"
            onClick={onAIReply}
          >
            <Bot className="mr-1.5 h-3.5 w-3.5" />
            AI 回复
          </Button>
        </div>
      </div>

      {post.mentions.length > 0 && (
        <div className="mt-4 space-y-2">
          {post.mentions.map((mention, index) => (
            <MentionChip key={index} mention={mention} />
          ))}
        </div>
      )}

        <div
          ref={bodyRef}
          style={collapsed ? { maxHeight: COLLAPSE_HEIGHT, overflow: "hidden" } : undefined}
        className="prose-pivot mt-3 max-w-none text-[13.5px] leading-7 text-slate-700 sm:text-[15px]"
      >
        <Markdown remarkPlugins={[remarkGfm]}>{post.body}</Markdown>
      </div>

      {overflows && (
        <button
          type="button"
          onClick={() => setCollapsed((value) => !value)}
          className="mt-2 text-xs text-primary hover:underline"
        >
          {collapsed ? "展开全文 ↓" : "收起全文 ↑"}
        </button>
      )}
    </article>
  );
}

function PostMentionPopover({
  category,
  slug,
  post,
  onMentioned,
}: {
  category: string;
  slug: string;
  post: Post;
  onMentioned: () => void;
}) {
  const [mentionOpen, setMentionOpen] = useState(false);
  const [mentionValue, setMentionValue] = useState<MentionBlock>(emptyMention());
  const resolvedNames = useRef<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!mentionOpen) return;
    const handler = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setMentionOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [mentionOpen]);

  const submitMention = async () => {
    if (mentionValue.open_ids.length === 0) return toast.error("至少选一个人");
    if (!isMentionValid(mentionValue)) return toast.error("必须填一句话");
    setSubmitting(true);
    try {
      await addMention(category, slug, post.filename, mentionValue);
      setMentionOpen(false);
      setMentionValue(emptyMention());
      toast.success("已发送提及");
      onMentioned();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="relative" ref={popoverRef}>
      <Button
        variant="ghost"
        size="sm"
        className="h-8 rounded-lg px-3 text-xs font-medium text-slate-700 hover:bg-slate-100"
        onClick={() => setMentionOpen((open) => !open)}
      >
        <AtSign className="mr-1.5 h-3.5 w-3.5" />
        提及
      </Button>
      {mentionOpen && (
        <div className="fixed inset-x-4 top-20 z-50 rounded-xl border border-slate-200 bg-white p-4 shadow-[0_16px_40px_rgba(15,23,42,0.08)] sm:absolute sm:inset-x-auto sm:right-0 sm:top-full sm:mt-2 sm:w-[min(22rem,calc(100vw-2rem))]">
          <p className="mb-3 text-xs font-semibold text-muted-foreground">提及某人</p>
          <MentionField
            value={mentionValue}
            onChange={setMentionValue}
            resolvedNames={resolvedNames.current}
          />
          <div className="mt-3 flex justify-end gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setMentionOpen(false);
                setMentionValue(emptyMention());
              }}
              disabled={submitting}
            >
              取消
            </Button>
            <Button size="sm" onClick={submitMention} disabled={submitting}>
              {submitting ? "发送中…" : "发送"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function PostTypeBadge({
  type,
  compact = false,
}: {
  type: "proposal" | "reply" | "post";
  compact?: boolean;
}) {
  const label = type === "proposal" ? "提案" : type === "reply" ? "回复" : "帖子";
  return (
    <span
      className={cn(
        "flex shrink-0 items-center justify-center rounded-2xl bg-blue-50 font-semibold text-blue-700 ring-1 ring-blue-200",
        compact ? "h-8 min-w-10 px-2.5 text-xs sm:h-10 sm:min-w-12 sm:px-3 sm:text-sm" : "h-10 min-w-12 px-3 text-xs sm:h-14 sm:min-w-14 sm:px-4 sm:text-sm",
      )}
    >
      {label}
    </span>
  );
}

function MentionChip({ mention }: { mention: MentionEntry }) {
  const names = mention.users.map((u) => u.user).join("、");
  return (
    <div className="flex items-start gap-2 rounded-xl border border-slate-200/70 bg-slate-100/82 px-3 py-2.5 text-xs">
      <AtSign className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      <div className="min-w-0">
        <span className="font-medium text-slate-800">{names}</span>
        {mention.comments && (
          <span className="text-muted-foreground"> — {mention.comments}</span>
        )}
        {(mention.author_display || mention.time) && (
          <span className="text-muted-foreground/70">
            {mention.author_display && ` · by ${mention.author_display}`}
            {mention.time && ` · ${relativeTime(mention.time)}`}
          </span>
        )}
      </div>
    </div>
  );
}

function ReplyForm({
  category,
  slug,
  body,
  setBody,
  mentions,
  setMentions,
  draftId,
  setDraftId,
  replyTo,
  references,
  onPosted,
}: {
  category: string;
  slug: string;
  body: string;
  setBody: (v: string) => void;
  mentions: MentionBlock;
  setMentions: (v: MentionBlock) => void;
  draftId: string | null;
  setDraftId: (id: string | null) => void;
  replyTo: string | null;
  setReplyTo: (v: string | null) => void;
  references: string[];
  setReferences: (v: string[]) => void;
  onPosted: () => void;
}) {
  const threadKey = `${category}/${slug}`;
  const resolvedNames = useRef<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);

  const { status, saveNow } = useDraftAutosave({
    draftId,
    setDraftId,
    type: "reply",
    payload: () => ({
      body_md: body,
      thread_key: threadKey,
      mentions: mentions.open_ids.length > 0 || mentions.comments ? mentions : null,
      reply_to: replyTo,
      references,
    }),
    enabled: body.trim().length > 0,
    deps: [body, mentions, replyTo, references],
  });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isMentionValid(mentions)) return toast.error("圈人后必须填一句话");
    setSubmitting(true);
    try {
      const id = await saveNow();
      if (!id) throw new Error("failed to save draft before posting");
      await publishDraft(id);
      setDraftId(null);
      onPosted();
      toast.success("已发布回复");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  const discard = async () => {
    if (!confirm("删除这条回复草稿？")) return;
    try {
      if (draftId) await deleteDraft(draftId);
      setDraftId(null);
      setBody("");
      setMentions(emptyMention());
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
        <span>{formatSaveStatus(status)}</span>
        <span>{replyTo ? `当前将回复到：${replyTo}` : "当前将作为新的回复发布"}</span>
      </div>

      <Textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        rows={6}
        maxLength={50000}
        placeholder="写下你的回复，或先切到 AI 助手整理草稿…"
        className="min-h-[8rem] rounded-2xl border-slate-300 bg-slate-50/90 font-mono text-sm sm:min-h-[9rem]"
      />

      <MentionField
        value={mentions}
        onChange={setMentions}
        resolvedNames={resolvedNames.current}
      />

      <div className="flex flex-wrap gap-3">
        <Button type="submit" className="rounded-xl bg-blue-600 hover:bg-blue-700" disabled={submitting || !body.trim()}>
          {submitting ? "发布中…" : "发布回复"}
        </Button>
        {(draftId || body.trim()) && (
          <Button type="button" variant="outline" className="rounded-xl" onClick={discard}>
            删除草稿
          </Button>
        )}
      </div>
    </form>
  );
}

function buildGitHubFileUrl(
  repoUrl: string | null,
  ref: string | null,
  category: string,
  slug: string,
  filename: string,
): string | null {
  if (!repoUrl || !ref) return null;

  const cleaned = repoUrl.trim().replace(/\.git$/, "");
  let base: string | null = null;

  if (cleaned.startsWith("https://github.com/")) {
    base = cleaned;
  } else {
    const sshMatch = cleaned.match(/^git@github\.com:([^/]+\/[^/]+)$/);
    if (sshMatch) {
      base = `https://github.com/${sshMatch[1]}`;
    }
  }

  if (!base) return null;

  const path = ["discussions", category, slug, filename]
    .map(encodeURIComponent)
    .join("/");

  return `${base}/blob/${encodeURIComponent(ref)}/${path}`;
}

export function ThreadDetailEmpty() {
  return <HomeWelcomePane />;
}
