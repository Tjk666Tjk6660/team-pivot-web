import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  AlertCircle,
  Bot,
  BookOpen,
  CheckCircle2,
  ChevronRight,
  FileText,
  List,
  Loader2,
  Search,
  Send,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useDashboard, type AIMsg } from "@/pages/Dashboard";
import type { AIToolUse } from "@/api";

const GENERATE_TAG = "[[GENERATE_REPLY_DRAFT]]";

export function AIPane({
  category,
  slug,
  threadKey,
  threadTitle,
  onUseDraftAsReply,
  pendingReplyTarget,
  onPendingReplyTargetConsumed,
  hasReplyDraft,
}: {
  category: string;
  slug: string;
  threadKey: string;
  threadTitle: string;
  onUseDraftAsReply: (content: string, replyTo: string) => Promise<boolean>;
  pendingReplyTarget?: string | null;
  onPendingReplyTargetConsumed?: () => void;
  hasReplyDraft: boolean;
}) {
  const { ai } = useDashboard();
  const state = ai.getThreadState(threadKey);
  const { messages, replyTarget, input, streaming, loading } = state;

  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const composerRef = useRef<HTMLDivElement>(null);

  const activeStream = ai.activeStream;
  const blockedByOtherThread = !!activeStream && activeStream.threadKey !== threadKey;
  const activeThreadTitle = activeStream?.title ?? "";

  useEffect(() => {
    void ai.ensureThreadLoaded(category, slug, threadKey);
  }, [ai, category, slug, threadKey]);

  useEffect(() => {
    if (!pendingReplyTarget || loading) return;
    ai.setReplyTarget(category, slug, threadKey, pendingReplyTarget);
    onPendingReplyTargetConsumed?.();
    setTimeout(() => inputRef.current?.focus(), 50);
  }, [ai, category, slug, threadKey, pendingReplyTarget, onPendingReplyTargetConsumed, loading]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const ensureComposerVisible = () => {
      requestAnimationFrame(() => {
        composerRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      });
    };
    const viewport = window.visualViewport;
    viewport?.addEventListener("resize", ensureComposerVisible);
    return () => viewport?.removeEventListener("resize", ensureComposerVisible);
  }, []);

  const handleSend = async () => {
    if (blockedByOtherThread) return;
    await ai.sendMessage({
      category,
      slug,
      threadKey,
      threadTitle,
      rawText: input,
      hasReplyDraft,
      onUseDraftAsReply,
    });
  };

  const handleGenerateDraft = async () => {
    if (blockedByOtherThread || !replyTarget) return;
    const target = replyTarget.split("/").pop() ?? replyTarget;
    await ai.sendMessage({
      category,
      slug,
      threadKey,
      threadTitle,
      rawText: `${GENERATE_TAG} 请根据以上对话，生成针对「${target}」的完整回复正文，整个正文必须用 <draft type="think">...</draft> 标签包裹。`,
      hasReplyDraft,
      onUseDraftAsReply,
    });
  };

  const noTarget = !replyTarget;
  const noUserMsg = messages.filter((m) => m.role === "user").length === 0;
  const interactionsDisabled = blockedByOtherThread || loading;
  const sendDisabled = interactionsDisabled || streaming || noTarget || !input.trim();
  const generateDisabled = interactionsDisabled || streaming || noTarget || noUserMsg;

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-hidden">
      {blockedByOtherThread && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800">
          <div className="flex items-start gap-2">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <div className="font-medium">AI 输出被其他 thread 占用</div>
              <div className="mt-1 leading-relaxed">
                《{activeThreadTitle}》正在输出，请等待它完成后再尝试。
              </div>
            </div>
          </div>
        </div>
      )}

      {replyTarget && (
        <div
          className="shrink-0 rounded-xl border border-blue-200/80 bg-blue-50/80 px-3 py-2 text-xs text-blue-900"
          title={replyTarget}
        >
          <div className="flex items-center gap-2">
            <FileText className="h-3.5 w-3.5 shrink-0 text-blue-600" />
            <span className="shrink-0 font-medium">起点帖子</span>
            <span className="truncate font-mono text-[11px] text-blue-800">
              {replyTarget.split("/").pop() ?? replyTarget}
            </span>
          </div>
        </div>
      )}

      <div
        ref={scrollRef}
        className="min-h-[12rem] flex-1 space-y-3 overflow-y-auto rounded-xl border border-slate-200/80 bg-white/80 px-4 py-4"
      >
        {loading && (
          <p className="pt-4 text-center text-xs text-muted-foreground">加载历史记录…</p>
        )}
        {!loading && messages.length === 0 && (
          <p className="pt-4 text-center text-xs text-muted-foreground">
            {noTarget
              ? "还未指定起点帖子。请从某条帖子卡片上点击「AI 回复」进入。"
              : "可以先提问、总结，或者让 AI 帮你生成回复草稿。"}
          </p>
        )}
        {messages.map((m) => (
          <AIMessageBubble key={m.id} msg={m} />
        ))}
      </div>

      <div ref={composerRef} className="shrink-0 rounded-xl border border-slate-200/80 bg-slate-50/80 p-3.5 pb-5">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-sm font-medium text-slate-800">
            <Bot className="h-4 w-4 text-blue-600" />
            AI 助手
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="default"
              className="h-8 rounded-lg bg-blue-600 px-3 hover:bg-blue-700"
              disabled={generateDisabled}
              onClick={() => void handleGenerateDraft()}
              title={
                blockedByOtherThread
                  ? `《${activeThreadTitle}》正在输出`
                  : noTarget
                    ? "未指定起点帖子"
                    : noUserMsg
                      ? "请先和 AI 至少聊一句"
                      : "根据当前讨论生成完整回复草稿"
              }
            >
              <Sparkles className="mr-1.5 h-4 w-4" />
              生成草稿
            </Button>
            {messages.length > 0 && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-8 rounded-lg px-3 text-xs text-slate-600"
                onClick={() => void ai.clearThreadConversation(category, slug, threadKey)}
                disabled={blockedByOtherThread || streaming}
              >
                清空对话
              </Button>
            )}
            <Button
              size="sm"
              onClick={() => void handleSend()}
              disabled={sendDisabled}
              className="h-8 rounded-lg bg-blue-600 px-3 hover:bg-blue-700"
            >
              <Send className="mr-1.5 h-4 w-4" />
              发送
            </Button>
          </div>
        </div>

        <div>
          <Textarea
            ref={inputRef}
            value={input}
            onChange={(e) => ai.setInput(threadKey, e.target.value)}
            onFocus={() => {
              requestAnimationFrame(() => {
                composerRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
              });
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                void handleSend();
              }
            }}
            placeholder={
              blockedByOtherThread
                ? `《${activeThreadTitle}》正在输出，请稍后…`
                : noTarget
                  ? "未指定起点帖子（请从某条帖子点击「AI 回复」进入）"
                  : "询问问题、提炼结论，或让 AI 帮你生成这条回复…"
            }
            rows={4}
            disabled={blockedByOtherThread || streaming || noTarget}
            className="min-h-[9.5rem] w-full resize-none rounded-xl border-slate-300 bg-white text-sm"
          />
        </div>
      </div>
    </div>
  );
}

function AIMessageBubble({ msg }: { msg: AIMsg }) {
  const isUser = msg.role === "user";
  const display = isUser ? msg.content.replace(GENERATE_TAG, "🎯").trim() : msg.content;
  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[88%] whitespace-pre-wrap rounded-2xl bg-slate-900 px-3.5 py-2.5 text-sm text-white">
          {display}
        </div>
      </div>
    );
  }
  return (
    <div>
      {msg.toolUses && msg.toolUses.length > 0 && <ToolUseTimeline tools={msg.toolUses} />}
      <div className="paper-panel prose-pivot max-w-none overflow-hidden rounded-2xl border px-4 py-3 text-sm text-slate-700">
        {msg.content ? (
          <Markdown
            remarkPlugins={[remarkGfm]}
            components={{
              table: ({ node: _node, ...props }) => (
                <div className="table-scroll">
                  <table {...props} />
                </div>
              ),
            }}
          >
            {display}
          </Markdown>
        ) : (
          <span className="animate-pulse text-muted-foreground">▌</span>
        )}
      </div>
    </div>
  );
}

function ToolUseTimeline({ tools }: { tools: AIToolUse[] }) {
  const allDone = tools.every((t) => t.output_summary);
  const [expanded, setExpanded] = useState(false);
  const [startAt, setStartAt] = useState<number | null>(null);
  const [endAt, setEndAt] = useState<number | null>(null);

  useEffect(() => {
    if (tools.length > 0 && startAt === null) setStartAt(Date.now());
  }, [tools.length, startAt]);

  useEffect(() => {
    if (allDone && startAt !== null && endAt === null) setEndAt(Date.now());
  }, [allDone, startAt, endAt]);

  const currentTool = tools.find((t) => !t.output_summary) ?? tools[tools.length - 1];
  const headerLabel = allDone
    ? startAt !== null && endAt !== null
      ? `查阅了 ${((endAt - startAt) / 1000).toFixed(2)}s`
      : `已读 ${tools.length} 项`
    : `正在读 ${currentTool ? fullActionText(currentTool) : "…"}`;

  return (
    <div className="mb-1.5 max-w-xl rounded-lg border border-slate-200/80 bg-slate-50/70 text-[11px] text-slate-500">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between gap-2 px-2.5 py-1.5 hover:bg-slate-100/70"
      >
        <span className="flex min-w-0 items-center gap-1.5">
          {allDone ? (
            <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-500" />
          ) : (
            <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-slate-400" />
          )}
          <span className="truncate" title={headerLabel}>{headerLabel}</span>
        </span>
        <ChevronRight
          className={`h-3 w-3 shrink-0 text-slate-400 transition-transform ${expanded ? "rotate-90" : ""}`}
        />
      </button>
      {expanded && (
        <ol className="relative space-y-1.5 border-t border-slate-200/80 px-3 py-2 pl-6">
          <span
            aria-hidden
            className="absolute left-[11.5px] top-4 bottom-4 border-l border-dashed border-slate-300"
          />
          {tools.map((t, idx) => (
            <TimelineRow key={`${t.id}-${idx}`} tool={t} />
          ))}
        </ol>
      )}
    </div>
  );
}

function fullActionText(t: AIToolUse): string {
  switch (t.name) {
    case "list_thread_titles":
      return "所有 thread 列表";
    case "search_indexes": {
      const kw = typeof t.arguments?.keyword === "string" ? t.arguments.keyword : "";
      return kw ? `搜索「${kw}」` : "搜索 index";
    }
    case "read_thread_index": {
      const slug =
        typeof t.arguments?.thread_slug === "string" ? t.arguments.thread_slug : "";
      return slug ? `index: ${slug}` : "index";
    }
    case "read_post": {
      const path = typeof t.arguments?.path === "string" ? t.arguments.path : "";
      return path ? path.split("/").pop() || path : "帖子";
    }
    default:
      return t.name;
  }
}

function TimelineRow({ tool }: { tool: AIToolUse }) {
  const s = describeToolCall(tool);
  const pending = !tool.output_summary;
  return (
    <li className="relative flex items-center gap-2">
      <span
        aria-hidden
        className={`absolute -left-[15px] top-1/2 h-1.5 w-1.5 -translate-y-1/2 rounded-full ring-2 ring-slate-50/70 ${
          pending ? "bg-slate-300 animate-pulse" : "bg-emerald-500"
        }`}
      />
      <span
        className={`inline-flex min-w-0 max-w-full items-center gap-1.5 rounded px-1.5 py-0.5 ring-1 ring-inset ${s.tone}`}
        title={s.title}
      >
        <s.Icon className={`h-3 w-3 shrink-0 ${s.iconTone}`} />
        <span className="truncate">{s.label}</span>
      </span>
      {pending && <span className="shrink-0 animate-pulse text-slate-400">…</span>}
    </li>
  );
}

type ChipStyle = {
  Icon: typeof Search;
  tone: string;
  iconTone: string;
  label: string;
  title: string;
};

function describeToolCall(t: AIToolUse): ChipStyle {
  switch (t.name) {
    case "list_thread_titles":
      return {
        Icon: List,
        tone: "bg-violet-50 text-violet-700 ring-violet-200/60",
        iconTone: "text-violet-500",
        label: "列出全部 thread",
        title: "list_thread_titles",
      };
    case "search_indexes": {
      const kw = typeof t.arguments?.keyword === "string" ? t.arguments.keyword : "";
      return {
        Icon: Search,
        tone: "bg-amber-50 text-amber-800 ring-amber-200/60",
        iconTone: "text-amber-500",
        label: kw || "搜索",
        title: kw ? `search_indexes("${kw}")` : "search_indexes",
      };
    }
    case "read_thread_index": {
      const slug =
        typeof t.arguments?.thread_slug === "string" ? t.arguments.thread_slug : "";
      return {
        Icon: BookOpen,
        tone: "bg-sky-50 text-sky-800 ring-sky-200/60",
        iconTone: "text-sky-500",
        label: truncateMiddle(slug, 24) || "index",
        title: slug ? `read_thread_index(${slug})` : "read_thread_index",
      };
    }
    case "read_post": {
      const path = typeof t.arguments?.path === "string" ? t.arguments.path : "";
      const filename = path.split("/").pop() ?? path;
      return {
        Icon: FileText,
        tone: "bg-slate-100 text-slate-700 ring-slate-200/70",
        iconTone: "text-slate-500",
        label: prettifyPostFilename(filename) || "post",
        title: path || "read_post",
      };
    }
    default:
      return {
        Icon: FileText,
        tone: "bg-slate-100 text-slate-600 ring-slate-200/70",
        iconTone: "text-slate-400",
        label: t.name,
        title: t.name,
      };
  }
}

function prettifyPostFilename(name: string): string {
  // 003_yuebilin_reply_c5f224.md -> 003 yuebilin reply
  const stripped = name.replace(/\.md$/i, "").replace(/_[a-f0-9]{6}$/i, "");
  return stripped.replace(/_/g, " ");
}

function truncateMiddle(s: string, max: number): string {
  if (s.length <= max) return s;
  const side = Math.max(3, Math.floor((max - 1) / 2));
  return `${s.slice(0, side)}…${s.slice(s.length - side)}`;
}
