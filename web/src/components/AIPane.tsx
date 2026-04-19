import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Bot, Send, Sparkles, X } from "lucide-react";
import { toast } from "sonner";
import {
  clearAIConversation,
  fetchAIConversation,
  saveAIConversation,
  streamAIChat,
  type ChatMessage,
} from "@/api";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { FileTreeBrowser } from "@/components/FileTreeBrowser";

const DRAFT_RE = /<draft>([\s\S]*?)<\/draft>/i;
const GENERATE_TAG = "[[GENERATE_REPLY_DRAFT]]";

function extractDraft(text: string): { draft: string; rest: string } | null {
  const m = text.match(DRAFT_RE);
  if (!m) return null;
  return { draft: m[1].trim(), rest: text.replace(DRAFT_RE, "").trim() };
}

type Msg = ChatMessage & { id: number };

export function AIPane({
  category,
  slug,
  threadKey,
  onClose,
  onUseDraftAsReply,
  pendingReplyTarget,
  onPendingReplyTargetConsumed,
  hasReplyDraft,
}: {
  category: string;
  slug: string;
  threadKey: string;
  onClose: () => void;
  onUseDraftAsReply: (content: string, replyTo: string, references: string[]) => Promise<boolean>;
  pendingReplyTarget?: string | null;
  onPendingReplyTargetConsumed?: () => void;
  hasReplyDraft: boolean;
}) {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [replyTarget, setReplyTarget] = useState<string | null>(null);
  const [referenceFiles, setReferenceFiles] = useState<string[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [loading, setLoading] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const msgIdRef = useRef(0);

  const nextId = () => ++msgIdRef.current;

  useEffect(() => {
    setMessages([]);
    setReplyTarget(null);
    setReferenceFiles([]);
    setInput("");
    setStreaming(false);
    setLoading(true);

    fetchAIConversation(category, slug)
      .then((conv) => {
        setMessages(conv.messages.map((m) => ({ ...m, id: nextId() })));
        setReplyTarget(conv.reply_target);
        setReferenceFiles(conv.reference_files);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [threadKey]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  // Apply pending reply target from parent (e.g. user clicked "AI 回复" on a post).
  // CRITICAL: defer until `loading` is false. Otherwise we'd persist with messages=[]
  // (the empty state set during fetch reset) and overwrite the conversation in the DB
  // before the fetch returns the real history.
  useEffect(() => {
    if (!pendingReplyTarget) return;
    if (loading) return;
    setReplyTarget(pendingReplyTarget);
    persist(messages, pendingReplyTarget, referenceFiles);
    onPendingReplyTargetConsumed?.();
    setTimeout(() => inputRef.current?.focus(), 50);
  }, [pendingReplyTarget, loading]); // eslint-disable-line react-hooks/exhaustive-deps

  const persist = (msgs: Msg[], target: string | null, refs: string[]) => {
    saveAIConversation(
      category,
      slug,
      msgs.map(({ role, content }) => ({ role, content })),
      target,
      refs,
    ).catch(() => {});
  };

  const sendCore = async (rawText: string) => {
    const trimmed = rawText.trim();
    if (!trimmed || streaming) return;
    if (!replyTarget) {
      toast.error("请先选择「回复对象」文件");
      return;
    }

    const userMsg: Msg = { id: nextId(), role: "user", content: trimmed };
    const assistantId = nextId();
    const withUser = [...messages, userMsg];
    setMessages([...withUser, { id: assistantId, role: "assistant", content: "" }]);
    setInput("");
    setStreaming(true);

    const historyForApi: ChatMessage[] = withUser.map(({ role, content }) => ({ role, content }));

    try {
      let accumulated = "";
      for await (const chunk of streamAIChat(category, slug, historyForApi, replyTarget, referenceFiles)) {
        accumulated += chunk;
        setMessages((prev) =>
          prev.map((m) => (m.id === assistantId ? { ...m, content: accumulated } : m)),
        );
      }

      const extracted = extractDraft(accumulated);
      let finalContent = accumulated;
      if (extracted) {
        // Confirm before overwriting an existing reply draft body the user may have edited
        let proceed = true;
        if (hasReplyDraft) {
          proceed = window.confirm(
            "你已修改 Reply 框内容，是否用 AI 新草稿覆盖？",
          );
        }
        if (proceed) {
          const ok = await onUseDraftAsReply(extracted.draft, replyTarget, referenceFiles);
          finalContent = extracted.rest
            ? `${extracted.rest}\n\n_${ok ? "✅" : "⚠️"} ${ok ? "草稿已填入回复框" : "填入草稿失败"}_`
            : `_${ok ? "✅ 草稿已填入回复框" : "⚠️ 填入草稿失败"}_`;
        } else {
          finalContent = extracted.rest
            ? `${extracted.rest}\n\n_⚠️ 已放弃覆盖（保留你在回复框中的内容）_`
            : "_⚠️ 已放弃覆盖（保留你在回复框中的内容）_";
        }
        setMessages((prev) =>
          prev.map((m) => (m.id === assistantId ? { ...m, content: finalContent } : m)),
        );
      }

      const finalMsgs: Msg[] = [
        ...withUser,
        { id: assistantId, role: "assistant", content: finalContent },
      ];
      persist(finalMsgs, replyTarget, referenceFiles);
    } catch (e) {
      const errText = e instanceof Error ? e.message : String(e);
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId ? { ...m, content: `_错误：${errText}_` } : m,
        ),
      );
    } finally {
      setStreaming(false);
    }
  };

  const handleSend = () => sendCore(input);

  const handleGenerateDraft = () => {
    if (!replyTarget) return;
    const target = replyTarget.split("/").pop() ?? replyTarget;
    sendCore(
      `${GENERATE_TAG} 请根据以上对话，生成针对「${target}」的完整回复正文，整个正文必须用 <draft>...</draft> 标签包裹。`,
    );
  };

  const handleClear = async () => {
    setMessages([]);
    await clearAIConversation(category, slug).catch(() => {});
  };

  const removeReference = (path: string) => {
    const next = referenceFiles.filter((f) => f !== path);
    setReferenceFiles(next);
    persist(messages, replyTarget, next);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      handleSend();
    }
  };

  const displayPath = (path: string) => path.split("/").pop() ?? path;

  const noTarget = !replyTarget;
  const noUserMsg = messages.filter((m) => m.role === "user").length === 0;
  const sendDisabled = streaming || noTarget || !input.trim();
  const generateDisabled = streaming || noTarget || noUserMsg;

  return (
    <div className="flex h-full flex-col border-l bg-background">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b px-4 py-2">
        <div className="flex items-center gap-2 text-sm font-medium">
          <Bot className="h-4 w-4 text-blue-500" />
          AI 助手
        </div>
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </div>

      {/* Reply target slot */}
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
              setReplyTarget(next);
              const cleanedRefs = referenceFiles.filter((r) => r !== next);
              setReferenceFiles(cleanedRefs);
              persist(messages, next, cleanedRefs);
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

      {/* References slot */}
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
              setReferenceFiles(files);
              persist(messages, replyTarget, files);
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
                  onClick={() => removeReference(path)}
                  className="ml-0.5 text-blue-400 hover:text-blue-700"
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
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
          const display = isUser
            ? m.content.replace(GENERATE_TAG, "🎯").trim()
            : m.content;
          return (
            <div key={m.id} className={isUser ? "flex justify-end" : ""}>
              {isUser ? (
                <div className="max-w-[85%] rounded-lg bg-blue-500 px-3 py-2 text-sm text-white whitespace-pre-wrap">
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

      {/* Generate Draft button */}
      <div className="shrink-0 border-t px-4 py-2">
        <Button
          size="sm"
          variant="default"
          className="w-full bg-amber-500 hover:bg-amber-600"
          disabled={generateDisabled}
          onClick={handleGenerateDraft}
          title={
            noTarget ? "请先选回复对象" :
            noUserMsg ? "请先和 AI 至少聊一句" :
            "根据当前讨论生成完整回复草稿"
          }
        >
          <Sparkles className="mr-1.5 h-4 w-4" />
          生成回复草稿
        </Button>
      </div>

      {/* Input */}
      <div className="shrink-0 border-t px-4 py-3">
        <div className="flex gap-2">
          <Textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              noTarget
                ? "请先选择回复对象文件…"
                : "输入问题… (⌘Enter 发送)"
            }
            rows={2}
            disabled={streaming || noTarget}
            className="flex-1 resize-none text-sm"
          />
          <Button
            size="icon"
            onClick={handleSend}
            disabled={sendDisabled}
            className="self-end"
          >
            <Send className="h-4 w-4" />
          </Button>
        </div>
        {messages.length > 0 && (
          <button
            type="button"
            className="mt-1.5 text-xs text-muted-foreground hover:underline"
            onClick={handleClear}
          >
            清空对话
          </button>
        )}
      </div>
    </div>
  );
}
