import { useEffect, useRef, useState } from "react";
import { Link, Outlet, useLocation, useOutletContext } from "react-router-dom";
import {
  ChevronDown,
  GripVertical,
  LogOut,
  MessageSquareText,
  RefreshCw,
  ShieldCheck,
  User,
} from "lucide-react";
import { Toaster, toast } from "sonner";
import {
  clearAIConversation,
  deleteDraft,
  fetchAIConversation,
  fetchDrafts,
  fetchThreads,
  fetchWorkspaceStatus,
  refreshWorkspace,
  saveAIConversation,
  streamAIChat,
  type ChatMessage,
  type Draft,
  type Me,
  type ThreadMeta,
  type WorkspaceStatus,
} from "@/api";
import { Button } from "@/components/ui/button";
import { ThreadListPane } from "@/components/ThreadListPane";
import { cn } from "@/lib/utils";

type AIMsg = ChatMessage & { id: number };

type AIThreadState = {
  loaded: boolean;
  loading: boolean;
  messages: AIMsg[];
  replyTarget: string | null;
  referenceFiles: string[];
  input: string;
  streaming: boolean;
  nextId: number;
};

type ActiveAIStream = {
  threadKey: string;
  category: string;
  slug: string;
  title: string;
} | null;

type DashboardContext = {
  reloadLists: () => Promise<void>;
  ai: {
    activeStream: ActiveAIStream;
    getThreadState: (threadKey: string) => AIThreadState;
    ensureThreadLoaded: (category: string, slug: string, threadKey: string) => Promise<void>;
    setInput: (threadKey: string, value: string) => void;
    setReplyTarget: (
      category: string,
      slug: string,
      threadKey: string,
      value: string | null,
    ) => void;
    setReferenceFiles: (
      category: string,
      slug: string,
      threadKey: string,
      files: string[],
    ) => void;
    clearThreadConversation: (category: string, slug: string, threadKey: string) => Promise<void>;
    sendMessage: (args: {
      category: string;
      slug: string;
      threadKey: string;
      threadTitle: string;
      rawText: string;
      hasReplyDraft: boolean;
      onUseDraftAsReply: (content: string, replyTo: string, references: string[]) => Promise<boolean>;
    }) => Promise<void>;
  };
};

function emptyAIThreadState(): AIThreadState {
  return {
    loaded: false,
    loading: false,
    messages: [],
    replyTarget: null,
    referenceFiles: [],
    input: "",
    streaming: false,
    nextId: 1,
  };
}

const DRAFT_RE = /<draft>([\s\S]*?)<\/draft>/i;

function extractDraft(text: string): { draft: string; rest: string } | null {
  const m = text.match(DRAFT_RE);
  if (!m) return null;
  return { draft: m[1].trim(), rest: text.replace(DRAFT_RE, "").trim() };
}

export function useDashboard() {
  return useOutletContext<DashboardContext>();
}

export function Dashboard({ me, onLogout }: { me: Me; onLogout: () => void }) {
  const location = useLocation();
  const [threads, setThreads] = useState<ThreadMeta[] | null>(null);
  const [drafts, setDrafts] = useState<Draft[] | null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceStatus | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [sidebarWidth, setSidebarWidth] = useState(320);
  const [aiThreads, setAiThreads] = useState<Record<string, AIThreadState>>({});
  const [activeAIStream, setActiveAIStream] = useState<ActiveAIStream>(null);
  const isThreadView = location.pathname.startsWith("/t/");
  const layoutRef = useRef<HTMLDivElement>(null);
  const aiThreadsRef = useRef<Record<string, AIThreadState>>({});
  const activeAIStreamRef = useRef<ActiveAIStream>(null);

  useEffect(() => {
    aiThreadsRef.current = aiThreads;
  }, [aiThreads]);

  useEffect(() => {
    activeAIStreamRef.current = activeAIStream;
  }, [activeAIStream]);

  const load = async () => {
    try {
      const [t, w, d] = await Promise.all([
        fetchThreads(), fetchWorkspaceStatus(), fetchDrafts(),
      ]);
      setThreads(t); setWorkspace(w); setDrafts(d);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    }
  };

  const getThreadState = (threadKey: string): AIThreadState =>
    aiThreads[threadKey] ?? emptyAIThreadState();

  const persistThreadConversation = (
    category: string,
    slug: string,
    threadKey: string,
    snapshot?: AIThreadState,
  ) => {
    const thread = snapshot ?? aiThreadsRef.current[threadKey] ?? emptyAIThreadState();
    saveAIConversation(
      category,
      slug,
      thread.messages.map(({ role, content }) => ({ role, content })),
      thread.replyTarget,
      thread.referenceFiles,
    ).catch(() => {});
  };

  const ensureThreadLoaded = async (category: string, slug: string, threadKey: string) => {
    const current = aiThreadsRef.current[threadKey];
    if (current?.loaded || current?.loading) return;

    setAiThreads((prev) => ({
      ...prev,
      [threadKey]: {
        ...(prev[threadKey] ?? emptyAIThreadState()),
        loading: true,
      },
    }));

    try {
      const conv = await fetchAIConversation(category, slug);
      setAiThreads((prev) => {
        const existing = prev[threadKey] ?? emptyAIThreadState();
        const mapped: AIMsg[] = conv.messages.map((m, idx) => ({ ...m, id: idx + 1 }));
        return {
          ...prev,
          [threadKey]: {
            ...existing,
            loaded: true,
            loading: false,
            messages: mapped,
            replyTarget: conv.reply_target,
            referenceFiles: conv.reference_files,
            nextId: mapped.length + 1,
          },
        };
      });
    } catch {
      setAiThreads((prev) => ({
        ...prev,
        [threadKey]: {
          ...(prev[threadKey] ?? emptyAIThreadState()),
          loaded: true,
          loading: false,
        },
      }));
    }
  };

  const setInput = (threadKey: string, value: string) => {
    setAiThreads((prev) => ({
      ...prev,
      [threadKey]: {
        ...(prev[threadKey] ?? emptyAIThreadState()),
        input: value,
      },
    }));
  };

  const setReplyTarget = (
    category: string,
    slug: string,
    threadKey: string,
    value: string | null,
  ) => {
    setAiThreads((prev) => {
      const existing = prev[threadKey] ?? emptyAIThreadState();
      const nextState: AIThreadState = {
        ...existing,
        replyTarget: value,
        referenceFiles: existing.referenceFiles.filter((ref) => ref !== value),
      };
      queueMicrotask(() => persistThreadConversation(category, slug, threadKey, nextState));
      return { ...prev, [threadKey]: nextState };
    });
  };

  const setReferenceFiles = (
    category: string,
    slug: string,
    threadKey: string,
    files: string[],
  ) => {
    setAiThreads((prev) => {
      const existing = prev[threadKey] ?? emptyAIThreadState();
      const nextState: AIThreadState = {
        ...existing,
        referenceFiles: files,
      };
      queueMicrotask(() => persistThreadConversation(category, slug, threadKey, nextState));
      return { ...prev, [threadKey]: nextState };
    });
  };

  const clearThreadConversation = async (category: string, slug: string, threadKey: string) => {
    setAiThreads((prev) => ({
      ...prev,
      [threadKey]: {
        ...(prev[threadKey] ?? emptyAIThreadState()),
        loaded: true,
        loading: false,
        messages: [],
        input: "",
        streaming: false,
        nextId: 1,
      },
    }));
    if (activeAIStreamRef.current?.threadKey === threadKey) {
      setActiveAIStream(null);
    }
    await clearAIConversation(category, slug).catch(() => {});
  };

  const sendMessage = async ({
    category,
    slug,
    threadKey,
    threadTitle,
    rawText,
    hasReplyDraft,
    onUseDraftAsReply,
  }: {
    category: string;
    slug: string;
    threadKey: string;
    threadTitle: string;
    rawText: string;
    hasReplyDraft: boolean;
    onUseDraftAsReply: (content: string, replyTo: string, references: string[]) => Promise<boolean>;
  }) => {
    const trimmed = rawText.trim();
    if (!trimmed) return;

    const active = activeAIStreamRef.current;
    if (active && active.threadKey !== threadKey) {
      toast.error(`《${active.title}》正在占用 AI 输出，请等待完成`);
      return;
    }

    const current = aiThreadsRef.current[threadKey] ?? emptyAIThreadState();
    if (current.streaming) return;
    if (!current.replyTarget) {
      toast.error("请先选择「回复对象」文件");
      return;
    }

    const currentReplyTarget = current.replyTarget;
    const currentReferenceFiles = current.referenceFiles;
    const userMsg: AIMsg = { id: current.nextId, role: "user", content: trimmed };
    const assistantId = current.nextId + 1;
    const withUser: AIMsg[] = [...current.messages, userMsg];
    const pendingMessages: AIMsg[] = [
      ...withUser,
      { id: assistantId, role: "assistant", content: "" },
    ];

    setAiThreads((prev) => ({
      ...prev,
      [threadKey]: {
        ...(prev[threadKey] ?? current),
        loaded: true,
        loading: false,
        messages: pendingMessages,
        input: "",
        streaming: true,
        nextId: current.nextId + 2,
      },
    }));

    setActiveAIStream({ threadKey, category, slug, title: threadTitle });
    const historyForApi: ChatMessage[] = withUser.map(({ role, content }) => ({ role, content }));

    try {
      let accumulated = "";
      for await (const chunk of streamAIChat(category, slug, historyForApi, currentReplyTarget, currentReferenceFiles)) {
        accumulated += chunk;
        setAiThreads((prev) => {
          const existing = prev[threadKey] ?? emptyAIThreadState();
          return {
            ...prev,
            [threadKey]: {
              ...existing,
              messages: existing.messages.map((m) =>
                m.id === assistantId ? { ...m, content: accumulated } : m,
              ),
            },
          };
        });
      }

      const extracted = extractDraft(accumulated);
      let finalContent = accumulated;
      if (extracted) {
        let proceed = true;
        if (hasReplyDraft) {
          proceed = window.confirm("你已修改 Reply 框内容，是否用 AI 新草稿覆盖？");
        }
        if (proceed) {
          const ok = await onUseDraftAsReply(extracted.draft, currentReplyTarget, currentReferenceFiles);
          finalContent = extracted.rest
            ? `${extracted.rest}\n\n_${ok ? "✅" : "⚠️"} ${ok ? "草稿已填入回复框" : "填入草稿失败"}_`
            : `_${ok ? "✅ 草稿已填入回复框" : "⚠️ 填入草稿失败"}_`;
        } else {
          finalContent = extracted.rest
            ? `${extracted.rest}\n\n_⚠️ 已放弃覆盖（保留你在回复框中的内容）_`
            : "_⚠️ 已放弃覆盖（保留你在回复框中的内容）_";
        }
      }

      let finalSnapshot: AIThreadState | null = null;
      setAiThreads((prev) => {
        const existing = prev[threadKey] ?? emptyAIThreadState();
        const nextState: AIThreadState = {
          ...existing,
          messages: withUser.concat([{ id: assistantId, role: "assistant", content: finalContent }]),
          streaming: false,
        };
        finalSnapshot = nextState;
        return { ...prev, [threadKey]: nextState };
      });
      if (finalSnapshot) {
        persistThreadConversation(category, slug, threadKey, finalSnapshot);
      }
    } catch (e) {
      const errText = e instanceof Error ? e.message : String(e);
      setAiThreads((prev) => {
        const existing = prev[threadKey] ?? emptyAIThreadState();
        return {
          ...prev,
          [threadKey]: {
            ...existing,
            messages: existing.messages.map((m) =>
              m.id === assistantId ? { ...m, content: `_错误：${errText}_` } : m,
            ),
            streaming: false,
          },
        };
      });
    } finally {
      setActiveAIStream((prev) => (prev?.threadKey === threadKey ? null : prev));
    }
  };

  useEffect(() => { load(); }, []);

  const onRefresh = async () => {
    setRefreshing(true);
    try {
      await refreshWorkspace();
      await load();
      toast.success("已从远端拉取最新");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setRefreshing(false);
    }
  };

  const removeDraft = async (id: string) => {
    if (!confirm("Delete this draft?")) return;
    try {
      await deleteDraft(id);
      setDrafts((ds) => (ds ?? []).filter((d) => d.id !== id));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    }
  };

  const startSidebarResize = (event: React.MouseEvent<HTMLDivElement>) => {
    event.preventDefault();
    const layout = layoutRef.current;
    if (!layout) return;
    const rect = layout.getBoundingClientRect();
    const minWidth = 260;
    const maxWidth = Math.min(560, rect.width - 360);

    const onMove = (moveEvent: MouseEvent) => {
      const next = Math.min(Math.max(moveEvent.clientX - rect.left, minWidth), maxWidth);
      setSidebarWidth(next);
      if (!sidebarOpen) setSidebarOpen(true);
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
    <div className="flex h-screen flex-col bg-transparent">
      <Toaster position="top-center" richColors />
      <header className="relative z-40 shrink-0 border-b border-slate-200/90 bg-[rgba(250,251,253,0.92)] backdrop-blur">
        <div className="flex min-h-[3.75rem] items-center gap-3 px-3 py-2 sm:min-h-[4.1rem] sm:flex-wrap sm:gap-4 sm:px-6 sm:py-3">
          <div className="flex min-w-0 flex-1 items-center gap-3 sm:gap-5">
            <Link to="/" className="flex min-w-0 items-center gap-2.5">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-blue-600 text-white shadow-sm">
                <MessageSquareText className="h-4 w-4" />
              </span>
              <span className="truncate text-[17px] font-semibold text-slate-900">
                team-pivot
              </span>
            </Link>
            <nav className="flex items-center gap-2">
              <span className="inline-flex h-10 items-center border-b-2 border-blue-600 px-1 text-sm font-semibold text-slate-900">
                讨论
              </span>
            </nav>
          </div>
          <div className="flex items-center gap-2 sm:flex-wrap sm:gap-3">
            <Button
              variant="outline"
              size="sm"
              className="h-9 rounded-xl border-slate-200/90 bg-white/84 px-2.5 text-sm font-medium text-slate-700 shadow-none hover:bg-slate-50 sm:h-10 sm:px-3.5"
              onClick={onRefresh}
              disabled={refreshing}
              title="同步 Git"
            >
              <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
              <span className="hidden sm:inline">同步 Git</span>
            </Button>
            {workspace?.head && (
              <span className="hidden h-10 items-center rounded-xl border border-slate-200/90 bg-white/84 px-3.5 text-sm font-medium text-slate-500 lg:inline-flex">
                HEAD {workspace.head}
              </span>
            )}
          </div>
          <div className="rounded-xl border border-slate-200/90 bg-white/84 px-1.5 py-1 sm:px-2.5 sm:py-1.5">
            <UserMenu me={me} onLogout={onLogout} />
          </div>
        </div>
      </header>

      <div ref={layoutRef} className="flex flex-1 flex-col overflow-hidden px-0 pb-0 pt-0 md:flex-row md:gap-3 md:px-4 md:pb-4 md:pt-4">
        <aside
          className={cn(
            "min-h-0 overflow-y-auto md:workbench-panel md:shrink-0 md:rounded-[1.2rem] md:border",
            isThreadView ? "hidden md:block" : "block",
            !sidebarOpen && "md:overflow-hidden md:border-transparent",
          )}
          style={{ width: sidebarOpen ? sidebarWidth : undefined }}
        >
          {sidebarOpen && (
            <ThreadListPane
              drafts={drafts}
              threads={threads}
              onRemoveDraft={removeDraft}
            />
          )}
        </aside>
        {sidebarOpen && (
          <div
            className="group relative hidden w-3 shrink-0 cursor-col-resize items-stretch justify-center md:flex"
            onMouseDown={startSidebarResize}
            title="拖拽调整导航栏宽度"
          >
            <div className="pointer-events-none flex items-center text-slate-300 transition-colors group-hover:text-slate-500">
              <GripVertical className="h-3.5 w-3.5" />
            </div>
          </div>
        )}
        <main
          className={cn(
            "relative min-h-0 flex-1 overflow-y-auto md:workbench-panel md:rounded-[1.2rem] md:border",
            !isThreadView && "hidden md:block",
          )}
        >
          <Outlet
            context={{
              reloadLists: load,
              ai: {
                activeStream: activeAIStream,
                getThreadState,
                ensureThreadLoaded,
                setInput,
                setReplyTarget,
                setReferenceFiles,
                clearThreadConversation,
                sendMessage,
              },
            } satisfies DashboardContext}
          />
        </main>
      </div>
    </div>
  );
}

function UserMenu({ me, onLogout }: { me: Me; onLogout: () => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex h-8 items-center gap-2 rounded-lg px-1.5 transition-colors hover:bg-slate-100"
      >
        {me.avatar_url && (
          <img src={me.avatar_url} alt="" className="h-7 w-7 rounded-full" />
        )}
        <div className="hidden text-left text-sm font-semibold text-slate-900 sm:block">{me.name}</div>
        <ChevronDown className="h-4 w-4 text-slate-400" />
      </button>
      {open && (
        <div className="absolute right-0 top-full z-50 mt-2 w-52 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-[0_12px_32px_rgba(15,23,42,0.08)]">
          <div className="border-b border-slate-200/80 px-3 py-2.5">
            <div className="text-sm font-medium text-slate-900">{me.name}</div>
            <div className="text-xs text-slate-500">
              {me.pinyin}
              {me.github_username ? ` · @${me.github_username}` : ""}
            </div>
          </div>
          <Link
            to="/settings"
            onClick={() => setOpen(false)}
            className="flex items-center gap-2 px-3 py-2.5 text-sm text-slate-700 hover:bg-slate-50"
          >
            <User className="h-4 w-4" />
            个人设置
          </Link>
          <Link
            to="/admin"
            onClick={() => setOpen(false)}
            className="flex items-center gap-2 px-3 py-2.5 text-sm text-slate-700 hover:bg-slate-50"
          >
            <ShieldCheck className="h-4 w-4" />
            管理员设置
          </Link>
          <button
            type="button"
            onClick={() => { setOpen(false); onLogout(); }}
            className="flex w-full items-center gap-2 border-t border-slate-200 px-3 py-2.5 text-left text-sm text-slate-700 hover:bg-slate-50"
          >
            <LogOut className="h-4 w-4" />
            退出登录
          </button>
        </div>
      )}
    </div>
  );
}
