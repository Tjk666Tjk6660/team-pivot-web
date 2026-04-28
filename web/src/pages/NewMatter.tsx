import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft } from "lucide-react";
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
const NARROW_HINT_KEY = "pivot:newmatter:hint-dismissed";
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
  const [stage, setStage] = useState<"idle" | "generating" | "submitting">("idle");
  const submitting = stage !== "idle";
  const [draftId, setDraftId] = useState<string | null>(null);
  const [draftLoaded, setDraftLoaded] = useState(false);
  const [showNarrowHint, setShowNarrowHint] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return !window.localStorage.getItem(NARROW_HINT_KEY);
  });

  const dismissNarrowHint = () => {
    setShowNarrowHint(false);
    try {
      window.localStorage.setItem(NARROW_HINT_KEY, "1");
    } catch {
      // localStorage may be disabled; the hint reappearing is harmless.
    }
  };

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
      },
    }),
    enabled: draftLoaded && isDirty && stage === "idle",
    deps: [
      draftLoaded, isDirty, stage,
      title, category, body, initialType, owner, ownerDisplayName,
      bodyState.body_source, bodyState.body_source_snapshot, aiSummary,
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
    // On narrow screens AIPane stacks below the form. Scroll the body
    // textarea into view so the user notices the AI fill landed and can
    // immediately review/publish. requestAnimationFrame waits one frame
    // so the body state has flushed and the textarea has been re-rendered
    // with the new content height.
    if (
      typeof window !== "undefined" &&
      !window.matchMedia("(min-width: 768px)").matches
    ) {
      requestAnimationFrame(() => {
        bodyRef.current?.scrollIntoView({
          behavior: "smooth",
          block: "center",
        });
      });
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
    if (!title.trim()) return toast.error("title 必填");
    if (!body.trim()) return toast.error("正文必填（AI 将基于此生成 summary）");

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
      // AIPane is always visible in the right column on this page; no toggle
      // needed. On narrow screens the user may need to scroll/expand it.
      toast.success("内容已填入 AI 输入框，可以继续追加说明再发送");
      return;
    }
    await performCreate(finalSource);
  };

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto md:flex-row md:overflow-hidden">
      {qualityDialog}
      <div className="min-h-0 flex-1 overflow-y-auto">
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
              这里直接进入 matter 的起草区。你可以和右侧 AI 助手讨论后让它起草，也可以直接手写正文；表单会自动保存草稿，不需要额外操作。
            </p>
          </div>

          {showNarrowHint && (
            <div
              className="flex items-start justify-between gap-2 rounded-[var(--r-md)] px-3 py-2 text-xs leading-5 md:hidden"
              style={{
                background:
                  "color-mix(in srgb, var(--accent) 12%, var(--surface))",
                border: "1px solid var(--accent-soft)",
                color: "var(--text)",
              }}
            >
              <span>💬 AI 助手可以帮你起草——下滑到底部展开 AI 区域</span>
              <button
                type="button"
                onClick={dismissNarrowHint}
                className="shrink-0 text-[var(--text-mute)] hover:text-[var(--text)]"
                aria-label="关闭提示"
              >
                ×
              </button>
            </div>
          )}

          <Card className="paper-panel rounded-[1.25rem] border sm:rounded-[1.75rem]">
            <form onSubmit={submit} className="space-y-6 p-4 sm:p-8">
              {/* Category */}
              <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
                <div className="space-y-2">
                  <div className="section-kicker">Category</div>
                  <p className="text-sm leading-6 text-[var(--text-mute)]">
                    从已有分类里选择，或者当场创建一个新的分类。
                  </p>
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="category">Category</Label>
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
                          placeholder="输入新的 category"
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
                        支持中文，最长 20 个字符；不能包含 <span className="font-mono">/ \ : * ? " &lt; &gt; |</span> 或换行。
                      </p>
                    </div>
                  )}
                </div>
              </div>

              <div className="editor-divider border-t" />

              {/* Title */}
              <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
                <div className="space-y-2">
                  <div className="section-kicker">Title</div>
                  <p className="text-sm leading-6 text-[var(--text-mute)]">标题决定 matter 在左侧目录里的可读性，尽量写成一个完整的主题句。</p>
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
                    适合直接写提案、背景、判断和待讨论问题，类型为 <span className="font-mono">think</span> 或{" "}
                    <span className="font-mono">act</span>。默认 think。
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

      {/* AI assistant column. PC: fixed-width right column; narrow: stacks
          below the form so the user lands on the form first. */}
      <aside
        className="flex min-h-[26rem] shrink-0 flex-col border-t bg-[var(--surface)] p-3 sm:p-4 md:h-full md:w-[420px] md:border-l md:border-t-0"
        style={{ borderColor: "var(--line)" }}
      >
        <AIPane
          mode="new-matter"
          matter_id={NEW_MATTER_PSEUDO_ID}
          threadKey={threadKey}
          threadTitle={title.trim() || "新讨论"}
          hasReplyDraft={false}
          onUseDraftAsReply={handleAIDraft}
        />
      </aside>
    </div>
  );
}
