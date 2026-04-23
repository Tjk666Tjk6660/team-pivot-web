import { useEffect, useRef } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { AlertCircle, Bot, Send, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useDashboard } from "@/pages/Dashboard";

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
  onUseDraftAsReply: (content: string, replyTo: string, references: string[]) => Promise<boolean>;
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
    if (blockedByOtherThread) return;
    const targetHint = replyTarget
      ? `「${replyTarget.split("/").pop() ?? replyTarget}」`
      : "当前讨论";
    await ai.sendMessage({
      category,
      slug,
      threadKey,
      threadTitle,
      rawText: `${GENERATE_TAG} 请根据以上对话，生成针对${targetHint}的完整回复草稿，整个正文必须用 <draft>...</draft> 标签包裹。`,
      hasReplyDraft,
      onUseDraftAsReply,
    });
  };

  const noUserMsg = messages.filter((m) => m.role === "user").length === 0;
  const interactionsDisabled = blockedByOtherThread || loading;
  const sendDisabled = interactionsDisabled || streaming || !input.trim();
  const generateDisabled = interactionsDisabled || streaming || noUserMsg;

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-hidden">
      {blockedByOtherThread && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800">
          <div className="flex items-start gap-2">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <div className="font-medium">AI 输出被其他对话占用</div>
              <div className="mt-1 leading-relaxed">
                《{activeThreadTitle}》正在输出，请等待它完成后再尝试。
              </div>
            </div>
          </div>
        </div>
      )}

      <div
        ref={scrollRef}
        className="flex min-h-[12rem] flex-1 flex-col gap-3 overflow-y-auto rounded-2xl border border-slate-200/80 bg-slate-50/60 px-4 py-4"
      >
        {loading && (
          <p className="m-auto text-center text-xs text-muted-foreground">加载历史记录…</p>
        )}
        {!loading && messages.length === 0 && (
          <p className="m-auto max-w-[22rem] text-center text-sm text-slate-400">
            可以先提问、总结，或者让 AI 帮你生成回复草稿。
          </p>
        )}
        {messages.map((m) => {
          const isUser = m.role === "user";
          const display = isUser ? m.content.replace(GENERATE_TAG, "🎯").trim() : m.content;
          return (
            <div key={m.id} className={isUser ? "flex justify-end" : ""}>
              {isUser ? (
                <div className="max-w-[88%] whitespace-pre-wrap rounded-2xl bg-slate-900 px-3.5 py-2.5 text-sm text-white">
                  {display}
                </div>
              ) : (
                <div className="paper-panel prose-pivot max-w-none rounded-2xl border px-4 py-3 text-sm text-slate-700">
                  {m.content ? (
                    <Markdown remarkPlugins={[remarkGfm]}>{display}</Markdown>
                  ) : (
                    <span className="animate-pulse text-muted-foreground">▌</span>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div ref={composerRef} className="shrink-0 rounded-2xl border border-slate-200/80 bg-slate-50/80 p-3.5">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-sm font-medium text-slate-800">
            <Bot className="h-4 w-4 text-blue-600" />
            AI 助手
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="secondary"
              className="h-8 rounded-lg bg-blue-100 px-3 text-blue-700 hover:bg-blue-200"
              disabled={generateDisabled}
              onClick={() => void handleGenerateDraft()}
              title={
                blockedByOtherThread
                  ? `《${activeThreadTitle}》正在输出`
                  : noUserMsg
                    ? "请先和 AI 至少聊一句"
                    : "根据当前讨论生成完整回复草稿"
              }
            >
              <Sparkles className="mr-1.5 h-4 w-4" />
              生成草稿
            </Button>
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
                : "询问问题、提炼结论，或让 AI 帮你生成草稿…"
            }
            rows={4}
            disabled={blockedByOtherThread || streaming}
            className="min-h-[9.5rem] w-full resize-none rounded-xl border-slate-300 bg-white text-sm"
          />
        </div>
      </div>
    </div>
  );
}
