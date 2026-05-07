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
  AIChatError,
  clearAIConversation,
  deleteDraft,
  fetchAIConversation,
  fetchDrafts,
  fetchMatters,
  fetchPreferences,
  fetchWorkspaceStatus,
  refreshWorkspace,
  saveAIConversation,
  SessionExpiredError,
  setMatterFavorite,
  setPreference,
  streamAIChat,
  type AIErrorDetail,
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
import { subscribeDraftsRefresh, subscribeListRefresh } from "@/events/listRefresh";
import {
  mergeLoadedAIConversation,
  setAIReplyTarget,
} from "@/lib/aiConversationState";

export type AIMsg = ChatMessage & { id: number; toolUses?: AIToolUse[] };

// 方案 B：sendMessage 时记下入参，供"重试"按钮直接复用同一上下文调用
// （F4：retryable 错误时一键重试）。
type LastSendArgs = {
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
};

type AIThreadState = {
  loaded: boolean;
  loading: boolean;
  messages: AIMsg[];
  replyTarget: string | null;
  input: string;
  streaming: boolean;
  nextId: number;
  // 方案 B 状态机扩展：
  // slow=true 表示当前正在等待 AI 上游回复（最近一次事件是 heartbeat 而非 token），
  // 用于驱动 AIPane 顶部的"AI 响应较慢…" banner（F2）。
  slow: boolean;
  // 最近一次失败的结构化详情；retryable=true 时 AIPane 显示"重试"按钮（F4）。
  errorDetail: AIErrorDetail | null;
  // 最近一次 sendMessage 的入参，"重试"按钮原样回放它即可（F4）。
  lastSendArgs: LastSendArgs | null;
};

type ActiveAIStream = {
  threadKey: string;
  matter_id: string;
  title: string;
} | null;

type ActiveAIAbort = {
  threadKey: string;
  controller: AbortController;
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
    sendMessage: (args: LastSendArgs) => Promise<void>;
    stopMessage: (threadKey: string) => void;
    /** 方案 B：复用上一次入参重新发起调用。AIPane "重试"按钮调用。
     *  无 lastSendArgs 时是 no-op。 */
    retryLastSend: (threadKey: string) => Promise<void>;
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
    slow: false,
    errorDetail: null,
    lastSendArgs: null,
  };
}

// Sentinel that AIPane's "生成草稿" button prefixes onto the user message
// to trigger the AI's <draft>-emitting branch. Mirrored in AIPane.tsx.
export const GENERATE_REPLY_DRAFT_TAG = "[[GENERATE_REPLY_DRAFT]]";

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
const SIDEBAR_RESIZE_CURSOR =
  "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24' fill='none' stroke='%235a3a1a' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M8 7 3 12l5 5'/%3E%3Cpath d='M16 7l5 5-5 5'/%3E%3Cpath d='M3 12h18'/%3E%3C/svg%3E\") 12 12, col-resize";

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
      a.last_activity_at !== b.last_activity_at ||
      a.unread_count !== b.unread_count ||
      a.red_unread_count !== b.red_unread_count ||
      a.gray_unread_count !== b.gray_unread_count ||
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

export type MatterListFilter = "all" | "mine";

const FILTER_PREF_KEY = "matter_list_filter";

function parseListFilter(value: string | undefined): MatterListFilter {
  return value === "mine" ? "mine" : "all";
}

// Local-storage mirror of the server-side matter_list_filter preference.
// Read synchronously on first render so the page boots with the right
// filter (no "全部 → 与我相关" flash on relogin); on every server-pref
// fetch / write we keep the mirror in sync. Read failures (e.g. private
// browsing modes) silently fall back to "all" — the server fetch will
// still correct it after one tick.
const FILTER_PREF_CACHE_KEY = "pivot.matter_list_filter";

function readCachedListFilter(): MatterListFilter {
  try {
    return parseListFilter(
      localStorage.getItem(FILTER_PREF_CACHE_KEY) ?? undefined,
    );
  } catch {
    return "all";
  }
}

function writeCachedListFilter(value: MatterListFilter): void {
  try {
    localStorage.setItem(FILTER_PREF_CACHE_KEY, value);
  } catch {
    // ignore
  }
}

export function Dashboard({ me, onLogout }: { me: Me; onLogout: () => void }) {
  const location = useLocation();
  const [matters, setMatters] = useState<MatterSummary[] | null>(null);
  const [drafts, setDrafts] = useState<Draft[] | null>(null);
  // "全部 / 与我相关" filter. Server-persisted via /api/me/preferences so
  // the choice survives across browsers / devices, with a localStorage
  // mirror read synchronously here so the page boots with the right value
  // and doesn't flash from "all" to "mine" on relogin.
  const [listFilter, setListFilter] = useState<MatterListFilter>(
    readCachedListFilter,
  );
  const [workspace, setWorkspace] = useState<WorkspaceStatus | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [sidebarWidth, setSidebarWidth] = useState(320);
  const [aiThreads, setAiThreads] = useState<Record<string, AIThreadState>>({});
  const [activeAIStream, setActiveAIStream] = useState<ActiveAIStream>(null);
  // Routes that take the full main pane on narrow screens. `/m/` is the
  // matter detail view; `/new` is the NewMatter composer (also a full pane).
  const isThreadView =
    location.pathname.startsWith("/m/") || location.pathname.startsWith("/new");
  // /new doesn't need the matter / draft list at all — the composer fills the
  // whole main column and the AI assistant lives in its own right column.
  const hideSidebar = location.pathname.startsWith("/new");
  const layoutRef = useRef<HTMLDivElement>(null);
  const aiThreadsRef = useRef<Record<string, AIThreadState>>({});
  const activeAIStreamRef = useRef<ActiveAIStream>(null);
  const activeAIAbortRef = useRef<ActiveAIAbort>(null);
  const aiThreadLoadsInFlightRef = useRef<Set<string>>(new Set());

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
      setMatters((prev) => (sameMatters(prev, m.items) ? prev : m.items));
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
      setMatters((prev) => (sameMatters(prev, next.items) ? prev : next.items));
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
    if (aiThreadLoadsInFlightRef.current.has(threadKey)) return;
    aiThreadLoadsInFlightRef.current.add(threadKey);

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
        return {
          ...prev,
          [threadKey]: mergeLoadedAIConversation<AIMsg, AIThreadState>(
            existing,
            conv,
          ),
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
    } finally {
      aiThreadLoadsInFlightRef.current.delete(threadKey);
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
      const { state: nextState, changed } = setAIReplyTarget(existing, value);
      if (!changed) return prev;
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
  }: LastSendArgs) => {
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
    // Snapshot args for the retry button (F4) — anything that can change
    // between send and retry is re-derived inside sendMessage on retry, so
    // we keep the *original* user intent here (rawText + mode + handlers).
    const sendArgsForRetry: LastSendArgs = {
      matter_id, threadKey, threadTitle, rawText,
      hasReplyDraft, onUseDraftAsReply, mode,
    };

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
        // 方案 B：开新 stream 时重置交互态。slow / errorDetail 应该是上一轮
        // 留下的"陈旧"态——发新消息时 UI 必须立即清掉，否则会在
        // "正在连接 AI…"阶段误报"AI 响应较慢"。
        slow: false,
        errorDetail: null,
        lastSendArgs: sendArgsForRetry,
      },
    }));

    setActiveAIStream({ threadKey, matter_id, title: threadTitle });
    const controller = new AbortController();
    activeAIAbortRef.current = { threadKey, controller };
    const historyForApi: ChatMessage[] = withUser.map(({ role, content }) => ({
      role,
      content,
    }));

    let accumulated = "";
    const toolUses: AIToolUse[] = [];
    try {
      for await (const ev of streamAIChat(
        matter_id,
        historyForApi,
        mode === "new-matter" ? null : currentReplyTarget,
        controller.signal,
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
                // 收到真实 token → 上游恢复响应，立即清掉"较慢" banner（F2 ↔
                // streaming 切回）。
                slow: false,
                messages: existing.messages.map((m) =>
                  m.id === assistantId ? { ...m, content: accumulated } : m,
                ),
              },
            };
          });
        } else if (ev.kind === "heartbeat") {
          // 方案 B (F2)：服务端在 `heartbeat_interval_s` 内未收到上游 token 时
          // 下发 heartbeat。把 thread 切到 slow 态触发 AIPane 顶部的"AI 响应较慢
          // ..." banner；下一条 delta 会自动把它撤掉。
          setAiThreads((prev) => {
            const existing = prev[threadKey] ?? emptyAIThreadState();
            if (existing.slow) return prev;
            return {
              ...prev,
              [threadKey]: { ...existing, slow: true },
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
      // Quality-gate invariant: AI failure must NEVER promote body_source
      // to "ai". onUseDraftAsReply (the only entry to applyAIDraft) is only
      // invoked from the `extracted && extracted.type === "think"` branch
      // below — empty / malformed / errored streams skip it entirely, so
      // body / body_source on the consumer side stays untouched.
      const userRequestedDraft = trimmed.startsWith(GENERATE_REPLY_DRAFT_TAG);
      if (userRequestedDraft && !extracted) {
        // GENERATE was triggered but the AI didn't produce a usable <draft>.
        // Surface this explicitly so the user knows nothing was filled in.
        toast.warning(
          "AI 没有给出可用草稿，请补充更多上下文后再试一次",
        );
      }
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
          // 成功结束的兜底：F2/F4 的状态在这里清干净，避免 banner 残留。
          slow: false,
          errorDetail: null,
        };
        finalSnapshot = nextState;
        return { ...prev, [threadKey]: nextState };
      });
      if (finalSnapshot) {
        persistThreadConversation(matter_id, threadKey, finalSnapshot);
      }
    } catch (e) {
      const errText = e instanceof Error ? e.message : String(e);
      const aborted =
        e instanceof DOMException && e.name === "AbortError";
      // 方案 B：AIChatError 携带服务端归一化后的 detail，按 retryable/code 分流
      // UI（F4）。其他错误退化为最简提示（不带 retry）。
      const errorDetail: AIErrorDetail | null =
        e instanceof AIChatError
          ? e.detail
          : aborted || e instanceof SessionExpiredError
            ? null
            : { code: "unknown", retryable: true, message: errText, status: null };
      if (e instanceof SessionExpiredError) {
        toast.error(errText);
      } else if (!aborted) {
        toast.error(`AI 调用失败：${errorDetail?.message ?? errText}`);
      }
      if (aborted) {
        const frozenToolUses = toolUses.map((t) => ({ ...t }));
        let finalSnapshot: AIThreadState | null = null;
        setAiThreads((prev) => {
          const existing = prev[threadKey] ?? emptyAIThreadState();
          const nextState: AIThreadState = {
            ...existing,
            messages: existing.messages.map((m) =>
              m.id === assistantId
                ? {
                    ...m,
                    content: accumulated
                      ? `${accumulated}\n\n_已停止生成_`
                      : "_已停止生成_",
                    toolUses: frozenToolUses,
                  }
                : m,
            ),
            streaming: false,
            slow: false,
            errorDetail: null,
          };
          finalSnapshot = nextState;
          return { ...prev, [threadKey]: nextState };
        });
        if (finalSnapshot) {
          persistThreadConversation(matter_id, threadKey, finalSnapshot);
        }
        return;
      }
      setAiThreads((prev) => {
        const existing = prev[threadKey] ?? emptyAIThreadState();
        // 失败时把消息体替换成简短占位文，把详细信息收到 errorDetail。
        // 用户点"重试"会复用 lastSendArgs 重新发起；不点也仍然能看到错误。
        const userMessage = errorDetail?.message ?? errText;
        return {
          ...prev,
          [threadKey]: {
            ...existing,
            messages: existing.messages.map((m) =>
              m.id === assistantId
                ? { ...m, content: `_错误：${userMessage}_` }
                : m,
            ),
            streaming: false,
            slow: false,
            errorDetail,
          },
        };
      });
    } finally {
      setActiveAIStream((prev) =>
        prev?.threadKey === threadKey ? null : prev,
      );
      if (activeAIAbortRef.current?.controller === controller) {
        activeAIAbortRef.current = null;
      }
    }
  };

  const stopMessage = (threadKey: string) => {
    const activeAbort = activeAIAbortRef.current;
    if (!activeAbort || activeAbort.threadKey !== threadKey) return;
    activeAbort.controller.abort();
  };

  // 方案 B (F4)：用 lastSendArgs 重新发起调用。
  //
  // 设计选择：保留失败历史，把每次重试都作为一对新的 user / assistant 追加
  // 到 messages 里——而不是抹掉上次失败那对然后假装从未发生过。理由：
  //   1. 用户视角更透明：能直观看到"我已经重试过 N 次都没成功"，方便决定
  //      要不要换个问法或先放弃；
  //   2. AI 视角无副作用：sendMessage 内部 historyForApi 只挑 messages 里
  //      role==='user' 的内容做拼装，错误占位（content 以 `_错误：` 开头的
  //      assistant 消息）作为 role='assistant' 也会被带上去，但语义就是"上
  //      下文里包含了之前失败留痕"，并不会污染 AI 的判断；
  //   3. 跟 IM 类工具的"重新发送失败的消息"心智一致。
  //
  // 因此这里只清交互态（errorDetail / slow / streaming），messages 不动；
  // sendMessage 会按正常流程在尾部 append 新的 user / assistant 占位。
  const retryLastSend = async (threadKey: string) => {
    const state = aiThreadsRef.current[threadKey];
    const args = state?.lastSendArgs;
    if (!args || state?.streaming) return;
    setAiThreads((prev) => {
      const existing = prev[threadKey];
      if (!existing) return prev;
      return {
        ...prev,
        [threadKey]: {
          ...existing,
          errorDetail: null,
          slow: false,
        },
      };
    });
    await sendMessage(args);
  };

  useEffect(() => {
    void load();
  }, [load]);

  // Reconcile the server-side persisted filter with the synchronously-read
  // localStorage mirror. Mirror is the source of truth for the boot frame;
  // server is authoritative across devices and overwrites the mirror on
  // success. Failures are silent — the cached value remains in effect.
  useEffect(() => {
    let cancelled = false;
    fetchPreferences()
      .then((prefs) => {
        if (cancelled) return;
        const fromServer = parseListFilter(prefs[FILTER_PREF_KEY]);
        setListFilter(fromServer);
        writeCachedListFilter(fromServer);
      })
      .catch(() => {
        // ignore — keep cached value
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleListFilterChange = useCallback((next: MatterListFilter) => {
    setListFilter(next);
    writeCachedListFilter(next);
    setPreference(FILTER_PREF_KEY, next).catch(() => {
      // server write failed; the in-memory state + local cache are still
      // updated so the current session works. Next session will fall back
      // to whatever the server has, which is ok — losing one filter toggle
      // is harmless.
    });
  }, []);

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

  // Local-action refresh channel: things like POST /files/.../read mutate
  // server state in a way that the matter list cares about (red/gray
  // counts shift) but don't fire SSE. The originating component
  // publishes here, we silently refetch the list — without going through
  // the SSE/resume path, which would also kick MatterDetailPane to
  // refetch the open detail page and step on FileCard's optimistic state.
  useEffect(
    () =>
      subscribeListRefresh(() => {
        scheduleRefresh("matters-list", refreshMattersSilently);
      }),
    [refreshMattersSilently],
  );

  useEffect(
    () =>
      subscribeDraftsRefresh(() => {
        scheduleRefresh("drafts-list", load);
      }),
    [load],
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
            // /new hides the sidebar entirely on every breakpoint.
            hideSidebar
              ? "hidden"
              : isThreadView
                ? "hidden md:block"
                : "block w-full",
            // desktop width
            sidebarOpen && !hideSidebar
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
          {sidebarOpen && !hideSidebar && (
            <ThreadListPane
              drafts={drafts}
              matters={matters}
              onRemoveDraft={removeDraft}
              listFilter={listFilter}
              onListFilterChange={handleListFilterChange}
            />
          )}
        </aside>
        {sidebarOpen && !hideSidebar && (
          <div
            className="group relative hidden w-3 shrink-0 cursor-col-resize items-stretch justify-center md:flex"
            onMouseDown={startSidebarResize}
            style={{ cursor: SIDEBAR_RESIZE_CURSOR }}
            title="拖拽调整导航栏宽度"
          >
            <div className="pointer-events-none flex items-center text-[var(--text-mute)] transition-colors group-hover:text-[var(--accent)]">
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
                  stopMessage,
                  retryLastSend,
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
          {me.roles?.includes("admin") && (
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
          )}
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
