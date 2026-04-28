import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, Bot, Sparkles, X } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  createMatter,
  deleteDraft,
  fetchDrafts,
  fetchMatters,
  streamAIChat,
  type DocType,
  type Me,
} from "@/api";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { OwnerPicker } from "@/components/matter/OwnerPicker";
import { AIPane } from "@/components/AIPane";
import {
  MentionField,
  emptyMention,
  isMentionValid,
} from "@/components/MentionField";
import type { MentionBlock } from "@/api";
import { formatSaveStatus, useDraftAutosave } from "@/hooks/useDraftAutosave";
import {
  applyAIDraft,
  computeAtPublish,
  onUserEdit,
  type BodySourceState,
} from "@/lib/bodySource";
import { useConfirmPublishQuality } from "@/hooks/useConfirmPublishQuality";
import { newMatterThreadKey, useDashboard } from "@/pages/Dashboard";

const NEW_CATEGORY_OPTION = "__new_category__";
const CATEGORY_PATTERN = /^[^/\\:*?"<>|\t\n\r]{1,20}$/;
// Special matter_id sent to /api/ai/matters/{id}/chat in new-matter mode.
// Backend ignores it because the chat handler now branches on `mode` rather
// than looking up the matter; we keep a stable string for log readability.
const NEW_MATTER_PSEUDO_ID = "_new_matter_";

export function NewMatter({ me }: { me: Me }) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const draftIdFromUrl = searchParams.get("draft");
  const [category, setCategory] = useState("");
  const [newCategory, setNewCategory] = useState("");
  const [categoryMode, setCategoryMode] = useState<"select" | "create">("select");
  const [availableCategories, setAvailableCategories] = useState<string[]>([]);
  const [title, setTitle] = useState("");
  const [aiTitleSuggestion, setAiTitleSuggestion] = useState<string | null>(null);
  const [initialType, setInitialType] = useState<DocType>("think");
  const [body, setBody] = useState("");
  const [bodyState, setBodyState] = useState<BodySourceState>({
    body_source: "manual",
  });
  // Cached AI <summary> from path A. When present, submit() uses it directly
  // instead of firing the legacy "summary-from-body" AI call.
  const [aiSummary, setAiSummary] = useState<string>("");
  const [owner, setOwner] = useState<string>(me.open_id);
  const [ownerDisplayName, setOwnerDisplayName] = useState<string>(me.name);
  const [mentions, setMentions] = useState<MentionBlock>(() => emptyMention());
  const [stage, setStage] = useState<"idle" | "generating" | "submitting">("idle");
  const submitting = stage !== "idle";
  const [draftId, setDraftId] = useState<string | null>(null);
  const [draftLoaded, setDraftLoaded] = useState(false);
  // AIPane open state — default true so the assistant is visible the moment
  // the page loads. On md+ it's the permanent right column; on narrow it's a
  // fullscreen overlay the user can dismiss via the X.
  const [aiOpen, setAiOpen] = useState(true);

  const { ai } = useDashboard();
  const { dialog: qualityDialog, confirm: confirmPublishQuality } =
    useConfirmPublishQuality();

  // Track whether body was just set from an AI draft so the next onChange
  // tick (React batches setBody → re-render → controlled input echo) doesn't
  // immediately demote the source. Without this guard, the very same body
  // value passing through onChange would still cost one onUserEdit call.
  const lastAIWriteRef = useRef<string | null>(null);
  // Used to scroll the user back to the form after AI fills the body.
  // On narrow screens the AIPane stacks below the form, so after the AI
  // generates the draft the user otherwise stays at the AIPane section
  // and doesn't notice the body got filled.
  const bodyRef = useRef<HTMLTextAreaElement | null>(null);
  // Outer scroll container on narrow screens. We reset its scrollTop after
  // an AI fill so the user lands on the form (which is at the top), rather
  // than relying on scrollIntoView which races React's render commit.
  const pageScrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    Promise.all([fetchMatters(), fetchDrafts()])
      .then(([items, drafts]) => {
        const cats = Array.from(
          new Set(
            items
              .map((m) => m.category)
              .filter((c): c is string => typeof c === "string" && c.length > 0),
          ),
        );
        setAvailableCategories(cats);

        const proposalDrafts = drafts.filter(
          (d) => d.type === "proposal" && !d.thread_key,
        );
        const candidate = draftIdFromUrl
          ? (proposalDrafts.find((d) => d.id === draftIdFromUrl) ?? null)
          : (proposalDrafts.sort((a, b) => b.updated_at - a.updated_at)[0] ?? null);

        if (candidate) {
          setDraftId(candidate.id);
          setTitle(candidate.title ?? "");
          setBody(candidate.body_md ?? "");
          if (candidate.category) {
            setCategory(candidate.category);
          } else if (cats.length === 0) {
            setCategoryMode("create");
          } else {
            setCategory(cats[0]);
          }
          const payload = (candidate.matter_payload ?? {}) as Record<string, unknown>;
          const dt = String(payload.doc_type ?? "");
          if (dt === "act" || dt === "think") setInitialType(dt);
          const ow = String(payload.owner ?? "");
          if (ow) {
            setOwner(ow);
            const od = String(payload.owner_display ?? "");
            setOwnerDisplayName(od || (ow === me.open_id ? me.name : ""));
          }
          // Restore body_source from previous session so the quality gate
          // judges this draft correctly across reloads / devices.
          const bs = payload.body_source;
          const snap = payload.body_source_snapshot;
          if (bs === "ai" && typeof snap === "string") {
            setBodyState({ body_source: "ai", body_source_snapshot: snap });
          } else {
            setBodyState({ body_source: "manual" });
          }
          if (typeof payload.ai_summary === "string") {
            setAiSummary(payload.ai_summary);
          }
          const rawMentions = payload.mentions as
            | { open_ids?: unknown; comments?: unknown }
            | undefined;
          if (
            rawMentions &&
            Array.isArray(rawMentions.open_ids) &&
            typeof rawMentions.comments === "string"
          ) {
            setMentions({
              open_ids: rawMentions.open_ids as string[],
              comments: rawMentions.comments,
            });
          }
        } else if (cats.length === 0) {
          setCategoryMode("create");
        } else {
          setCategory((current) => current || cats[0]);
        }
      })
      .catch(() => {})
      .finally(() => setDraftLoaded(true));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const isDirty = title.trim().length > 0 || body.trim().length > 0;
  const { status: draftStatus } = useDraftAutosave({
    draftId,
    setDraftId,
    type: "proposal",
    payload: () => ({
      title: title.trim() || null,
      category: category.trim() || null,
      body_md: body,
      matter_payload: {
        doc_type: initialType,
        ...(owner ? { owner, owner_display: ownerDisplayName } : {}),
        body_source: bodyState.body_source,
        ...(bodyState.body_source_snapshot
          ? { body_source_snapshot: bodyState.body_source_snapshot }
          : {}),
        ...(aiSummary ? { ai_summary: aiSummary } : {}),
        ...(mentions.open_ids.length > 0 ? { mentions } : {}),
      },
    }),
    enabled: draftLoaded && isDirty && stage === "idle",
    deps: [
      draftLoaded, isDirty, stage,
      title, category, body, initialType, owner, ownerDisplayName,
      bodyState.body_source, bodyState.body_source_snapshot, aiSummary,
      mentions.open_ids.length, mentions.comments,
    ],
  });

  // Stable thread key for AIPane. Falls back to a placeholder before the
  // draft id materializes; once autosave creates the draft, the AIPane
  // remounts with the real key. We mitigate the rare lost-conversation case
  // by recommending the user type at least one form field before opening AI
  // (in practice everyone does anyway).
  const threadKey = useMemo(
    () => newMatterThreadKey(draftId ?? "tmp"),
    [draftId],
  );

  const titleAndBodyDirty = useMemo(
    () => ({ title: title.trim(), body: body.trim() }),
    [title, body],
  );

  const handleAIDraft = async (
    content: string,
    _replyTo: string,
    summary?: string,
    aiTitle?: string,
  ): Promise<boolean> => {
    lastAIWriteRef.current = content;
    setBody(content);
    setBodyState(applyAIDraft(content));
    if (summary) setAiSummary(summary);
    if (aiTitle && aiTitle.trim()) {
      const trimmed = aiTitle.trim();
      if (!titleAndBodyDirty.title) {
        setTitle(trimmed);
        setAiTitleSuggestion(null);
      } else if (trimmed !== titleAndBodyDirty.title) {
        setAiTitleSuggestion(trimmed);
      }
    }
    // On narrow screens AIPane is a fullscreen overlay; close it after a
    // successful fill so the user lands back on the form (mirrors how the
    // reply path auto-minimizes its AIPane in MatterDetailPane).
    if (
      typeof window !== "undefined" &&
      !window.matchMedia("(min-width: 768px)").matches
    ) {
      setAiOpen(false);
      // Scroll page back to top + briefly focus the body so the user sees
      // what AI just wrote. setTimeout > rAF — gives the overlay-close
      // animation a moment to commit before we re-focus.
      window.setTimeout(() => {
        pageScrollRef.current?.scrollTo({ top: 0, behavior: "smooth" });
        bodyRef.current?.focus({ preventScroll: true });
      }, 50);
    }
    return true;
  };

  const onBodyChange = (next: string) => {
    setBody(next);
    // If this onChange echoes the exact AI write we just performed, skip
    // re-evaluating the state machine (saves one LCS pass on long bodies).
    if (lastAIWriteRef.current !== null && next === lastAIWriteRef.current) {
      lastAIWriteRef.current = null;
      return;
    }
    lastAIWriteRef.current = null;
    setBodyState((s) => onUserEdit(s, next));
  };

  const adoptAITitle = () => {
    if (aiTitleSuggestion) {
      setTitle(aiTitleSuggestion);
      setAiTitleSuggestion(null);
    }
  };

  const categoryOptions = category.trim() && !availableCategories.includes(category.trim())
    ? [category.trim(), ...availableCategories]
    : availableCategories;

  const createCategory = () => {
    const next = newCategory.trim();
    if (!CATEGORY_PATTERN.test(next)) {
      toast.error('category 需为 1-20 个字符，且不能包含 / \\\\ : * ? " < > | 或换行');
      return;
    }
    setAvailableCategories((current) => (current.includes(next) ? current : [...current, next]));
    setCategory(next);
    setCategoryMode("select");
    setNewCategory("");
  };

  const generateSummaryFromBody = async (): Promise<string> => {
    const userMsg = [
      `请为下面这篇新增的 ${initialType} 文件生成一句不超过 80 字的中文 summary。`,
      `要求：`,
      `- 直接输出这一句话本身，不要加引号，也不要任何前后解释。`,
      `- 用最精简的语言概括这篇文件推进 / 判断 / 结论了什么。`,
      ``,
      `讨论标题：${title.trim()}`,
      ``,
      `新文件正文：`,
      "```",
      body.trim(),
      "```",
    ].join("\n");
    let acc = "";
    for await (const ev of streamAIChat(
      NEW_MATTER_PSEUDO_ID,
      [{ role: "user", content: userMsg }],
      null,
      undefined,
      "new-matter",
    )) {
      if (ev.kind === "delta") acc += ev.delta;
    }
    return acc.trim();
  };

  const performCreate = async (sourceForBackend: "ai" | "manual") => {
    setStage("generating");
    let summary = aiSummary.trim();
    if (!summary) {
      try {
        summary = await generateSummaryFromBody();
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "生成 summary 失败");
        setStage("idle");
        return;
      }
    }
    if (!summary) {
      toast.error("AI 生成的 summary 为空");
      setStage("idle");
      return;
    }

    setStage("submitting");
    try {
      const r = await createMatter({
        category: category.trim(),
        title: title.trim(),
        initial_file: {
          type: initialType,
          summary,
          body: body.trim(),
          owner: owner || undefined,
          body_source: sourceForBackend,
          // Match CreateFileDialog's encoding: matter has no top-level
          // mention concept, so the @-mentioned recipients ride on the
          // first comment alongside the user-typed sentence.
          ...(mentions.open_ids.length > 0
            ? {
                comments: [
                  {
                    body: mentions.comments.trim(),
                    mentions: mentions.open_ids,
                  },
                ],
              }
            : {}),
        },
      });
      if (draftId) {
        try {
          await deleteDraft(draftId);
        } catch {
          // Draft delete failure does not affect the published matter.
        }
      }
      navigate(`/m/${encodeURIComponent(r.matter_id)}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
      setStage("idle");
    }
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return toast.error("标题必填");
    if (!body.trim()) return toast.error("正文必填（AI 将基于此生成 summary）");
    if (!isMentionValid(mentions)) {
      return toast.error("圈人后必须填一句话");
    }

    const finalSource = computeAtPublish(bodyState, body);
    const active = ai.activeStream;
    const blockedByAIBusy =
      finalSource === "manual" &&
      !!active &&
      active.threadKey !== threadKey;

    const gate = await confirmPublishQuality({
      bodySource: finalSource,
      blockedByAIBusy,
      busyTitle: blockedByAIBusy ? active?.title : undefined,
    });
    if (gate === "cancel") return;
    if (gate === "send_to_ai") {
      ai.setInput(threadKey, body);
      // On narrow screens AIPane is hidden behind a button; force it open
      // so the user can see the content was filled and continue chatting.
      // On md+ the right column is always visible; setAiOpen is harmless.
      setAiOpen(true);
      toast.success("内容已填入 AI 输入框，可以继续追加说明再发送");
      return;
    }
    await performCreate(finalSource);
  };

  return (
    <div
      ref={pageScrollRef}
      className="flex h-full min-h-0 flex-col overflow-y-auto md:flex-row md:overflow-hidden"
    >
      {qualityDialog}
      {/* On narrow screens the outer container is the sole scroller so the
          page reads as one continuous flow (form, then AIPane below). On md+
          the form column gets its own internal scroll so it can be tall
          without pushing AIPane out of the side panel. */}
      <div className="min-h-0 flex-1 md:overflow-y-auto">
        <div className="mx-auto w-full max-w-4xl space-y-4 px-3 py-4 sm:px-5 sm:py-5 md:space-y-6">
          <Button
            asChild
            variant="ghost"
            size="sm"
            className="rounded-[var(--r-md)] px-3 text-[var(--text-soft)] hover:bg-[var(--surface-alt)]"
          >
            <Link to="/">
              <ArrowLeft className="h-4 w-4" />
              返回 matter 列表
            </Link>
          </Button>

          <div className="space-y-2">
            <div className="section-kicker">New Matter</div>
            <div className="flex flex-wrap items-baseline gap-3">
              <h1 className="text-2xl font-semibold tracking-[-0.03em] text-[var(--text)] sm:text-3xl">
                新讨论
              </h1>
              {draftStatus !== "idle" && (
                <span
                  className={
                    draftStatus === "error"
                      ? "text-xs text-[var(--danger-600)]"
                      : "text-xs text-[var(--text-mute)]"
                  }
                >
                  {formatSaveStatus(draftStatus)}
                </span>
              )}
              {bodyState.body_source === "ai" && (
                <span className="text-xs text-[var(--accent)]">
                  ✦ AI 协作草稿
                </span>
              )}
            </div>
            <p className="max-w-2xl text-sm leading-7 text-[var(--text-soft)]">
              和右侧 AI 助手讨论后让它起草，或者直接手写。表单会自动保存草稿。
            </p>
          </div>

          {/* AI assistant trigger: only on narrow screens. On md+ the AIPane
              is permanently visible as the right column, so this button is
              hidden to avoid duplication. */}
          <Button
            type="button"
            variant="outline"
            className="md:hidden flex w-full items-center justify-center gap-2 rounded-[var(--r-md)]"
            onClick={() => setAiOpen(true)}
          >
            <Sparkles className="h-4 w-4 text-[var(--accent)]" />
            AI 助手 · 帮你起草
          </Button>

          <Card className="paper-panel rounded-[1.25rem] border sm:rounded-[1.75rem]">
            <form onSubmit={submit} className="space-y-6 p-4 sm:p-8">
              {/* Category */}
              <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
                <div className="space-y-2">
                  <div className="section-kicker">种类</div>
                  <p className="text-sm leading-6 text-[var(--text-mute)]">
                    选已有，或新建一个。
                  </p>
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="category">种类</Label>
                  <select
                    id="category"
                    value={categoryMode === "create" ? NEW_CATEGORY_OPTION : category}
                    onChange={(e) => {
                      const next = e.target.value;
                      if (next === NEW_CATEGORY_OPTION) {
                        setCategoryMode("create");
                        setNewCategory("");
                        return;
                      }
                      setCategoryMode("select");
                      setNewCategory("");
                      setCategory(next);
                    }}
                    required
                    className="flex h-11 w-full rounded-[var(--r-md)] border border-input bg-[var(--surface-alt)] px-3 py-2 text-sm ring-offset-background"
                  >
                    {categoryOptions.length === 0 && <option value="general">general</option>}
                    {categoryOptions.map((opt) => (
                      <option key={opt} value={opt}>
                        {opt}
                      </option>
                    ))}
                    <option value={NEW_CATEGORY_OPTION}>+ 新建 category</option>
                  </select>
                  {categoryMode === "create" && (
                    <div className="space-y-1.5">
                      <div className="flex gap-2">
                        <Input
                          value={newCategory}
                          onChange={(e) => setNewCategory(e.target.value)}
                          placeholder="输入新种类名称"
                          maxLength={20}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              e.preventDefault();
                              createCategory();
                            }
                          }}
                        />
                        <Button type="button" variant="outline" className="rounded-[var(--r-md)]" onClick={createCategory}>
                          创建并选中
                        </Button>
                      </div>
                      <p className="text-xs leading-5 text-[var(--text-mute)]">
                        最长 20 字；不能含 <span className="font-mono">/ \ : * ? " &lt; &gt; |</span> 或换行。
                      </p>
                    </div>
                  )}
                </div>
              </div>

              <div className="editor-divider border-t" />

              {/* Title */}
              <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
                <div className="space-y-2">
                  <div className="section-kicker">标题</div>
                  <p className="text-sm leading-6 text-[var(--text-mute)]">写一句完整的主题句。</p>
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="title">标题</Label>
                  <Input
                    id="title"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    required
                    maxLength={200}
                    className="h-11 rounded-[var(--r-md)] bg-[var(--surface-alt)]"
                  />
                  {aiTitleSuggestion && aiTitleSuggestion !== title && (
                    <button
                      type="button"
                      onClick={adoptAITitle}
                      className="self-start text-xs text-[var(--text-mute)] hover:text-[var(--accent)]"
                    >
                      AI 建议：{aiTitleSuggestion} · 点击采用
                    </button>
                  )}
                </div>
              </div>

              <div className="editor-divider border-t" />

              {/* Initial file type */}
              <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
                <div className="space-y-2">
                  <div className="section-kicker">首篇文件</div>
                  <p className="text-sm leading-6 text-[var(--text-mute)]">
                    <span className="font-mono">think</span> 写判断 / 方案，<span className="font-mono">act</span> 推进行动。默认 think。
                  </p>
                </div>
                <div className="space-y-3">
                  <div className="flex gap-5 text-sm">
                    <label className="flex items-center gap-1.5">
                      <input
                        type="radio"
                        checked={initialType === "think"}
                        onChange={() => setInitialType("think")}
                      />
                      think（记录判断 / 方案）
                    </label>
                    <label className="flex items-center gap-1.5">
                      <input
                        type="radio"
                        checked={initialType === "act"}
                        onChange={() => setInitialType("act")}
                      />
                      act（记录一项待推进的行动）
                    </label>
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="body">
                      正文（markdown）<span className="text-[var(--danger-500)]"> *</span>
                    </Label>
                    <p className="text-xs text-[var(--text-mute)]">
                      可以让 AI 帮你起草（右侧），也可以直接在这里写。
                    </p>
                    <Textarea
                      ref={bodyRef}
                      id="body"
                      value={body}
                      onChange={(e) => onBodyChange(e.target.value)}
                      required
                      rows={10}
                      maxLength={50000}
                      className="min-h-[14rem] rounded-[var(--r-md)] border-[var(--line-strong)] bg-[var(--surface-alt)] font-mono text-sm"
                    />
                  </div>
                  {initialType === "act" && (
                    <div className="grid gap-2">
                      <Label>Owner（执行人 · 默认你自己）</Label>
                      <OwnerPicker
                        value={owner}
                        onChange={(openId, name) => {
                          setOwner(openId);
                          setOwnerDisplayName(name);
                        }}
                        sessionOpenId={me.open_id}
                        sessionName={me.name}
                        displayName={ownerDisplayName}
                      />
                    </div>
                  )}
                </div>
              </div>

              <div className="editor-divider border-t" />

              {/* Mentions: identical encoding to CreateFileDialog — recipients
                  ride on the first comment along with the user-typed sentence. */}
              <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
                <div className="space-y-2">
                  <div className="section-kicker">圈人</div>
                  <p className="text-sm leading-6 text-[var(--text-mute)]">
                    可选。圈到的人会在飞书里收到通知。
                  </p>
                </div>
                <div>
                  <MentionField
                    value={mentions}
                    onChange={setMentions}
                  />
                </div>
              </div>

              <div className="flex flex-wrap gap-3 pt-2">
                <Button
                  type="submit"
                  className="rounded-[var(--r-md)] px-5"
                  disabled={submitting || !title.trim() || !body.trim()}
                >
                  {stage === "generating"
                    ? "生成摘要中…"
                    : stage === "submitting"
                      ? "创建中…"
                      : "创建 Matter"}
                </Button>
              </div>
            </form>
          </Card>
        </div>
      </div>

      {/* AI assistant: fullscreen overlay on narrow screens (toggled by the
          "AI 助手" button), persistent right column on md+. Mirrors the
          reply path UX in MatterDetailPane. */}
      <aside
        className={cn(
          "flex min-h-0 flex-col overflow-hidden bg-[var(--surface)]",
          // Narrow: fullscreen overlay, controlled by aiOpen.
          aiOpen ? "fixed inset-0 z-50" : "hidden",
          // md+: ignore aiOpen, render as permanent right column.
          "md:static md:flex md:h-full md:w-[420px] md:shrink-0 md:border-l md:border-l-[var(--line)] md:p-3 md:sm:p-4",
        )}
      >
        {/* Mobile-only header with close button. md+ doesn't need it
            because the panel is always present beside the form. */}
        <div
          className="flex items-center justify-between border-b border-[var(--line)] px-4 py-3 md:hidden"
        >
          <div className="flex items-center gap-2 text-sm font-medium text-[var(--text)]">
            <Bot className="h-4 w-4 text-[var(--accent)]" />
            AI 助手
          </div>
          <button
            type="button"
            onClick={() => setAiOpen(false)}
            className="rounded-[var(--r-sm)] p-1 text-[var(--text-mute)] hover:bg-[var(--surface-alt)] hover:text-[var(--text)]"
            aria-label="关闭 AI 助手"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="min-h-0 flex-1 p-3 sm:p-4 md:p-0">
          <AIPane
            mode="new-matter"
            matter_id={NEW_MATTER_PSEUDO_ID}
            threadKey={threadKey}
            threadTitle={title.trim() || "新讨论"}
            // Treat any existing body as "draft already filled" so AIPane
            // asks the overwrite confirm before AI replaces user content.
            hasReplyDraft={!!body.trim()}
            onUseDraftAsReply={handleAIDraft}
          />
        </div>
      </aside>
    </div>
  );
}
