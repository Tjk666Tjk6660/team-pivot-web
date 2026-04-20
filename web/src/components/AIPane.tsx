import { useEffect, useRef } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { AlertCircle, Bot, Send, Sparkles, X } from "lucide-react";
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
  onClose,
  onUseDraftAsReply,
  pendingReplyTarget,
  onPendingReplyTargetConsumed,
  hasReplyDraft,
}: {
  category: string;
  slug: string;
  threadKey: string;
  threadTitle: string;
  onClose: () => void;
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
    if (!replyTarget) return;
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

  const handleClear = async () => {
    if (blockedByOtherThread) return;
    await ai.clearThreadConversation(category, slug, threadKey);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      void handleSend();
    }
  };

  const displayPath = (path: string) => path.split("/").pop() ?? path;
  const noTarget = !replyTarget;
  const noUserMsg = messages.filter((m) => m.role === "user").length === 0;
  const interactionsDisabled = blockedByOtherThread || loading;
  const sendDisabled = interactionsDisabled || streaming || noTarget || !input.trim();
  const generateDisabled = interactionsDisabled || streaming || noTarget || noUserMsg;

  return (
    <div className="relative flex h-full min-h-0 flex-col border-l bg-background">
      <div className="flex shrink-0 items-center justify-between border-b px-4 py-2">
        <div className="flex items-center gap-2 text-sm font-medium">
          <Bot className="h-4 w-4 text-blue-500" />
          AI 助手
        </div>
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </div>

      {blockedByOtherThread && (
        <div className="shrink-0 border-b bg-amber-50 px-4 py-3 text-xs text-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
          <div className="flex items-start gap-2">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <div className="font-medium">AI 输出被其他 thread 占用</div>
              <div className="mt-1 leading-relaxed">
                《{activeThreadTitle}》正在占用 AI 输出，请等待它完成后再尝试。
              </div>
            </div>
          </div>
        </div>
      )}

      <div
        className={
          blockedByOtherThread
            ? "pointer-events-none flex min-h-0 flex-1 flex-col opacity-50"
            : "flex min-h-0 flex-1 flex-col"
        }
      >
        <div className="shrink-0 border-b px-4 py-2">
          <div className="mb-1.5 flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-muted-foreground">
              📝 回复对象 <span className="text-red-500">*必选</span>
            </span>
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
          {replyTarget ? (
            <span
              className="inline-flex max-w-full items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-xs text-amber-800 dark:bg-amber-950/50 dark:text-amber-300"
              title={replyTarget}
            >
              <span className="truncate font-mono">{displayPath(replyTarget)}</span>
            </span>
          ) : (
            <p className="text-xs text-amber-700">请选择一个回复对象后才能与 AI 对话</p>
          )}
        </div>

        <div className="shrink-0 border-b px-4 py-2">
          <div className="mb-1.5 flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-muted-foreground">
              📎 引用其他文件 {referenceFiles.length > 0 ? `(${referenceFiles.length}/4)` : "(选填)"}
            </span>
            <FileTreeBrowser
              mode="reference"
              triggerIcon="plus"
              currentCategory={category}
              currentSlug={slug}
              selected={referenceFiles}
              excludePaths={replyTarget ? [replyTarget] : []}
              onConfirm={(files) => {
                ai.setReferenceFiles(category, slug, threadKey, files);
              }}
            />
          </div>
          {referenceFiles.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {referenceFiles.map((path) => (
                <span
                  key={path}
                  className="flex items-center gap-1 rounded-full bg-blue-50 px-2 py-0.5 text-xs text-blue-700 dark:bg-blue-950/50 dark:text-blue-300"
                >
                  <span className="max-w-[160px] truncate font-mono" title={path}>
                    {displayPath(path)}
                  </span>
                  <button
                    type="button"
                    onClick={() => {
                      const next = referenceFiles.filter((f) => f !== path);
                      ai.setReferenceFiles(category, slug, threadKey, next);
                    }}
                    className="ml-0.5 text-blue-400 hover:text-blue-700"
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>

        <div ref={scrollRef} className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-3">
          {loading && (
            <p className="pt-8 text-center text-xs text-muted-foreground">加载历史记录…</p>
          )}
          {!loading && messages.length === 0 && (
            <p className="pt-8 text-center text-xs text-muted-foreground">
              {noTarget
                ? "请先选择回复对象文件，然后开始对话"
                : "针对回复对象提问、讨论；想要生成草稿时点击下方按钮"}
            </p>
          )}
          {messages.map((m) => {
            const isUser = m.role === "user";
            const display = isUser ? m.content.replace(GENERATE_TAG, "🎯").trim() : m.content;
            return (
              <div key={m.id} className={isUser ? "flex justify-end" : ""}>
                {isUser ? (
                  <div className="max-w-[85%] whitespace-pre-wrap rounded-lg bg-blue-500 px-3 py-2 text-sm text-white">
                    {display}
                  </div>
                ) : (
                  <div className="prose-pivot text-sm">
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

        <div className="shrink-0 border-t px-4 py-2">
          <Button
            size="sm"
            variant="default"
            className="w-full bg-amber-500 hover:bg-amber-600"
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
            生成回复草稿
          </Button>
        </div>

        <div className="shrink-0 border-t px-4 py-3">
          <div className="flex gap-2">
            <Textarea
              ref={inputRef}
              value={input}
              onChange={(e) => ai.setInput(threadKey, e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                blockedByOtherThread
                  ? `《${activeThreadTitle}》正在输出，请稍后…`
                  : noTarget
                    ? "请先选择回复对象文件…"
                    : "输入问题… (⌘Enter 发送)"
              }
              rows={2}
              disabled={blockedByOtherThread || streaming || noTarget}
              className="flex-1 resize-none text-sm"
            />
            <Button size="icon" onClick={() => void handleSend()} disabled={sendDisabled} className="self-end">
              <Send className="h-4 w-4" />
            </Button>
          </div>
          {messages.length > 0 && (
            <button
              type="button"
              className="mt-1.5 text-xs text-muted-foreground hover:underline"
              onClick={() => void handleClear()}
              disabled={blockedByOtherThread || streaming}
            >
              清空对话
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
