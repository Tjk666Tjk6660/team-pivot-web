import { useCallback, useEffect, useRef, useState } from "react";
import { Link, Outlet, useLocation, useOutletContext } from "react-router-dom";
import {
  ChevronDown,
  GripVertical,
  LogOut,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
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
  fetchMatters,
  fetchWorkspaceStatus,
  refreshWorkspace,
  saveAIConversation,
  SessionExpiredError,
  setMatterFavorite,
  streamAIChat,
  type AIToolUse,
  type ChatMessage,
  type Draft,
  type MatterSummary,
  type Me,
  type WorkspaceStatus,
} from "@/api";
import { Button } from "@/components/ui/button";
import { ThreadListPane } from "@/components/ThreadListPane";
import { cn } from "@/lib/utils";
import { useMatterEvents } from "@/events/MatterEventsProvider";
import { scheduleRefresh } from "@/events/scheduleRefresh";

export type AIMsg = ChatMessage & { id: number; toolUses?: AIToolUse[] };

type AIThreadState = {
  loaded: boolean;
  loading: boolean;
  messages: AIMsg[];
  replyTarget: string | null;
  input: string;
  streaming: boolean;
  nextId: number;
};

type ActiveAIStream = {
  threadKey: string;
  matter_id: string;
  title: string;
} | null;

type DashboardContext = {
  reloadLists: () => Promise<void>;
  toggleMatterFavorite: (matterId: string) => Promise<void>;
  ai: {
    activeStream: ActiveAIStream;
    getThreadState: (threadKey: string) => AIThreadState;
    ensureThreadLoaded: (
      matter_id: string,
      threadKey: string,
    ) => Promise<void>;
    setInput: (threadKey: string, value: string) => void;
    setReplyTarget: (
      matter_id: string,
      threadKey: string,
      value: string | null,
    ) => void;
    clearThreadConversation: (
      matter_id: string,
      threadKey: string,
    ) => Promise<void>;
    sendMessage: (args: {
      matter_id: string;
      threadKey: string;
      threadTitle: string;
      rawText: string;
      hasReplyDraft: boolean;
      onUseDraftAsReply: (
        content: string,
        replyTo: string,
        summary?: string,
        title?: string,
      ) => Promise<boolean>;
      mode?: "reply" | "new-matter";
    }) => Promise<void>;
  };
};

function emptyAIThreadState(): AIThreadState {
  return {
    loaded: false,
    loading: false,
    messages: [],
    replyTarget: null,
    input: "",
    streaming: false,
    nextId: 1,
  };
}

// Matches `<draft>...</draft>` with an optional `type="..."` attribute.
// The captured type (or "think" when omitted) drives future doc-type branches.
const DRAFT_RE = /<draft(?:\s+type="([^"]*)")?\s*>([\s\S]*?)<\/draft>/i;
// Optional `<summary>...</summary>` produced by the same AI call so the
// publish step doesn't need a second AI round-trip to summarise.
const SUMMARY_RE = /<summary>([\s\S]*?)<\/summary>/i;
// Optional `<title>...</title>` produced in new-matter mode for the matter
// title suggestion. Reply mode does not request it.
const TITLE_RE = /<title>([\s\S]*?)<\/title>/i;

function extractDraft(text: string): {
  draft: string;
  rest: string;
  type: string;
  summary?: string;
  title?: string;
} | null {
  const m = text.match(DRAFT_RE);
  if (!m) return null;
  const summaryMatch = text.match(SUMMARY_RE);
  const titleMatch = text.match(TITLE_RE);
  // Strip all three blocks from `rest` so the user-facing AI message doesn't
  // show the raw tags after streaming completes.
  const rest = text
    .replace(DRAFT_RE, "")
    .replace(SUMMARY_RE, "")
    .replace(TITLE_RE, "")
    .trim();
  return {
    draft: m[2].trim(),
    rest,
    type: (m[1] || "think").toLowerCase(),
    summary: summaryMatch ? summaryMatch[1].trim() || undefined : undefined,
    title: titleMatch ? titleMatch[1].trim() || undefined : undefined,
  };
}

// Virtual threadKey for NewMatter conversations: __newmatter__:<draftId>.
// Bound to a draft so the same composer reopened later resumes the same chat.
const NEW_MATTER_THREAD_PREFIX = "__newmatter__:";

export function newMatterThreadKey(draftId: string): string {
  return `${NEW_MATTER_THREAD_PREFIX}${draftId}`;
}

export function isNewMatterThreadKey(key: string): boolean {
  return key.startsWith(NEW_MATTER_THREAD_PREFIX);
}

function newMatterDraftIdFromKey(key: string): string | null {
  if (!isNewMatterThreadKey(key)) return null;
  return key.slice(NEW_MATTER_THREAD_PREFIX.length);
}

export function useDashboard() {
  return useOutletContext<DashboardContext>();
}

// Stable shallow compare: identical lengths + per-id fingerprints over fields
// that the list view actually reads. Returning true makes the silent refresh
// path a no-op so list rows do not re-commit.
function sameMatters(
  prev: MatterSummary[] | null,
  next: MatterSummary[],
): boolean {
  if (prev === null) return false;
  if (prev.length !== next.length) return false;
  for (let i = 0; i < prev.length; i++) {
    const a = prev[i];
    const b = next[i];
    if (
      a.id !== b.id ||
      a.updated_at !== b.updated_at ||
      a.unread_count !== b.unread_count ||
      a.file_count !== b.file_count ||
      a.favorite !== b.favorite ||
      a.current_status !== b.current_status ||
      a.title !== b.title
    ) {
      return false;
    }
  }
  return true;
}

export function Dashboard({ me, onLogout }: { me: Me; onLogout: () => void }) {
  const location = useLocation();
  const [matters, setMatters] = useState<MatterSummary[] | null>(null);
  const [drafts, setDrafts] = useState<Draft[] | null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceStatus | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [sidebarWidth, setSidebarWidth] = useState(320);
  const [aiThreads, setAiThreads] = useState<Record<string, AIThreadState>>({});
  const [activeAIStream, setActiveAIStream] = useState<ActiveAIStream>(null);
  const isThreadView = location.pathname.startsWith("/m/");
  const layoutRef = useRef<HTMLDivElement>(null);
  const aiThreadsRef = useRef<Record<string, AIThreadState>>({});
  const activeAIStreamRef = useRef<ActiveAIStream>(null);

  useEffect(() => {
    aiThreadsRef.current = aiThreads;
  }, [aiThreads]);

  useEffect(() => {
    activeAIStreamRef.current = activeAIStream;
  }, [activeAIStream]);

  const load = useCallback(async () => {
    try {
      const [m, w, d] = await Promise.all([
        fetchMatters(),
        fetchWorkspaceStatus(),
        fetchDrafts(),
      ]);
      setMatters((prev) => (sameMatters(prev, m) ? prev : m));
      setWorkspace(w);
      setDrafts(d);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    }
  }, []);

  // Silent refresh path: only the matters list, no workspace/drafts. Skips
  // toast on failure (the user did not ask for it) and avoids touching state
  // when the list is byte-equivalent so list rows don't re-render.
  const refreshMattersSilently = useCallback(async () => {
    try {
      const next = await fetchMatters();
      setMatters((prev) => (sameMatters(prev, next) ? prev : next));
    } catch {
      // swallow; resume / next event will retry
    }
  }, []);

  const mattersRef = useRef<MatterSummary[] | null>(null);
  useEffect(() => {
    mattersRef.current = matters;
  }, [matters]);

  const toggleMatterFavorite = useCallback(async (matterId: string) => {
    const current = mattersRef.current?.find((m) => m.id === matterId);
    if (!current) return;
    const next = !current.favorite;
    // optimistic
    setMatters((prev) =>
      prev
        ? prev.map((m) => (m.id === matterId ? { ...m, favorite: next } : m))
        : prev,
    );
    try {
      await setMatterFavorite(matterId, next);
    } catch (e) {
      setMatters((prev) =>
        prev
          ? prev.map((m) => (m.id === matterId ? { ...m, favorite: !next } : m))
          : prev,
      );
      toast.error(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const getThreadState = (threadKey: string): AIThreadState =>
    aiThreads[threadKey] ?? emptyAIThreadState();

  const persistThreadConversation = (
    matter_id: string,
    threadKey: string,
    snapshot?: AIThreadState,
  ) => {
    const thread =
      snapshot ?? aiThreadsRef.current[threadKey] ?? emptyAIThreadState();
    saveAIConversation(
      matter_id,
      thread.messages.map(({ role, content }) => ({ role, content })),
      thread.replyTarget,
    ).catch(() => {});
  };

  const ensureThreadLoaded = async (
    matter_id: string,
    threadKey: string,
  ) => {
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
      const conv = await fetchAIConversation(matter_id);
      setAiThreads((prev) => {
        const existing = prev[threadKey] ?? emptyAIThreadState();
        const mapped: AIMsg[] = conv.messages.map((m, idx) => ({
          ...m,
          id: idx + 1,
        }));
        return {
          ...prev,
          [threadKey]: {
            ...existing,
            loaded: true,
            loading: false,
            messages: mapped,
            replyTarget: conv.reply_target,
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
    matter_id: string,
    threadKey: string,
    value: string | null,
  ) => {
    setAiThreads((prev) => {
      const existing = prev[threadKey] ?? emptyAIThreadState();
      const nextState: AIThreadState = {
        ...existing,
        replyTarget: value,
      };
      queueMicrotask(() =>
        persistThreadConversation(matter_id, threadKey, nextState),
      );
      return { ...prev, [threadKey]: nextState };
    });
  };

  const clearThreadConversation = async (
    matter_id: string,
    threadKey: string,
  ) => {
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
    await clearAIConversation(matter_id).catch(() => {});
  };

  const sendMessage = async ({
    matter_id,
    threadKey,
    threadTitle,
    rawText,
    hasReplyDraft,
    onUseDraftAsReply,
    mode = "reply",
  }: {
    matter_id: string;
    threadKey: string;
    threadTitle: string;
    rawText: string;
    hasReplyDraft: boolean;
    onUseDraftAsReply: (
      content: string,
      replyTo: string,
      summary?: string,
      title?: string,
    ) => Promise<boolean>;
    mode?: "reply" | "new-matter";
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
    if (mode === "reply" && !current.replyTarget) {
      toast.error("未找到起点帖子，请从某条帖子上点击「AI 回复」进入");
      return;
    }

    // new-matter mode has no replyTarget; use empty string when calling
    // onUseDraftAsReply (handler ignores it).
    const currentReplyTarget = current.replyTarget ?? "";
    const userMsg: AIMsg = {
      id: current.nextId,
      role: "user",
      content: trimmed,
    };
    const assistantId = current.nextId + 1;
    const withUser: AIMsg[] = [...current.messages, userMsg];
    const pendingMessages: AIMsg[] = [
      ...withUser,
      { id: assistantId, role: "assistant", content: "", toolUses: [] },
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

    setActiveAIStream({ threadKey, matter_id, title: threadTitle });
    const historyForApi: ChatMessage[] = withUser.map(({ role, content }) => ({
      role,
      content,
    }));

    try {
      let accumulated = "";
      const toolUses: AIToolUse[] = [];
      for await (const ev of streamAIChat(
        matter_id,
        historyForApi,
        mode === "new-matter" ? null : currentReplyTarget,
        undefined,
        mode,
      )) {
        if (ev.kind === "delta") {
          accumulated += ev.delta;
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
        } else if (ev.kind === "tool_start") {
          toolUses.push({
            id: ev.id,
            name: ev.name,
            arguments: ev.arguments,
          });
          const snapshot = toolUses.map((t) => ({ ...t }));
          setAiThreads((prev) => {
            const existing = prev[threadKey] ?? emptyAIThreadState();
            return {
              ...prev,
              [threadKey]: {
                ...existing,
                messages: existing.messages.map((m) =>
                  m.id === assistantId ? { ...m, toolUses: snapshot } : m,
                ),
              },
            };
          });
        } else if (ev.kind === "tool_end") {
          const target = toolUses.find((t) => t.id === ev.id);
          if (target) target.output_summary = ev.output_summary;
          const snapshot = toolUses.map((t) => ({ ...t }));
          setAiThreads((prev) => {
            const existing = prev[threadKey] ?? emptyAIThreadState();
            return {
              ...prev,
              [threadKey]: {
                ...existing,
                messages: existing.messages.map((m) =>
                  m.id === assistantId ? { ...m, toolUses: snapshot } : m,
                ),
              },
            };
          });
        }
      }

      const extracted = extractDraft(accumulated);
      let finalContent = accumulated;
      if (extracted) {
        if (extracted.type !== "think") {
          finalContent = extracted.rest
            ? `${extracted.rest}\n\n_⚠️ 暂不支持 type="${extracted.type}" 的草稿_`
            : `_⚠️ 暂不支持 type="${extracted.type}" 的草稿_`;
        } else {
          let proceed = true;
          if (hasReplyDraft) {
            proceed = window.confirm(
              "你已修改 Reply 框内容，是否用 AI 新草稿覆盖？",
            );
          }
          if (proceed) {
            const ok = await onUseDraftAsReply(
              extracted.draft,
              currentReplyTarget,
              extracted.summary,
              extracted.title,
            );
            finalContent = extracted.rest
              ? `${extracted.rest}\n\n_${ok ? "✅" : "⚠️"} ${ok ? "草稿已填入回复框" : "填入草稿失败"}_`
              : `_${ok ? "✅ 草稿已填入回复框" : "⚠️ 填入草稿失败"}_`;
          } else {
            finalContent = extracted.rest
              ? `${extracted.rest}\n\n_⚠️ 已放弃覆盖（保留你在回复框中的内容）_`
              : "_⚠️ 已放弃覆盖（保留你在回复框中的内容）_";
          }
        }
      }

      const frozenToolUses = toolUses.map((t) => ({ ...t }));
      let finalSnapshot: AIThreadState | null = null;
      setAiThreads((prev) => {
        const existing = prev[threadKey] ?? emptyAIThreadState();
        const nextState: AIThreadState = {
          ...existing,
          messages: withUser.concat([
            {
              id: assistantId,
              role: "assistant",
              content: finalContent,
              toolUses: frozenToolUses,
            },
          ]),
          streaming: false,
        };
        finalSnapshot = nextState;
        return { ...prev, [threadKey]: nextState };
      });
      if (finalSnapshot) {
        persistThreadConversation(matter_id, threadKey, finalSnapshot);
      }
    } catch (e) {
      const errText = e instanceof Error ? e.message : String(e);
      if (e instanceof SessionExpiredError) {
        toast.error(errText);
      }
      setAiThreads((prev) => {
        const existing = prev[threadKey] ?? emptyAIThreadState();
        return {
          ...prev,
          [threadKey]: {
            ...existing,
            messages: existing.messages.map((m) =>
              m.id === assistantId
                ? { ...m, content: `_错误：${errText}_` }
                : m,
            ),
            streaming: false,
          },
        };
      });
    } finally {
      setActiveAIStream((prev) =>
        prev?.threadKey === threadKey ? null : prev,
      );
    }
  };

  useEffect(() => {
    void load();
  }, [load]);

  // One-shot cleanup of orphan __newmatter__: threads. A NewMatter draft can
  // be deleted (via publish or manual remove) while its AIPane conversation
  // sits in the in-memory ai store keyed by draftId. On Dashboard mount, drop
  // any such thread whose draftId is no longer in the latest drafts list so
  // the store doesn't accumulate dead entries across sessions.
  const orphanCleanupDoneRef = useRef(false);
  useEffect(() => {
    if (orphanCleanupDoneRef.current) return;
    if (drafts === null) return;
    orphanCleanupDoneRef.current = true;
    const liveIds = new Set(drafts.map((d) => d.id));
    setAiThreads((prev) => {
      let changed = false;
      const next: Record<string, AIThreadState> = {};
      for (const [k, v] of Object.entries(prev)) {
        const draftId = newMatterDraftIdFromKey(k);
        if (draftId && !liveIds.has(draftId)) {
          changed = true;
          continue;
        }
        next[k] = v;
      }
      return changed ? next : prev;
    });
  }, [drafts]);

  // Subscribe to SSE matter events + visibility/reconnect resume signals.
  // Both list-mutating events and resume should converge on a single debounced
  // refetch keyed by "matters-list" so a burst of events triggers one network
  // call.
  useMatterEvents(
    useCallback(
      (evt) => {
        // resume / matter.created / matter.updated all warrant a list refresh.
        if (evt.type !== "resume" && !evt.matter_id) return;
        scheduleRefresh("matters-list", refreshMattersSilently);
      },
      [refreshMattersSilently],
    ),
  );

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
      const next = Math.min(
        Math.max(moveEvent.clientX - rect.left, minWidth),
        maxWidth,
      );
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
      <header
        className="relative z-40 shrink-0 border-b backdrop-blur"
        style={{
          borderColor: "var(--line)",
          background: "rgba(255, 253, 248, 0.94)",
        }}
      >
        <div className="flex min-h-[3.75rem] items-center gap-3 px-3 py-2 sm:min-h-[3.75rem] sm:gap-4 sm:px-6 sm:py-2">
          <div className="flex min-w-0 flex-1 items-center gap-3 sm:gap-5">
            <Button
              variant="ghost"
              size="icon"
              className="hidden h-8 w-8 rounded-md hover:bg-[var(--surface-alt)] lg:inline-flex"
              style={{ color: "var(--text-soft)" }}
              onClick={() => setSidebarOpen((o) => !o)}
              title={sidebarOpen ? "收起左侧栏" : "展开左侧栏"}
              aria-label={sidebarOpen ? "收起左侧栏" : "展开左侧栏"}
            >
              {sidebarOpen ? (
                <PanelLeftClose className="h-4 w-4" />
              ) : (
                <PanelLeftOpen className="h-4 w-4" />
              )}
            </Button>
            <Link to="/" className="flex min-w-0 items-center gap-2.5">
              <img
                src="/pivot-logo.png"
                alt="Pivot"
                className="h-10 w-10 shrink-0 rounded-lg object-cover object-top"
                style={{
                  background: "var(--surface-alt)",
                  border: "1px solid var(--line)",
                }}
              />
              <span
                className="truncate text-[17px] font-semibold"
                style={{
                  color: "var(--text)",
                  letterSpacing: "var(--letter-tight)",
                }}
              >
                Pivot
              </span>
            </Link>
            <nav className="hidden items-center gap-1 sm:flex">
              <span
                className="rounded-md px-3 py-1.5 text-[13px] font-semibold cursor-default"
                style={{
                  background: "var(--accent-bg)",
                  color: "var(--accent)",
                }}
              >
                讨论
              </span>
            </nav>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              className="h-8 rounded-md px-2.5 text-[12.5px] font-medium hover:bg-[var(--surface-alt)]"
              style={{ color: "var(--text-soft)" }}
              onClick={onRefresh}
              disabled={refreshing}
              title="同步 Git"
            >
              <RefreshCw
                className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`}
                style={{ color: "var(--text-mute)" }}
              />
              <span className="hidden sm:inline">同步 Git</span>
            </Button>
            {workspace?.head && (
              <span
                className="hidden h-8 items-center rounded-md px-2.5 text-[11.5px] font-mono lg:inline-flex"
                style={{
                  border: "1px solid var(--line)",
                  background: "var(--surface)",
                  color: "var(--text-mute)",
                }}
                title="当前工作区 HEAD"
              >
                HEAD {workspace.head.slice(0, 7)}
              </span>
            )}
            <Link to="/new">
              <Button
                size="sm"
                className="h-8 rounded-md px-3 text-[12.5px] font-semibold shadow-none"
                style={{
                  background: "var(--accent)",
                  color: "var(--accent-ink)",
                  border: "1px solid var(--accent)",
                }}
              >
                <Plus className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">新讨论</span>
              </Button>
            </Link>
            <UserMenu me={me} onLogout={onLogout} />
          </div>
        </div>
      </header>

      <div
        ref={layoutRef}
        className="flex flex-1 flex-col overflow-hidden md:flex-row"
      >
        <aside
          className={cn(
            "min-h-0 overflow-y-auto md:shrink-0 md:transition-[width] md:duration-200 md:ease-out",
            // mobile visibility (route-based)
            isThreadView ? "hidden md:block" : "block w-full",
            // desktop width
            sidebarOpen
              ? "md:w-[var(--sidebar-width)] md:border-r"
              : "md:w-0 md:overflow-hidden",
          )}
          style={
            sidebarOpen
              ? ({
                  "--sidebar-width": `${sidebarWidth}px`,
                  borderColor: "var(--line)",
                  background: "var(--bg)",
                } as React.CSSProperties)
              : ({ background: "var(--bg)" } as React.CSSProperties)
          }
        >
          {sidebarOpen && (
            <ThreadListPane
              drafts={drafts}
              matters={matters}
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
            <div className="pointer-events-none flex items-center text-[var(--text-fade)] transition-colors group-hover:text-[var(--text-mute)]">
              <GripVertical className="h-3.5 w-3.5" />
            </div>
          </div>
        )}
        <main
          className={cn(
            "relative min-h-0 flex-1 overflow-y-auto",
            !isThreadView && "hidden md:block",
          )}
          style={{ background: "var(--bg)" }}
        >
          <Outlet
            context={
              {
                reloadLists: load,
                toggleMatterFavorite,
                ai: {
                  activeStream: activeAIStream,
                  getThreadState,
                  ensureThreadLoaded,
                  setInput,
                  setReplyTarget,
                  clearThreadConversation,
                  sendMessage,
                },
              } satisfies DashboardContext
            }
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
      if (ref.current && !ref.current.contains(e.target as Node))
        setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex h-8 items-center gap-2 rounded-md pl-1 pr-1.5 transition-colors hover:bg-[var(--surface-alt)]"
      >
        {me.avatar_url ? (
          <img src={me.avatar_url} alt="" className="h-6 w-6 rounded-full" />
        ) : (
          <span
            className="flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-semibold uppercase"
            style={{ background: "var(--accent-bg)", color: "var(--accent)" }}
          >
            {me.name.slice(0, 1)}
          </span>
        )}
        <span
          className="hidden text-left text-[13px] font-semibold sm:block"
          style={{ color: "var(--text)" }}
        >
          {me.name}
        </span>
        <ChevronDown
          className="h-3.5 w-3.5"
          style={{ color: "var(--text-mute)" }}
        />
      </button>
      {open && (
        <div
          className="absolute right-0 top-full z-50 mt-2 w-56 overflow-hidden rounded-lg"
          style={{
            background: "var(--surface)",
            border: "1px solid var(--line-strong)",
            boxShadow: "var(--shadow-lg)",
          }}
        >
          <div
            className="px-3 py-3"
            style={{ borderBottom: "1px solid var(--line-soft)" }}
          >
            <div
              className="text-[14px] font-semibold"
              style={{ color: "var(--text)", fontFamily: "var(--font-serif)" }}
            >
              {me.name}
            </div>
            <div
              className="mt-0.5 text-[11.5px] font-mono"
              style={{ color: "var(--text-mute)" }}
            >
              {me.pinyin}
              {me.github_username ? ` · @${me.github_username}` : ""}
            </div>
          </div>
          <Link
            to="/settings"
            onClick={() => setOpen(false)}
            className="flex items-center gap-2.5 px-3 py-2.5 text-[13px] hover:bg-[var(--surface-alt)]"
            style={{ color: "var(--text-soft)" }}
          >
            <User
              className="h-3.5 w-3.5"
              style={{ color: "var(--text-mute)" }}
            />
            个人设置
          </Link>
          <Link
            to="/admin"
            onClick={() => setOpen(false)}
            className="flex items-center gap-2.5 px-3 py-2.5 text-[13px] hover:bg-[var(--surface-alt)]"
            style={{ color: "var(--text-soft)" }}
          >
            <ShieldCheck
              className="h-3.5 w-3.5"
              style={{ color: "var(--text-mute)" }}
            />
            管理员设置
          </Link>
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              onLogout();
            }}
            className="flex w-full items-center gap-2.5 px-3 py-2.5 text-left text-[13px] hover:bg-[var(--surface-alt)]"
            style={{
              color: "var(--text-soft)",
              borderTop: "1px solid var(--line-soft)",
            }}
          >
            <LogOut
              className="h-3.5 w-3.5"
              style={{ color: "var(--text-mute)" }}
            />
            退出登录
          </button>
        </div>
      )}
    </div>
  );
}
