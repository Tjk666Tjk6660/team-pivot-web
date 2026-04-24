import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { MermaidBlock } from "@/components/MermaidBlock";
import { ArrowDown, ArrowUp, AtSign, Bot, ChevronLeft, FileText, Maximize2, Minimize2, Sparkles, Star, X } from "lucide-react";
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

const POST_MARKDOWN_COMPONENTS = {
  code(props: { className?: string; children?: React.ReactNode; inline?: boolean }) {
    const { className, children, inline, ...rest } = props;
    const match = /language-([\w-]+)/.exec(className ?? "");
    const lang = match?.[1];
    const raw = Array.isArray(children) ? children.join("") : String(children ?? "");
    if (!inline && lang === "mermaid") {
      return <MermaidBlock code={raw.replace(/\n$/, "")} />;
    }
    return (
      <code className={className} {...rest}>
        {children}
      </code>
    );
  },
};

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
  const [scrollPos, setScrollPos] = useState({ top: 0, max: 0 });
  const [mobileAiMode, setMobileAiMode] = useState<"closed" | "peek" | "full">("closed");
  const [mobileKeyboardInset, setMobileKeyboardInset] = useState(0);
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

  const hasDraft = replyBody.trim().length > 0;
  // 桌面 AI 浮动面板需要 sidebar (≈320) + 主内容 (≥620) + AI panel (≥420) + gaps
  // 加起来约 1380+px 才不挤。1024-1280 (iPad Pro) 走移动端全屏抽屉更舒服。
  const isDesktopViewport = () => typeof window !== "undefined" && window.innerWidth >= 1280;
  const desktopFloatGap = 16;
  const openMobileAi = () => setMobileAiMode("full");
  const minimizeMobileAi = () => setMobileAiMode("peek");
  const closeMobileAi = () => setMobileAiMode("closed");

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
    // Recompute scroll bounds whenever the thread data changes — keeps the
    // floating "to top / to bottom" buttons accurate on first render.
    if (typeof window === "undefined") return;
    const id = window.requestAnimationFrame(() => updateScrollPos());
    return () => window.cancelAnimationFrame(id);
  }, [data]);

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
      const inset = viewport
        ? Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop)
        : 0;
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
    openMobileAi();
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

  const updateScrollPos = () => {
    const el = scrollContainerRef.current;
    if (!el) return;
    setScrollPos({
      top: el.scrollTop,
      max: Math.max(0, el.scrollHeight - el.clientHeight),
    });
  };

  const scrollToTop = () => {
    scrollContainerRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  };
  const scrollToBottom = () => {
    const el = scrollContainerRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
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
        updateScrollPos();
      }}
    >
      <div
        className={cn(
          "px-3 py-3 sm:px-5 sm:py-5",
          aiOpen
            ? "mx-0 max-w-none lg:pr-4"
            : "mx-auto max-w-[88rem]",
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
                <div
                  className="hidden min-w-0 items-center gap-2 text-[11.5px] font-meta uppercase tracking-[0.06em] lg:flex"
                  style={{ color: "var(--text-mute)" }}
                >
                  <Link
                    to="/"
                    className="hover:opacity-80"
                    style={{ color: "var(--text-mute)" }}
                  >
                    Pivot
                  </Link>
                  <span>›</span>
                  <span style={{ color: "var(--text-soft)" }}>{category}</span>
                </div>
                <div className="lg:hidden">
                  <div
                    className="truncate text-[15px] font-semibold font-serif-body"
                    style={{ color: "var(--text)", letterSpacing: "var(--letter-tight)" }}
                  >
                    {data.meta.title}
                  </div>
                  <div className="mt-0.5 text-[11px] font-meta" style={{ color: "var(--text-mute)" }}>
                    {category}
                  </div>
                </div>
              </div>
              <Button
                type="button"
                variant="default"
                size="sm"
                className="h-9 shrink-0 rounded-md px-3.5 text-xs font-semibold shadow-none"
                style={{
                  background: "var(--accent)",
                  color: "var(--accent-ink)",
                  border: "1px solid var(--accent)",
                }}
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
              <div
                className="flex items-center justify-between gap-3 px-1 pt-2"
                style={{ borderTop: "1px solid var(--line)" }}
              >
                <div className="flex items-center gap-3 pt-3">
                  <span
                    className="section-kicker"
                    style={{ color: "var(--text-mute)" }}
                  >
                    II. 讨论
                  </span>
                  <span
                    className="text-[12.5px] font-meta"
                    style={{ color: "var(--text-mute)" }}
                  >
                    · {replyPosts.length} 封回信
                  </span>
                </div>
                <div
                  className="pt-3 text-[11.5px] font-meta"
                  style={{ color: "var(--text-mute)" }}
                >
                  按时间顺序
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
                <div
                  className="rounded-[var(--r-md)] px-5 py-6 text-[13.5px] font-serif-body italic"
                  style={{
                    border: "1px dashed var(--line-strong)",
                    background: "var(--surface-alt)",
                    color: "var(--text-mute)",
                  }}
                >
                  还没有回信。你可以直接在下面写第一封回信，或先切到 AI 助手整理思路。
                </div>
              )}
            </section>

            <section
              ref={composerRef}
              className="overflow-hidden rounded-[var(--r-lg)]"
              style={{
                background: "var(--surface)",
                border: "1px solid var(--line-strong)",
                boxShadow: "var(--shadow-md)",
              }}
            >
              <div
                className="flex items-center gap-1 px-4 py-3"
                style={{
                  borderBottom: "1px solid var(--line-soft)",
                  background: "var(--surface-alt)",
                }}
              >
                <span
                  className="text-[11.5px] font-bold uppercase tracking-[0.06em] font-meta mr-1"
                  style={{ color: "var(--accent)" }}
                >
                  分析你的想法
                </span>
                <ComposerTab
                  label="回复"
                  active={
                    isDesktopViewport()
                      ? !aiOpen
                      : mobileAiMode === "closed"
                  }
                  onClick={() => {
                    if (isDesktopViewport()) {
                      setAiOpen(false);
                    } else {
                      setMobileAiMode("closed");
                    }
                  }}
                />
                <ComposerTab
                  label="AI 助手"
                  active={
                    isDesktopViewport()
                      ? aiOpen
                      : mobileAiMode !== "closed"
                  }
                  onClick={() => {
                    if (!aiPendingReplyTarget && data.posts.length > 0) {
                      const last = data.posts[data.posts.length - 1];
                      setAiPendingReplyTarget(`${category}/${slug}/${last.filename}`);
                    }
                    if (isDesktopViewport()) {
                      setAiOpen((open) => !open);
                    } else {
                      setMobileAiMode((current) => (current === "closed" ? "full" : "closed"));
                    }
                  }}
                />
                <div
                  className="ml-auto hidden items-center gap-1.5 text-[11.5px] font-meta sm:flex"
                  style={{ color: "var(--text-mute)" }}
                >
                  <FileText className="h-3 w-3" />
                  {replyTo ? `回复到 ${replyTo}` : "直接补充新的回复"}
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

      {/* Floating scroll-to-top / scroll-to-bottom controls */}
      {scrollPos.max > 400 && (
        <div
          className="pointer-events-none sticky bottom-4 z-30 flex justify-end pr-4 sm:pr-6"
          style={{ marginTop: -56 }}
        >
          <div
            className="pointer-events-auto flex flex-col overflow-hidden rounded-full"
            style={{
              background: "var(--surface)",
              border: "1px solid var(--line-strong)",
              boxShadow: "var(--shadow-md)",
            }}
          >
            <button
              type="button"
              onClick={scrollToTop}
              disabled={scrollPos.top <= 8}
              title="回到顶部"
              aria-label="回到顶部"
              className="flex h-9 w-9 items-center justify-center transition-colors hover:bg-[var(--accent-bg)] disabled:cursor-default disabled:opacity-30"
              style={{ color: "var(--text-soft)" }}
            >
              <ArrowUp className="h-4 w-4" />
            </button>
            <span
              aria-hidden
              className="mx-2 h-px"
              style={{ background: "var(--line-soft)" }}
            />
            <button
              type="button"
              onClick={scrollToBottom}
              disabled={scrollPos.top >= scrollPos.max - 8}
              title="跳到底部"
              aria-label="跳到底部"
              className="flex h-9 w-9 items-center justify-center transition-colors hover:bg-[var(--accent-bg)] disabled:cursor-default disabled:opacity-30"
              style={{ color: "var(--text-soft)" }}
            >
              <ArrowDown className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}

      {aiOpen && isDesktopViewport() && (
        <>
          <div
            className="group absolute z-40 hidden w-6 cursor-col-resize xl:block"
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
            className="pointer-events-none absolute right-0 z-40 hidden translate-x-0 opacity-100 transition-all duration-200 ease-out xl:block"
            style={{
              top: desktopFloatFrame.top,
              width: aiPaneWidth,
              height: desktopFloatFrame.height,
            }}
          >
            <div
              className="pointer-events-auto mr-4 flex h-full min-h-0 flex-col overflow-hidden rounded-[var(--r-lg)]"
              style={{
                background: "var(--bg-alt)",
                border: "1px solid var(--line-strong)",
                boxShadow: "var(--shadow-lg)",
              }}
            >
              <div
                className="flex items-center justify-between px-4 py-3"
                style={{
                  borderBottom: "1px solid var(--line)",
                  background: "var(--surface)",
                }}
              >
                <div className="flex items-center gap-2.5">
                  <span
                    className="flex h-6 w-6 items-center justify-center rounded-md text-white"
                    style={{ background: "linear-gradient(135deg,#6c52d9,#3a6bf5)" }}
                  >
                    <Bot className="h-3.5 w-3.5" />
                  </span>
                  <span
                    className="text-[13px] font-semibold font-serif-body"
                    style={{ color: "var(--text)" }}
                  >
                    AI 助手
                  </span>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 rounded-md hover:bg-[var(--surface-alt)]"
                  style={{ color: "var(--text-mute)" }}
                  onClick={() => setAiOpen(false)}
                >
                  <X className="h-3.5 w-3.5" />
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

      {!isDesktopViewport() && mobileAiMode === "full" && (
        <div
          className="fixed inset-0 z-50 flex flex-col xl:hidden"
          style={{
            background: "var(--bg-alt)",
            paddingBottom: mobileKeyboardInset,
          }}
        >
          <div
            className="flex shrink-0 items-center justify-between px-4 py-3"
            style={{
              borderBottom: "1px solid var(--line)",
              background: "var(--surface)",
            }}
          >
            <div className="flex min-w-0 flex-1 items-center gap-2.5">
              <span
                className="flex h-6 w-6 items-center justify-center rounded-md text-white"
                style={{ background: "linear-gradient(135deg,#6c52d9,#3a6bf5)" }}
              >
                <Bot className="h-3.5 w-3.5" />
              </span>
              <span
                className="text-[13px] font-semibold font-serif-body"
                style={{ color: "var(--text)" }}
              >
                AI 助手
              </span>
            </div>
            <div className="ml-3 flex items-center gap-1">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8 rounded-md hover:bg-[var(--surface-alt)]"
                style={{ color: "var(--text-mute)" }}
                onClick={minimizeMobileAi}
                title="最小化"
                aria-label="最小化"
              >
                <Minimize2 className="h-4 w-4" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8 rounded-md hover:bg-[var(--surface-alt)]"
                style={{ color: "var(--text-mute)" }}
                onClick={closeMobileAi}
                title="关闭"
                aria-label="关闭"
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          </div>

          <div className="min-h-0 flex-1 p-1 pb-2">
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
      )}

      {!isDesktopViewport() && mobileAiMode === "peek" && (
        <button
          type="button"
          onClick={openMobileAi}
          className="fixed inset-x-0 bottom-0 z-50 flex h-14 items-center justify-between gap-2 px-4 xl:hidden"
          style={{
            bottom: mobileKeyboardInset,
            background: "var(--surface)",
            borderTop: "1px solid var(--line-strong)",
            boxShadow: "0 -8px 20px rgba(31, 29, 23, 0.08)",
          }}
        >
          <div className="flex min-w-0 flex-1 items-center gap-2.5">
            <span
              className="flex h-6 w-6 items-center justify-center rounded-md text-white"
              style={{ background: "linear-gradient(135deg,#6c52d9,#3a6bf5)" }}
            >
              <Bot className="h-3.5 w-3.5" />
            </span>
            <span
              className="truncate text-[13px] font-semibold font-serif-body"
              style={{ color: "var(--text)" }}
            >
              AI 助手
            </span>
          </div>
          <div className="ml-3 flex items-center gap-1">
            <span
              className="flex h-8 w-8 items-center justify-center rounded-md"
              style={{ color: "var(--text-mute)" }}
              aria-hidden
            >
              <Maximize2 className="h-4 w-4" />
            </span>
            <span
              role="button"
              tabIndex={0}
              onClick={(e) => { e.stopPropagation(); closeMobileAi(); }}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.stopPropagation();
                  closeMobileAi();
                }
              }}
              className="flex h-8 w-8 items-center justify-center rounded-md hover:bg-[var(--surface-alt)]"
              style={{ color: "var(--text-mute)" }}
              title="关闭"
              aria-label="关闭"
            >
              <X className="h-4 w-4" />
            </span>
          </div>
        </button>
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
        "rounded-md px-3 py-1.5 text-[12.5px] font-semibold transition-colors",
      )}
      style={
        active
          ? { background: "var(--accent-bg)", color: "var(--accent)" }
          : { background: "transparent", color: "var(--text-mute)" }
      }
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
  const [headerCollapseHint, setHeaderCollapseHint] = useState(false);

  useLayoutEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    setOverflows(el.scrollHeight > el.clientHeight + 2);
  }, [post.body]);

  useEffect(() => {
    if (!headerCollapseHint) return;
    const timer = window.setTimeout(() => setHeaderCollapseHint(false), 1200);
    return () => window.clearTimeout(timer);
  }, [headerCollapseHint]);

  const toggleCollapsed = (source: "header" | "footer") => {
    setCollapsed((value) => {
      const next = !value;
      if (source === "footer" && value && !next) {
        setHeaderCollapseHint(true);
      }
      if (next) {
        setHeaderCollapseHint(false);
      }
      return next;
    });
  };

  return (
    <article
      className="relative rounded-[var(--r-lg)] p-5 sm:p-6"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--line)",
        boxShadow: "var(--shadow-sm)",
      }}
    >
      {/* Sepia accent rule on the left edge */}
      <span
        aria-hidden
        className="absolute left-0 top-6 bottom-6 w-[3px] rounded-r"
        style={{ background: "var(--accent)" }}
      />
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
        <div className="flex min-w-0 items-start gap-3 sm:gap-4">
          <PostTypeBadge type="proposal" />
          <div className="min-w-0 flex-1 space-y-1">
            <div
              className="text-[12.5px] leading-[1.55] font-meta"
              style={{ color: "var(--text-mute)" }}
            >
              作者{" "}
              <span style={{ color: "var(--text)", fontWeight: 600 }}>{author}</span>
              {created ? ` · ${formatFullDateTime(created)}` : null}
            </div>
            <div
              className="flex min-w-0 flex-wrap items-center gap-x-2 text-[11px] font-meta"
              style={{ color: "var(--text-mute)" }}
            >
              <span
                className="min-w-0 max-w-full truncate font-mono"
                title={post.filename}
              >
                {post.filename}
              </span>
              <span>· {postCount} 条</span>
              <span className="hidden sm:inline">· {category}</span>
            </div>
            {overflows && !collapsed && (
              <div className="pt-1">
                <CollapseHeaderAction
                  visible
                  active={headerCollapseHint}
                  onClick={() => toggleCollapsed("header")}
                />
              </div>
            )}
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <StatusControl status={threadStatus} onChange={onStatusChange} />
          <Button
            variant="ghost"
            size="sm"
            className="h-9 rounded-md px-3 text-xs"
            style={{
              color: favorite ? "var(--accent)" : "var(--text-soft)",
              background: favorite ? "var(--accent-bg)" : "transparent",
              border: favorite ? "1px solid var(--accent-soft)" : "1px solid transparent",
            }}
            disabled={favoriteSaving}
            onClick={() => { void onToggleFavorite(); }}
          >
            <Star
              className="h-3.5 w-3.5"
              style={{ fill: favorite ? "currentColor" : "none" }}
            />
            {favorite ? "已收藏" : "收藏"}
          </Button>
        </div>
      </div>

      <div
        className="mt-5 pt-5"
        style={{ borderTop: "1px solid var(--line-soft)" }}
      >
        {post.mentions.length > 0 && (
          <div className="mb-4 space-y-2">
            {post.mentions.map((mention, index) => (
              <MentionChip key={index} mention={mention} index={index} />
            ))}
          </div>
        )}

        <div
          ref={bodyRef}
          style={collapsed ? { maxHeight: COLLAPSE_HEIGHT, overflow: "hidden" } : undefined}
          className="prose-pivot max-w-none text-[14.5px] leading-[1.75] sm:text-[16px]"
        >
          <Markdown remarkPlugins={[remarkGfm]} components={POST_MARKDOWN_COMPONENTS}>
            {post.body}
          </Markdown>
        </div>

        {overflows && (
          <button
            type="button"
            onClick={() => toggleCollapsed("footer")}
            className="mt-2 text-[12px] font-meta hover:underline"
            style={{ color: "var(--accent)" }}
          >
            {collapsed ? "展开全文 ↓" : "收起全文 ↑"}
          </button>
        )}
      </div>

      <div
        className="mt-5 flex flex-col gap-3 pt-4 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between"
        style={{ borderTop: "1px solid var(--line-soft)" }}
      >
        <div className="flex flex-wrap items-center gap-2">
          <PostMentionPopover
            category={category}
            slug={slug}
            post={post}
            onMentioned={onMentioned}
            align="left"
          />
          <Button
            variant="outline"
            size="sm"
            className="h-8 rounded-md px-3 text-[12px] font-semibold shadow-none hover:bg-[var(--accent-bg)] hover:text-[var(--accent)]"
            style={{
              background: "var(--surface-alt)",
              border: "1px solid var(--line-strong)",
              color: "var(--text-soft)",
            }}
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
            className="text-[11.5px] font-mono underline underline-offset-2"
            style={{ color: "var(--text-mute)" }}
          >
            {post.filename}
          </a>
        ) : (
          <span className="text-[11.5px] font-mono" style={{ color: "var(--text-mute)" }}>
            {post.filename}
          </span>
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
  const [headerCollapseHint, setHeaderCollapseHint] = useState(false);

  useLayoutEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    setOverflows(el.scrollHeight > el.clientHeight + 2);
  }, [post.body]);

  useEffect(() => {
    if (!headerCollapseHint) return;
    const timer = window.setTimeout(() => setHeaderCollapseHint(false), 1200);
    return () => window.clearTimeout(timer);
  }, [headerCollapseHint]);

  const toggleCollapsed = (source: "header" | "footer") => {
    setCollapsed((value) => {
      const next = !value;
      if (source === "footer" && value && !next) {
        setHeaderCollapseHint(true);
      }
      if (next) {
        setHeaderCollapseHint(false);
      }
      return next;
    });
  };

  return (
    <article
      className="rounded-[var(--r-md)] px-5 py-5 sm:px-6 sm:py-6"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--line)",
        boxShadow: "var(--shadow-sm)",
      }}
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-3">
            <PostTypeBadge type={type === "reply" ? "reply" : "post"} compact />
            <div className="min-w-0 flex-1 space-y-1">
              <div
                className="text-[12.5px] leading-[1.55] font-meta"
                style={{ color: "var(--text-mute)" }}
              >
                第 {postNumber} 条 · 作者{" "}
                <span style={{ color: "var(--text)", fontWeight: 600 }}>{author}</span>
                {created ? ` · ${formatFullDateTime(created)}` : null}
              </div>
              {githubFileUrl ? (
                <a
                  href={githubFileUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="block min-w-0 max-w-full truncate text-[11px] font-mono underline underline-offset-2"
                  style={{ color: "var(--text-mute)" }}
                  title={post.filename}
                >
                  {post.filename}
                </a>
              ) : (
                <span
                  className="block min-w-0 max-w-full truncate text-[11px] font-mono"
                  style={{ color: "var(--text-mute)" }}
                  title={post.filename}
                >
                  {post.filename}
                </span>
              )}
              {overflows && !collapsed && (
                <div className="pt-1">
                  <CollapseHeaderAction
                    visible
                    active={headerCollapseHint}
                    onClick={() => toggleCollapsed("header")}
                  />
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <PostMentionPopover category={category} slug={slug} post={post} onMentioned={onMentioned} />
          <Button
            variant="outline"
            size="sm"
            className="h-8 rounded-md px-3 text-[12px] font-semibold shadow-none hover:bg-[var(--accent-bg)] hover:text-[var(--accent)]"
            style={{
              background: "var(--surface-alt)",
              border: "1px solid var(--line-strong)",
              color: "var(--text-soft)",
            }}
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
            <MentionChip key={index} mention={mention} index={index} />
          ))}
        </div>
      )}

      <div
        ref={bodyRef}
        style={collapsed ? { maxHeight: COLLAPSE_HEIGHT, overflow: "hidden" } : undefined}
        className="prose-pivot mt-4 max-w-none text-[14px] leading-[1.75] sm:text-[15.5px]"
      >
        <Markdown remarkPlugins={[remarkGfm]} components={POST_MARKDOWN_COMPONENTS}>
          {post.body}
        </Markdown>
      </div>

      {overflows && (
        <button
          type="button"
          onClick={() => toggleCollapsed("footer")}
          className="mt-2 text-[12px] font-meta hover:underline"
          style={{ color: "var(--accent)" }}
        >
          {collapsed ? "展开全文 ↓" : "收起全文 ↑"}
        </button>
      )}
    </article>
  );
}

function CollapseHeaderAction({
  visible,
  active,
  onClick,
}: {
  visible: boolean;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-hidden={!visible}
      tabIndex={visible ? 0 : -1}
      className={cn(
        "inline-flex h-6 items-center gap-1 rounded-md px-2 text-[11px] font-medium transition-all duration-300",
        visible
          ? "pointer-events-auto translate-y-0 opacity-100"
          : "pointer-events-none -translate-y-1 opacity-0",
        active && "scale-[1.04]",
      )}
      style={
        visible
          ? {
              background: active ? "var(--accent)" : "var(--accent-bg)",
              color: active ? "var(--accent-ink)" : "var(--accent)",
              border: "1px solid var(--accent-soft)",
            }
          : { background: "transparent", color: "transparent", border: "1px solid transparent" }
      }
    >
      收起全文
      <span className={cn("transition-transform duration-300", active && "-translate-y-0.5")}>↑</span>
    </button>
  );
}

function PostMentionPopover({
  category,
  slug,
  post,
  onMentioned,
  align = "right",
}: {
  category: string;
  slug: string;
  post: Post;
  onMentioned: () => void;
  align?: "left" | "right";
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
        variant="outline"
        size="sm"
        className="h-8 rounded-md px-3 text-[12px] font-semibold shadow-none hover:bg-[var(--accent-bg)] hover:text-[var(--accent)]"
        style={{
          background: "var(--surface-alt)",
          border: "1px solid var(--line-strong)",
          color: "var(--text-soft)",
        }}
        onClick={() => setMentionOpen((open) => !open)}
      >
        <AtSign className="mr-1.5 h-3.5 w-3.5" />
        提及
      </Button>
      {mentionOpen && (
        <div
          className={cn(
            "fixed inset-x-4 top-20 z-[60] rounded-[var(--r-md)] p-4 sm:absolute sm:inset-x-auto sm:top-full sm:mt-2 sm:w-[min(22rem,calc(100vw-2rem))]",
            align === "left" ? "sm:left-0" : "sm:right-0",
          )}
          style={{
            background: "var(--surface)",
            border: "1px solid var(--line-strong)",
            boxShadow: "var(--shadow-lg)",
          }}
        >
          <p
            className="mb-3 text-[10.5px] font-bold uppercase tracking-[0.18em] font-meta"
            style={{ color: "var(--text-mute)" }}
          >
            提及某人
          </p>
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
              className="h-8 rounded-[var(--r-sm)] px-3 text-[12.5px]"
              style={{
                background: "transparent",
                border: "1px solid var(--line-strong)",
                color: "var(--text-soft)",
              }}
            >
              取消
            </Button>
            <Button
              size="sm"
              onClick={submitMention}
              disabled={submitting}
              className="h-8 rounded-[var(--r-sm)] px-3 text-[12.5px] font-semibold shadow-none"
              style={{
                background: "var(--accent)",
                color: "var(--accent-ink)",
                border: "1px solid var(--accent)",
              }}
            >
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
  const label = type === "proposal" ? "I. 提案" : type === "reply" ? "回复" : "帖子";
  const isProposal = type === "proposal";
  return (
    <span
      className={cn(
        "flex shrink-0 items-center justify-center rounded-[var(--r-sm)] font-bold uppercase tracking-[0.08em] font-meta",
        compact
          ? "h-7 min-w-12 px-2 text-[10.5px]"
          : "h-8 min-w-14 px-2.5 text-[11px] sm:h-9 sm:min-w-16 sm:px-3 sm:text-[11.5px]",
      )}
      style={
        isProposal
          ? { background: "var(--accent-bg)", color: "var(--accent)" }
          : { background: "var(--surface-alt)", color: "var(--text-soft)", border: "1px solid var(--line)" }
      }
    >
      {label}
    </span>
  );
}

function MentionChip({ mention, index }: { mention: MentionEntry; index: number }) {
  const author = mention.author_display?.trim() || "未知用户";
  const comment = mention.comments?.trim();
  return (
    <div
      className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-[var(--r-md)] px-3 py-2 text-[12.5px]"
      style={{
        background: "var(--surface-alt)",
        border: "1px solid var(--line)",
        color: "var(--text)",
      }}
    >
      <div
        className="flex shrink-0 items-center gap-2 text-[11px] font-meta"
        style={{ color: "var(--text-mute)" }}
      >
        <span
          className="inline-flex h-5 items-center rounded-full px-2 font-medium"
          style={{
            background: "var(--surface)",
            border: "1px solid var(--line-strong)",
            color: "var(--text-soft)",
          }}
        >
          {`评论${index + 1}`}
        </span>
        {mention.time ? <span>· {relativeTime(mention.time)}</span> : null}
      </div>
      <div className="min-w-0 break-words leading-7">
        <span className="font-semibold" style={{ color: "var(--text)" }}>
          {author}
        </span>
        {mention.users.length > 0 && (
          <span className="ml-1 inline-flex flex-wrap gap-1 align-middle">
            {mention.users.map((u, i) => (
              <span
                key={i}
                className="inline-flex h-5 items-center rounded-full px-2 text-[11.5px] font-semibold"
                style={{
                  background: "var(--accent-bg)",
                  border: "1px solid var(--accent-soft)",
                  color: "var(--accent)",
                }}
              >
                @{u.user}
              </span>
            ))}
          </span>
        )}
        <span className="mx-1" style={{ color: "var(--text-mute)" }}>
          说：
        </span>
        {comment ? (
          <span style={{ color: "var(--text)" }}>{comment}</span>
        ) : (
          <span style={{ color: "var(--text-fade)" }}>未填写评论内容</span>
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
      <div
        className="flex flex-wrap items-center justify-between gap-2 text-[11.5px] font-meta"
        style={{ color: "var(--text-mute)" }}
      >
        <span>{formatSaveStatus(status)}</span>
        <span>
          {replyTo ? (
            <>
              当前将回复到：
              <span className="font-mono" style={{ color: "var(--text-soft)" }}>{replyTo}</span>
            </>
          ) : (
            "当前将作为新的回复发布"
          )}
        </span>
      </div>

      <Textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        rows={6}
        maxLength={50000}
        placeholder="写下你的回复，或先切到 AI 助手整理草稿…"
        className="min-h-[8rem] rounded-[var(--r-md)] font-mono text-[13px] leading-[1.6] sm:min-h-[9rem]"
        style={{
          background: "var(--surface-alt)",
          border: "1px solid var(--line-strong)",
          color: "var(--text)",
        }}
      />

      <MentionField
        value={mentions}
        onChange={setMentions}
        resolvedNames={resolvedNames.current}
      />

      <div className="flex flex-wrap gap-3">
        <Button
          type="submit"
          className="h-9 rounded-md px-4 text-[12.5px] font-semibold shadow-none"
          style={{
            background: "var(--accent)",
            color: "var(--accent-ink)",
            border: "1px solid var(--accent)",
          }}
          disabled={submitting || !body.trim()}
        >
          {submitting ? "发布中…" : "发布回复"}
        </Button>
        {(draftId || body.trim()) && (
          <Button
            type="button"
            variant="outline"
            className="h-9 rounded-md px-4 text-[12.5px]"
            style={{
              background: "transparent",
              color: "var(--text-soft)",
              border: "1px solid var(--line-strong)",
            }}
            onClick={discard}
          >
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
