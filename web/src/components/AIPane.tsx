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

// Rotating hints shown in the textarea placeholder while AI is streaming —
// keeps the "等待间隙" 不空，给点 Coda/书信体气质的提示。
const STREAMING_HINTS = [
  "正在对齐颗粒度…",
  "正在追溯线索…",
  "正在校对引用…",
  "正在编织上下文…",
  "正在斟酌措辞…",
  "正在权衡分歧…",
  "正在拼装结论…",
  "正在润色草稿…",
];

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
  const { messages, replyTarget, input, streaming, loading, loaded } = state;

  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const composerRef = useRef<HTMLDivElement>(null);

  const [streamingHintIdx, setStreamingHintIdx] = useState(0);
  useEffect(() => {
    if (!streaming) return;
    setStreamingHintIdx(Math.floor(Math.random() * STREAMING_HINTS.length));
    const id = window.setInterval(() => {
      setStreamingHintIdx((i) => (i + 1) % STREAMING_HINTS.length);
    }, 2400);
    return () => window.clearInterval(id);
  }, [streaming]);

  const activeStream = ai.activeStream;
  const blockedByOtherThread = !!activeStream && activeStream.threadKey !== threadKey;
  const activeThreadTitle = activeStream?.title ?? "";

  useEffect(() => {
    void ai.ensureThreadLoaded(category, slug, threadKey);
  }, [ai, category, slug, threadKey]);

  useEffect(() => {
    if (!pendingReplyTarget || !loaded) return;
    ai.setReplyTarget(category, slug, threadKey, pendingReplyTarget);
    onPendingReplyTargetConsumed?.();
    setTimeout(() => inputRef.current?.focus(), 50);
  }, [ai, category, slug, threadKey, pendingReplyTarget, onPendingReplyTargetConsumed, loaded]);

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
    <div
      className="flex h-full min-h-0 flex-col gap-2.5 overflow-hidden p-2 sm:gap-3 sm:p-4"
      style={{ background: "var(--bg-alt)" }}
    >
      {blockedByOtherThread && (
        <div
          className="rounded-[var(--r-md)] px-4 py-3 text-[12px]"
          style={{
            border: "1px solid color-mix(in srgb, var(--warn-500) 35%, var(--line))",
            background: "color-mix(in srgb, var(--warn-500) 8%, var(--surface))",
            color: "var(--warn-600)",
          }}
        >
          <div className="flex items-start gap-2">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <div className="font-semibold">AI 输出被其他 thread 占用</div>
              <div className="mt-1 leading-relaxed">
                《{activeThreadTitle}》正在输出，请等待它完成后再尝试。
              </div>
            </div>
          </div>
        </div>
      )}

      {replyTarget && (
        <div
          className="shrink-0 rounded-[var(--r-md)] px-3 py-2 text-[11.5px]"
          style={{
            border: "1px solid var(--accent-soft)",
            background: "var(--accent-bg)",
            color: "var(--accent)",
          }}
          title={replyTarget}
        >
          <div className="flex items-center gap-2">
            <FileText className="h-3.5 w-3.5 shrink-0" />
            <span className="shrink-0 font-semibold">起点帖子</span>
            <span className="truncate font-mono text-[11px]">
              {replyTarget.split("/").pop() ?? replyTarget}
            </span>
          </div>
        </div>
      )}

      <div
        ref={scrollRef}
        className="min-h-[12rem] flex-1 space-y-3 overflow-y-auto rounded-[var(--r-md)] px-2.5 py-3 sm:px-4 sm:py-4"
        style={{
          border: "1px solid var(--line)",
          background: "var(--surface)",
        }}
      >
        {loading && (
          <p
            className="pt-4 text-center text-[11.5px] font-meta"
            style={{ color: "var(--text-mute)" }}
          >
            加载历史记录…
          </p>
        )}
        {!loading && messages.length === 0 && (
          <p
            className="pt-4 text-center text-[11.5px] font-serif-body italic"
            style={{ color: "var(--text-mute)" }}
          >
            {noTarget
              ? "还未指定起点帖子。请从某条帖子卡片上点击「AI 回复」进入。"
              : "可以先提问、总结，或者让 AI 帮你生成回复草稿。"}
          </p>
        )}
        {messages.map((m, idx) => {
          const isLastEmptyAssistant =
            streaming &&
            idx === messages.length - 1 &&
            m.role === "assistant" &&
            !m.content;
          return (
            <AIMessageBubble
              key={m.id}
              msg={m}
              streamingHint={isLastEmptyAssistant ? STREAMING_HINTS[streamingHintIdx] : undefined}
            />
          );
        })}
      </div>

      <div
        ref={composerRef}
        className="shrink-0 rounded-[var(--r-md)] p-2.5 pb-3 sm:p-3.5 sm:pb-5"
        style={{
          border: "1px solid var(--line)",
          background: "var(--surface-alt)",
        }}
      >
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div
            className="flex items-center gap-2 text-[13px] font-semibold font-serif-body"
            style={{ color: "var(--text)" }}
          >
            <Bot className="h-4 w-4" style={{ color: "var(--accent)" }} />
            AI 助手
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="default"
              className="h-8 rounded-md px-3 text-[12.5px] font-semibold shadow-none"
              style={{
                background: generateDisabled ? "var(--surface)" : "var(--accent)",
                color: generateDisabled ? "var(--text-fade)" : "var(--accent-ink)",
                border: `1px solid ${generateDisabled ? "var(--line)" : "var(--accent)"}`,
              }}
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
              <Sparkles className="mr-1.5 h-3.5 w-3.5" />
              生成草稿
            </Button>
            {messages.length > 0 && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-8 rounded-md px-3 text-[12px]"
                style={{ color: "var(--text-soft)" }}
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
              className="h-8 rounded-md px-3 text-[12.5px] font-semibold shadow-none"
              style={{
                background: sendDisabled ? "var(--surface)" : "var(--accent)",
                color: sendDisabled ? "var(--text-fade)" : "var(--accent-ink)",
                border: `1px solid ${sendDisabled ? "var(--line)" : "var(--accent)"}`,
              }}
            >
              <Send className="mr-1.5 h-3.5 w-3.5" />
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
            className="min-h-[9.5rem] w-full resize-none rounded-[var(--r-md)] text-[13px]"
            style={{
              background: "var(--surface)",
              border: "1px solid var(--line-strong)",
              color: "var(--text)",
            }}
          />
        </div>
      </div>
    </div>
  );
}

function AIMessageBubble({
  msg,
  streamingHint,
}: {
  msg: AIMsg;
  streamingHint?: string;
}) {
  const isUser = msg.role === "user";
  const display = isUser ? msg.content.replace(GENERATE_TAG, "🎯").trim() : msg.content;
  if (isUser) {
    return (
      <div className="flex justify-end">
        <div
          className="max-w-[88%] whitespace-pre-wrap rounded-[var(--r-md)] px-3.5 py-2.5 text-[13px] leading-[1.55]"
          style={{
            background: "var(--accent)",
            color: "var(--accent-ink)",
            border: "1px solid var(--accent)",
            boxShadow: "var(--shadow-sm)",
          }}
        >
          {display}
        </div>
      </div>
    );
  }
  return (
    <div>
      {msg.toolUses && msg.toolUses.length > 0 && <ToolUseTimeline tools={msg.toolUses} />}
      <div
        className="prose-pivot max-w-none overflow-hidden rounded-[var(--r-md)] px-4 py-3 text-[13.5px]"
        style={{
          background: "var(--surface)",
          border: "1px solid var(--line)",
          borderLeft: "3px solid var(--accent)",
          color: "var(--text)",
        }}
      >
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
          <span
            className="inline-flex items-center gap-1.5 italic font-serif-body"
            style={{ color: "var(--text-mute)" }}
          >
            {streamingHint ?? "正在等待回应…"}
            <span className="animate-pulse" aria-hidden>▌</span>
          </span>
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
    <div
      className="mb-1.5 max-w-xl rounded-md text-[11px] font-meta"
      style={{
        border: "1px solid var(--line)",
        background: "var(--surface-alt)",
        color: "var(--text-mute)",
      }}
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between gap-2 px-2.5 py-1.5 hover:bg-[var(--bg-alt)]"
      >
        <span className="flex min-w-0 items-center gap-1.5">
          {allDone ? (
            <CheckCircle2 className="h-3.5 w-3.5 shrink-0" style={{ color: "var(--ok-500)" }} />
          ) : (
            <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" style={{ color: "var(--text-fade)" }} />
          )}
          <span className="truncate" title={headerLabel}>{headerLabel}</span>
        </span>
        <ChevronRight
          className={`h-3 w-3 shrink-0 transition-transform ${expanded ? "rotate-90" : ""}`}
          style={{ color: "var(--text-fade)" }}
        />
      </button>
      {expanded && (
        <ol
          className="relative space-y-1.5 px-3 py-2 pl-6"
          style={{ borderTop: "1px solid var(--line)" }}
        >
          <span
            aria-hidden
            className="absolute left-[11.5px] top-4 bottom-4 border-l border-dashed"
            style={{ borderColor: "var(--line-strong)" }}
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
