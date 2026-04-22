import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { AtSign, Bot, ChevronLeft, GripVertical, Star } from "lucide-react";
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
import { Card } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { StatusControl } from "@/components/StatusControl";
import { MentionField, emptyMention, isMentionValid } from "@/components/MentionField";
import { AIPane } from "@/components/AIPane";
import { formatSaveStatus, useDraftAutosave } from "@/hooks/useDraftAutosave";
import { formatFullDateTime, relativeTime } from "@/lib/time";
import { useDashboard } from "@/pages/Dashboard";
import { HomeWelcomePane } from "@/pages/HomeWelcomePane";

// Sentinel: reply form after all posts
const REPLY_LAST = "__last__";

export function ThreadDetailPane() {
  const { category, slug } = useParams<{ category: string; slug: string }>();
  const { reloadLists } = useDashboard();
  const [data, setData] = useState<ThreadDetailData | null | undefined>(undefined);

  // AI pane visibility remains local to the current thread view. The actual
  // streaming state now lives above this component in Dashboard, so switching
  // threads no longer destroys the active AI output.
  const [aiOpen, setAiOpen] = useState(false);
  const [aiMounted, setAiMounted] = useState(false);
  const [aiPaneWidth, setAiPaneWidth] = useState(420);
  // Filename within current thread that the AI draft should reply under in UI ordering
  const [aiReplyAnchor, setAiReplyAnchor] = useState<string | null>(null);
  // Pending reply target (full path "cat/slug/file") to push to AIPane on open
  const [aiPendingReplyTarget, setAiPendingReplyTarget] = useState<string | null>(null);

  // Reply state lifted so content survives form open/close toggling
  const [replyAfter, setReplyAfter] = useState<string | null>(null);
  const [replyBody, setReplyBody] = useState("");
  const [replyMentions, setReplyMentions] = useState<MentionBlock>(emptyMention());
  const [replyDraftId, setReplyDraftId] = useState<string | null>(null);
  const [replyTo, setReplyTo] = useState<string | null>(null);
  const [replyReferences, setReplyReferences] = useState<string[]>([]);
  const [favoriteSaving, setFavoriteSaving] = useState(false);
  const [workspaceMirror, setWorkspaceMirror] = useState<WorkspaceMirrorConfig | null>(null);
  const detailLayoutRef = useRef<HTMLDivElement>(null);

  const hasDraft = replyBody.trim().length > 0;

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

  // Reset and pre-load existing reply draft when navigating to a thread
  useEffect(() => {
    setReplyAfter(null);
    setReplyBody("");
    setReplyMentions(emptyMention());
    setReplyDraftId(null);
    setReplyTo(null);
    setReplyReferences([]);
    setAiReplyAnchor(null);
    setAiOpen(false);
    setAiMounted(false);
    if (!category || !slug) return;
    const threadKey = `${category}/${slug}`;
    fetchDrafts()
      .then((items) => {
        const existing = items.find((d) => d.type === "reply" && d.thread_key === threadKey);
        if (existing && existing.body_md.trim()) {
          setReplyBody(existing.body_md);
          setReplyDraftId(existing.id);
          if (existing.mentions) setReplyMentions(existing.mentions);
          if (existing.reply_to) setReplyTo(existing.reply_to);
          setReplyReferences(existing.references ?? []);
          setReplyAfter(REPLY_LAST);
        }
      })
      .catch(() => {});
  }, [category, slug]);

  // Called when user clicks "AI 回复" on a specific post
  const openAIReply = (post: Post) => {
    const filePath = `${category}/${slug}/${post.filename}`;
    setAiReplyAnchor(post.filename);
    setAiPendingReplyTarget(filePath);
    setAiMounted(true);
    setAiOpen(true);
    if (hasDraft) setReplyAfter((prev) => prev ?? REPLY_LAST);
  };

  // Called when user clicks "AI 写回复" at the bottom — defaults to last post
  const openAIReplyLast = () => {
    setAiReplyAnchor(null);
    if (data && data.posts.length > 0) {
      const last = data.posts[data.posts.length - 1];
      setAiPendingReplyTarget(`${category}/${slug}/${last.filename}`);
    }
    setAiMounted(true);
    setAiOpen(true);
    if (hasDraft) setReplyAfter((prev) => prev ?? REPLY_LAST);
  };

  // Called by AIPane when it extracts a <draft> block. We persist FIRST, then mount
  // ReplyForm — this way ReplyForm's autosave never fires with a stale draftId=null
  // and creates a duplicate.
  const onUseDraftAsReply = async (
    content: string,
    aiReplyTo: string,
    aiReferences: string[],
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
          references: aiReferences,
        });
      } else {
        const d = await createDraft({
          type: "reply",
          body_md: content,
          thread_key: threadKey,
          reply_to: replyToFilename,
          references: aiReferences,
        });
        nextDraftId = d.id;
      }
    } catch {
      return false;
    }

    // Now that the draft is persisted, flip UI state. ReplyForm mounts with
    // draftId already set so its autosave never tries to create another one.
    if (nextDraftId !== replyDraftId) setReplyDraftId(nextDraftId);
    setReplyBody(content);
    setReplyTo(replyToFilename);
    setReplyReferences(aiReferences);
    const anchor = aiReplyAnchor || REPLY_LAST;
    setReplyAfter(anchor);
    setTimeout(() => {
      document.getElementById(`reply-anchor-${anchor}`)
        ?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 50);
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
      setReplyAfter(null);
      setReplyBody("");
      setReplyMentions(emptyMention());
      setReplyDraftId(null);
      setReplyTo(null);
      setReplyReferences([]);
      load();
      reloadLists();
    },
    onCancel: () => setReplyAfter(null),
  };

  const threadKey = `${category}/${slug}`;
  const favorite = data.meta.favorite;

  const startAIPaneResize = (event: React.MouseEvent<HTMLDivElement>) => {
    event.preventDefault();
    const layout = detailLayoutRef.current;
    if (!layout) return;
    const rect = layout.getBoundingClientRect();
    const minWidth = 320;
    const maxWidth = Math.min(760, rect.width - 320);

    const onMove = (moveEvent: MouseEvent) => {
      const next = Math.min(Math.max(rect.right - moveEvent.clientX, minWidth), maxWidth);
      setAiPaneWidth(next);
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

  return (
    <div ref={detailLayoutRef} className="flex h-full min-h-0 flex-col overflow-hidden md:flex-row">
      {/* Posts column */}
      <div className={`min-h-0 overflow-y-auto ${aiOpen ? "flex-1 min-w-0" : "w-full"}`}>
        <div className="mx-auto max-w-3xl px-4 py-5 sm:px-6 lg:px-8 lg:py-6">

          <div className="mb-4 lg:hidden">
            <Button asChild variant="ghost" size="sm" className="h-8 px-2 text-xs">
              <Link to="/">
                <ChevronLeft className="h-4 w-4" />
                返回讨论列表
              </Link>
            </Button>
          </div>

          {/* Thread header */}
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-xl font-semibold sm:text-2xl">{data.meta.title}</h1>
            <StatusControl
              status={data.meta.status}
              onChange={async (to, reason) => {
                if (!category || !slug) return;
                await changeThreadStatus(category, slug, to, reason);
                load();
                reloadLists();
              }}
            />
            <Button
              variant={favorite ? "secondary" : "ghost"}
              size="sm"
              className="h-8 px-2 text-xs"
              disabled={favoriteSaving}
              onClick={async () => {
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
              title={favorite ? "取消收藏" : "收藏"}
            >
              <Star className={`h-4 w-4 ${favorite ? "fill-current text-amber-500" : ""}`} />
              {favorite ? "已收藏" : "收藏"}
            </Button>
            <Button
              variant={aiOpen ? "secondary" : "ghost"}
              size="sm"
              className="ml-auto h-7 px-2 text-xs"
              onClick={() => {
                if (!aiOpen) setAiMounted(true);
                setAiOpen((o) => !o);
              }}
              title="AI 助手"
            >
              <Bot className="mr-1 h-3.5 w-3.5" />
              AI 助手
            </Button>
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            {data.meta.category} · {data.meta.author_display ?? data.meta.author ?? "unknown"} · {data.meta.post_count} posts
            {data.meta.last_updated && ` · last activity ${relativeTime(data.meta.last_updated)}`}
          </div>

          {/* Posts */}
          <div className="mt-6 space-y-4">
            {data.posts.map((p, index) => (
              <div key={p.filename}>
                <PostCard
                  post={p}
                  postNumber={index + 1}
                  category={category!}
                  slug={slug!}
                  githubFileUrl={buildGitHubFileUrl(
                    workspaceMirror?.repo_url ?? null,
                    workspaceMirror?.head ?? workspaceMirror?.branch ?? null,
                    category!,
                    slug!,
                    p.filename,
                  )}
                  isReplyOpen={replyAfter === p.filename}
                  onAIReply={() => openAIReply(p)}
                  onMentioned={load}
                />
                {replyAfter === p.filename && (
                  <div id={`reply-anchor-${p.filename}`} className="mt-3">
                    <ReplyForm {...replyFormProps} />
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Bottom: "AI 写回复" or reply form */}
          <div id={`reply-anchor-${REPLY_LAST}`} className="mt-8 pb-6">
            {replyAfter === REPLY_LAST ? (
              <ReplyForm {...replyFormProps} />
            ) : (
              <div className="flex justify-center">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={openAIReplyLast}
                  className={hasDraft ? "border-orange-300 text-orange-600 hover:bg-orange-50" : ""}
                >
                  <Bot className="mr-2 h-4 w-4" />
                  {hasDraft ? "继续 AI 回复 ●" : "AI 写回复"}
                </Button>
              </div>
            )}
          </div>

        </div>
      </div>

      {/* AI pane — kept mounted once opened so background streaming survives close */}
    {aiMounted && (
      <>
        {aiOpen && (
          <div
            className="group hidden w-2 shrink-0 cursor-col-resize items-stretch justify-center border-l bg-muted/20 transition-colors hover:bg-muted/35 md:flex"
            onMouseDown={startAIPaneResize}
            title="拖拽调整 AI 对话框宽度"
          >
            <div className="pointer-events-none flex items-center text-muted-foreground/80 group-hover:text-foreground">
              <GripVertical className="h-3.5 w-3.5" />
            </div>
          </div>
        )}
          <div
            className={
              aiOpen
                ? "flex min-h-0 w-full flex-col overflow-hidden border-t md:shrink-0 md:self-stretch md:border-l md:border-t-0"
                : "hidden"
            }
            style={aiOpen ? { width: aiPaneWidth } : undefined}
          >
            <AIPane
              category={category!}
              slug={slug!}
              threadKey={threadKey}
              threadTitle={data.meta.title}
              pendingReplyTarget={aiPendingReplyTarget}
              onPendingReplyTargetConsumed={() => setAiPendingReplyTarget(null)}
              onClose={() => setAiOpen(false)}
              onUseDraftAsReply={onUseDraftAsReply}
              hasReplyDraft={hasDraft}
            />
          </div>
        </>
      )}
    </div>
  );
}

const COLLAPSE_HEIGHT = 208;

function PostCard({
  post, postNumber, category, slug, githubFileUrl, isReplyOpen, onAIReply, onMentioned,
}: {
  post: Post;
  postNumber: number;
  category: string;
  slug: string;
  githubFileUrl: string | null;
  isReplyOpen: boolean;
  onAIReply: () => void;
  onMentioned: () => void;
}) {
  const author = post.author_display ?? (post.frontmatter.author as string) ?? "unknown";
  const type = (post.frontmatter.type as string) ?? "";
  const created = post.frontmatter.created as string | null ?? null;
  const actionLabel = type === "reply" ? "回复" : "发布";
  const typeLabel = type === "reply" ? "回复" : type === "proposal" ? "提案" : type;
  const typeBadgeClass = type === "reply"
    ? "bg-blue-50 text-blue-700 ring-blue-200"
    : "bg-amber-50 text-amber-700 ring-amber-200";

  const bodyRef = useRef<HTMLDivElement>(null);
  const [overflows, setOverflows] = useState(false);
  const [collapsed, setCollapsed] = useState(true);

  useLayoutEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    setOverflows(el.scrollHeight > el.clientHeight + 2);
  }, [post.body]);

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

  const aiReplyBtnClass = isReplyOpen
    ? "h-7 px-2 text-xs bg-blue-50 text-blue-700 border border-blue-200 hover:bg-blue-100"
    : "h-7 px-2 text-xs";

  return (
    <Card className="border-l-4 border-l-muted">
      <div className="p-4 sm:p-5">
        <div className="mb-2 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset ${typeBadgeClass}`}>
                {typeLabel}
              </span>
              <span className="text-lg font-semibold tracking-tight text-foreground sm:text-xl">
                {author}
              </span>
              <span className="text-sm text-muted-foreground">
                {actionLabel} 第 {postNumber} 条帖子
                {created ? ` 于 ${formatFullDateTime(created)}` : ""}
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs leading-relaxed text-muted-foreground">
              {githubFileUrl ? (
                <a
                  href={githubFileUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="font-mono underline decoration-muted-foreground/50 underline-offset-2 hover:text-foreground"
                >
                  {post.filename}
                </a>
              ) : (
                <span className="font-mono">{post.filename}</span>
              )}
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-1 sm:justify-end">
            {!collapsed && overflows && (
              <button
                onClick={() => setCollapsed(true)}
                className="h-7 px-2 text-xs text-primary hover:underline focus:outline-none motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-top-1 motion-safe:duration-200"
              >
                收起全文 ↑
              </button>
            )}
            <Button
              variant="ghost"
              size="sm"
              className={aiReplyBtnClass}
              onClick={onAIReply}
            >
              <Bot className="mr-1 h-3.5 w-3.5" />
              AI 回复
            </Button>
            <div className="relative" ref={popoverRef}>
              <Button
                variant="ghost" size="sm" className="h-7 px-2 text-xs"
                onClick={() => setMentionOpen((o) => !o)}
              >
                <AtSign className="mr-1 h-3.5 w-3.5" /> 提及
              </Button>
              {mentionOpen && (
                <div className="fixed inset-x-4 top-20 z-50 rounded-lg border bg-white p-4 shadow-lg dark:bg-zinc-900 sm:absolute sm:inset-x-auto sm:right-0 sm:top-full sm:mt-1 sm:w-[min(20rem,calc(100vw-2rem))]">
                  <p className="mb-3 text-xs font-semibold text-muted-foreground">提及某人</p>
                  <MentionField
                    value={mentionValue}
                    onChange={setMentionValue}
                    resolvedNames={resolvedNames.current}
                  />
                  <div className="mt-3 flex justify-end gap-2">
                    <Button
                      size="sm" variant="outline"
                      onClick={() => { setMentionOpen(false); setMentionValue(emptyMention()); }}
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
          </div>
        </div>

        {post.mentions.length > 0 && (
          <div className="mb-3 space-y-1.5">
            {post.mentions.map((m, i) => (
              <MentionChip key={i} mention={m} />
            ))}
          </div>
        )}

        <div
          ref={bodyRef}
          style={collapsed ? { maxHeight: COLLAPSE_HEIGHT, overflow: "hidden" } : undefined}
          className="prose-pivot"
        >
          <Markdown remarkPlugins={[remarkGfm]}>{post.body}</Markdown>
        </div>
        {overflows && (
          <button
            onClick={() => setCollapsed((c) => !c)}
            className="mt-1.5 text-xs text-primary hover:underline focus:outline-none"
          >
            {collapsed ? "展开全文 ↓" : "收起全文 ↑"}
          </button>
        )}
      </div>
    </Card>
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

function MentionChip({ mention }: { mention: MentionEntry }) {
  const names = mention.users.map((u) => u.user).join("、");
  return (
    <div className="flex items-start gap-2 rounded-md bg-muted/50 px-3 py-1.5 text-xs">
      <AtSign className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      <div className="min-w-0">
        <span className="font-medium">{names}</span>
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
  category, slug, body, setBody, mentions, setMentions, draftId, setDraftId,
  replyTo, references, onPosted, onCancel,
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
  onCancel: () => void;
}) {
  const threadKey = `${category}/${slug}`;
  const resolvedNames = useRef<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);

  const { status, saveNow } = useDraftAutosave({
    draftId, setDraftId,
    type: "reply",
    payload: () => ({
      body_md: body, thread_key: threadKey,
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
    <Card>
      <form onSubmit={submit} className="space-y-3 p-4 sm:p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div className="flex items-baseline gap-3">
            <h3 className="font-semibold">回复</h3>
            <span className={`text-xs ${status === "error" ? "text-destructive" : "text-muted-foreground"}`}>
              {formatSaveStatus(status)}
            </span>
          </div>
          <Button type="button" variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={onCancel}>
            收起
          </Button>
        </div>
        <Textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={6}
          maxLength={50000}
          placeholder="AI 生成的回复草稿，可在此编辑…"
          className="font-mono text-sm"
          autoFocus
        />
        <MentionField
          value={mentions} onChange={setMentions}
          resolvedNames={resolvedNames.current}
        />
        <div className="flex flex-wrap gap-3">
          <Button type="submit" disabled={submitting || !body.trim()}>
            {submitting ? "发布中…" : "发布回复"}
          </Button>
          {(draftId || body.trim()) && (
            <Button type="button" variant="outline" onClick={discard}>
              删除草稿
            </Button>
          )}
        </div>
      </form>
    </Card>
  );
}

export function ThreadDetailEmpty() {
  return <HomeWelcomePane />;
}
