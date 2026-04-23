import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { AlertCircle, Bot, ChevronDown, ChevronRight, Send, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { FileTreeBrowser } from "@/components/FileTreeBrowser";
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
  const {
    messages,
    replyTarget,
    referenceFiles,
    input,
    streaming,
    loading,
  } = state;

  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const composerRef = useRef<HTMLDivElement>(null);
  const [targetOpen, setTargetOpen] = useState(!replyTarget);
  const [referencesOpen, setReferencesOpen] = useState(false);

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

  useEffect(() => {
    if (!replyTarget) {
      setTargetOpen(true);
    }
  }, [replyTarget]);

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
      rawText: `${GENERATE_TAG} 请根据以上对话，生成针对「${target}」的完整回复正文，整个正文必须用 <draft>...</draft> 标签包裹。`,
      hasReplyDraft,
      onUseDraftAsReply,
    });
  };

  const displayPath = (path: string) => path.split("/").pop() ?? path;
  const noTarget = !replyTarget;
  const noUserMsg = messages.filter((m) => m.role === "user").length === 0;
  const interactionsDisabled = blockedByOtherThread || loading;
  const sendDisabled = interactionsDisabled || streaming || noTarget || !input.trim();
  const generateDisabled = interactionsDisabled || streaming || noTarget || noUserMsg;
  const targetSummary = replyTarget ? displayPath(replyTarget) : "未选择回复对象";

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

      <div className="shrink-0 rounded-xl border border-slate-200/80 bg-slate-50/75 p-3">
        <div className="space-y-2">
          <div className="rounded-lg border border-slate-200/80 bg-white/80 px-3 py-2">
            <div className="flex items-center justify-between gap-3">
              <button
                type="button"
                onClick={() => setTargetOpen((open) => !open)}
                className="flex min-w-0 flex-1 items-center gap-2 text-left"
              >
                {targetOpen ? (
                  <ChevronDown className="h-4 w-4 shrink-0 text-slate-400" />
                ) : (
                  <ChevronRight className="h-4 w-4 shrink-0 text-slate-400" />
                )}
                <div className="flex min-w-0 flex-1 items-center gap-2">
                  <div className="shrink-0 text-sm font-semibold text-slate-800">回复对象</div>
                  <span className="shrink-0 rounded-full bg-rose-50 px-2 py-0.5 text-[11px] font-medium text-rose-600">
                    必选
                  </span>
                  <div
                    className="min-w-0 truncate text-xs text-slate-500"
                    title={replyTarget ?? undefined}
                  >
                    {targetSummary}
                  </div>
                </div>
              </button>
              <FileTreeBrowser
                mode="reply_target"
                triggerLabel={replyTarget ? "更换" : "选择"}
                triggerIcon={replyTarget ? "pencil" : "plus"}
                currentCategory={category}
                currentSlug={slug}
                selected={replyTarget ? [replyTarget] : []}
                onConfirm={(files) => {
                  const next = files[0] ?? null;
                  ai.setReplyTarget(category, slug, threadKey, next);
                }}
              />
            </div>
            {targetOpen && (
              <div className="mt-2 border-t border-slate-200/80 pt-2">
                {replyTarget ? (
                  <div
                    className="flex min-h-9 items-center rounded-lg border border-blue-200/80 bg-blue-50/90 px-3 text-sm text-blue-900"
                    title={replyTarget}
                  >
                    <span className="truncate font-mono">{displayPath(replyTarget)}</span>
                  </div>
                ) : (
                  <div className="rounded-lg border border-dashed border-slate-200 bg-white/70 px-3 py-2 text-xs text-slate-500">
                    请选择要回复的帖子文件。
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="rounded-lg border border-slate-200/80 bg-white/80 px-3 py-2">
            <div className="flex items-center justify-between gap-3">
              <button
                type="button"
                onClick={() => setReferencesOpen((open) => !open)}
                className="flex min-w-0 flex-1 items-center gap-2 text-left"
              >
                {referencesOpen ? (
                  <ChevronDown className="h-4 w-4 shrink-0 text-slate-400" />
                ) : (
                  <ChevronRight className="h-4 w-4 shrink-0 text-slate-400" />
                )}
                <div className="flex min-w-0 flex-1 items-center gap-2">
                  <div className="shrink-0 text-sm font-semibold text-slate-800">引用文件</div>
                  <div className="min-w-0 truncate text-xs text-slate-500">
                    {referenceFiles.length > 0 ? `${referenceFiles.length} 个` : "0 个"}
                  </div>
                </div>
              </button>
              <FileTreeBrowser
                mode="reference"
                triggerIcon="plus"
                currentCategory={category}
                currentSlug={slug}
                selected={referenceFiles}
                excludePaths={replyTarget ? [replyTarget] : []}
                onConfirm={(files) => ai.setReferenceFiles(category, slug, threadKey, files)}
              />
            </div>
            {referencesOpen && (
              <div className="mt-2 border-t border-slate-200/80 pt-2">
                {referenceFiles.length > 0 ? (
                  <div className="flex flex-wrap gap-2">
                    {referenceFiles.map((path) => (
                      <span
                        key={path}
                        className="flex items-center gap-1 rounded-lg border border-slate-200 bg-white/90 px-2.5 py-1.5 text-xs text-slate-700"
                      >
                        <span className="max-w-[220px] truncate font-mono" title={path}>
                          {displayPath(path)}
                        </span>
                        <button
                          type="button"
                          onClick={() =>
                            ai.setReferenceFiles(
                              category,
                              slug,
                              threadKey,
                              referenceFiles.filter((f) => f !== path),
                            )
                          }
                          className="ml-0.5 text-slate-400 hover:text-slate-700"
                        >
                          ×
                        </button>
                      </span>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-lg border border-dashed border-slate-200 bg-white/70 px-3 py-2 text-xs text-slate-500">
                    暂未选择引用文件。
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

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
              ? "先选择回复对象，再开始和 AI 一起讨论。"
              : "可以先提问、总结，或者让 AI 帮你生成回复草稿。"}
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
                    ? "请先选回复对象"
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
                  ? "请先选择回复对象文件…"
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
