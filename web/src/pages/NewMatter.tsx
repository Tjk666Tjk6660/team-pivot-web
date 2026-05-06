import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
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
  type CategoryVisibilityScope,
  type VisibilityScope,
} from "@/api";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { OwnerPicker } from "@/components/matter/OwnerPicker";
import {
  MentionField,
  emptyMention,
  isMentionValid,
} from "@/components/MentionField";
import { searchContacts, type MentionBlock } from "@/api";
import { formatSaveStatus, useDraftAutosave } from "@/hooks/useDraftAutosave";
import {
  computeAtPublish,
  onUserEdit,
  type BodySourceState,
} from "@/lib/bodySource";
import { useConfirmPublishQuality } from "@/hooks/useConfirmPublishQuality";
import {
  NewMatterGuidedFlow,
  type ClassicBridgeSnapshot,
} from "@/pages/NewMatterGuidedFlow";
import { publishDraftsRefresh } from "@/events/listRefresh";
import { VisibilityScopePicker } from "@/components/visibility/VisibilityScopePicker";

const NEW_CATEGORY_OPTION = "__new_category__";
const CATEGORY_PATTERN = /^[^/\\:*?"<>|\t\n\r]{1,20}$/;
// Special matter_id sent to /api/ai/matters/{id}/chat in new-matter mode.
// Backend ignores it because the chat handler now branches on `mode` rather
// than looking up the matter; we keep a stable string for log readability.
const NEW_MATTER_PSEUDO_ID = "_new_matter_";
const PUBLIC_VISIBILITY: VisibilityScope = { mode: "public", roles: [], user_ids: [] };
const PUBLIC_CATEGORY_VISIBILITY: CategoryVisibilityScope = {
  mode: "public",
  authorized_roles: [],
};

function categoryScopeToVisibility(scope: CategoryVisibilityScope): VisibilityScope {
  return {
    mode: scope.mode,
    roles: scope.mode === "restricted" ? scope.authorized_roles : [],
    user_ids: [],
  };
}

function visibilityToCategoryScope(scope: VisibilityScope): CategoryVisibilityScope {
  return {
    mode: scope.mode === "restricted" && scope.roles.length > 0
      ? "restricted"
      : "public",
    authorized_roles: scope.mode === "restricted" ? scope.roles : [],
  };
}

export function NewMatter({ me }: { me: Me }) {
  // Two paths: guided AI conversation (default, mirrors AICraft demo) and the
  // classic form for users who already know what they want to write.
  // bridge carries the classic form's full snapshot (title, category, type,
  // mentions, body) across into the guided flow when the user picks
  // "进行 AI 讨论" in the publish quality gate. The guided flow then skips
  // the manual steps and jumps straight to AI drafting.
  const [searchParams] = useSearchParams();
  const hasDraftParam = !!searchParams.get("draft");
  const [mode, setMode] = useState<"guided" | "classic">(
    () => (hasDraftParam ? "classic" : "guided"),
  );
  const [bridge, setBridge] = useState<ClassicBridgeSnapshot | null>(null);
  const [classicSeed, setClassicSeed] = useState<ClassicBridgeSnapshot | null>(null);
  if (mode === "guided") {
    return (
      <NewMatterGuidedFlow
        me={me}
        initialBridge={bridge ?? undefined}
        onSwitchToClassic={(snapshot) => {
          setBridge(null);
          setClassicSeed(snapshot ?? null);
          setMode("classic");
        }}
      />
    );
  }
  return (
    <NewMatterClassicForm
      me={me}
      initialSnapshot={classicSeed ?? undefined}
      onSwitchToGuided={() => {
        setBridge(null);
        setClassicSeed(null);
        setMode("guided");
      }}
      onSwitchToGuidedWithSnapshot={(snap) => {
        setBridge(snap);
        setClassicSeed(null);
        setMode("guided");
      }}
    />
  );
}

function NewMatterClassicForm({
  me,
  initialSnapshot,
  onSwitchToGuided,
  onSwitchToGuidedWithSnapshot,
}: {
  me: Me;
  initialSnapshot?: ClassicBridgeSnapshot;
  onSwitchToGuided: () => void;
  onSwitchToGuidedWithSnapshot: (snap: ClassicBridgeSnapshot) => void;
}) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const draftIdFromUrl = searchParams.get("draft");
  const [category, setCategory] = useState(() => initialSnapshot?.category ?? "");
  const [newCategory, setNewCategory] = useState("");
  const [categoryMode, setCategoryMode] = useState<"select" | "create">("select");
  const [createdCategory, setCreatedCategory] = useState<string | null>(
    () => initialSnapshot?.createdCategory ?? null,
  );
  const [categoryVisibility, setCategoryVisibility] =
    useState<CategoryVisibilityScope>(
      () => initialSnapshot?.categoryVisibility ?? PUBLIC_CATEGORY_VISIBILITY,
    );
  const [availableCategories, setAvailableCategories] = useState<string[]>([]);
  const [title, setTitle] = useState(() => initialSnapshot?.title ?? "");
  const [initialType, setInitialType] = useState<DocType>(
    () => initialSnapshot?.docType ?? "think",
  );
  const [body, setBody] = useState(() => initialSnapshot?.body ?? "");
  const [bodyState, setBodyState] = useState<BodySourceState>({
    body_source: initialSnapshot?.body ? "ai" : "manual",
    ...(initialSnapshot?.body ? { body_source_snapshot: initialSnapshot.body } : {}),
  });
  const [matterOwner, setMatterOwner] = useState<{ pivotUserId: string; name: string }>(
    () => initialSnapshot?.matterOwner ?? ({
      pivotUserId: me.id,
      name: me.name,
    }),
  );
  const [owner, setOwner] = useState<string>(me.open_id);
  const [ownerDisplayName, setOwnerDisplayName] = useState<string>(me.name);
  const [mentions, setMentions] = useState<MentionBlock>(
    () => initialSnapshot?.mentions ?? emptyMention(),
  );
  const [visibility, setVisibility] = useState<VisibilityScope>(
    () => initialSnapshot?.matterVisibility ?? PUBLIC_VISIBILITY,
  );
  const [stage, setStage] = useState<"idle" | "generating" | "submitting">("idle");
  const submitting = stage !== "idle";
  const [draftId, setDraftId] = useState<string | null>(null);
  const [draftLoaded, setDraftLoaded] = useState(false);
  // Resolved open_id → display-name map for the mention chips. MentionField
  // mutates this in place when the user picks from the dropdown, but on
  // draft restore we only have open_ids — fetch the names lazily.
  const [resolvedNames, setResolvedNames] = useState<Record<string, string>>({});

  const { dialog: qualityDialog, confirm: confirmPublishQuality } =
    useConfirmPublishQuality();

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
        setAvailableCategories(
          initialSnapshot?.category && !cats.includes(initialSnapshot.category)
            ? [...cats, initialSnapshot.category]
            : cats,
        );

        if (initialSnapshot) {
          // Snapshot from guided flow may have empty category (user skipped
          // that step). Without backfill the dropdown visually shows cats[0]
          // but state stays "" → submit fails with 422 category-min-length.
          if (!initialSnapshot.category && cats.length > 0) {
            setCategory((current) => current || cats[0]);
          } else if (cats.length === 0) {
            setCategoryMode("create");
          }
          return;
        }

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
            if (!cats.includes(candidate.category)) {
              setCreatedCategory(candidate.category);
            }
          } else if (cats.length === 0) {
            setCategoryMode("create");
          } else {
            setCategory(cats[0]);
          }
          const payload = (candidate.matter_payload ?? {}) as Record<string, unknown>;
          const dt = String(payload.doc_type ?? "");
          if (dt === "act" || dt === "think") setInitialType(dt);
          const matterOwnerPivotUserId = String(payload.matter_owner ?? "");
          if (matterOwnerPivotUserId) {
            const matterOwnerName = String(payload.matter_owner_display ?? "");
            setMatterOwner({
              pivotUserId: matterOwnerPivotUserId,
              name:
                matterOwnerName ||
                (matterOwnerPivotUserId === me.id ? me.name : ""),
            });
          }
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
          const rawCategoryVisibility = payload.category_visibility as
            | CategoryVisibilityScope
            | undefined;
          if (
            rawCategoryVisibility &&
            (rawCategoryVisibility.mode === "public" ||
              rawCategoryVisibility.mode === "restricted") &&
            Array.isArray(rawCategoryVisibility.authorized_roles)
          ) {
            setCategoryVisibility(rawCategoryVisibility);
          }
          const rawMatterVisibility = payload.matter_visibility as
            | VisibilityScope
            | undefined;
          if (
            rawMatterVisibility &&
            (rawMatterVisibility.mode === "public" ||
              rawMatterVisibility.mode === "restricted") &&
            Array.isArray(rawMatterVisibility.roles) &&
            Array.isArray(rawMatterVisibility.user_ids)
          ) {
            setVisibility(rawMatterVisibility);
          }
          const restoredCreatedCategory = payload.created_category;
          if (typeof restoredCreatedCategory === "string" && restoredCreatedCategory) {
            setCreatedCategory(restoredCreatedCategory);
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

  // Resolve newly-restored open_ids → display names so mention chips show
  // "@李帅" instead of "@ou_737f4". Mirrors the same effect inside
  // CreateFileForm. Per-id failures are swallowed; the chip falls back to a
  // sliced open_id, which is acceptable.
  useEffect(() => {
    const missing = mentions.open_ids.filter((oid) => !(oid in resolvedNames));
    if (missing.length === 0) return;
    let cancelled = false;
    void (async () => {
      const fresh: Record<string, string> = {};
      for (const oid of missing) {
        try {
          const results = await searchContacts(oid);
          const found = results.find((c) => c.open_id === oid);
          if (found) fresh[oid] = found.name;
        } catch {
          /* per-id failure does not block the rest */
        }
      }
      if (cancelled || Object.keys(fresh).length === 0) return;
      setResolvedNames((prev) => ({ ...prev, ...fresh }));
    })();
    return () => {
      cancelled = true;
    };
    // resolvedNames is intentionally omitted — it's only ever extended, so
    // including it would create a redundant re-run.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mentions.open_ids]);

  const isDirty = title.trim().length > 0 || body.trim().length > 0;
  const { status: draftStatus, saveNow } = useDraftAutosave({
    draftId,
    setDraftId,
    type: "proposal",
    payload: () => ({
      title: title.trim() || null,
      category: category.trim() || null,
      body_md: body,
      matter_payload: {
        doc_type: initialType,
        matter_owner: matterOwner.pivotUserId,
        matter_owner_display: matterOwner.name,
        ...(owner ? { owner, owner_display: ownerDisplayName } : {}),
        body_source: bodyState.body_source,
        ...(bodyState.body_source_snapshot
          ? { body_source_snapshot: bodyState.body_source_snapshot }
          : {}),
        ...(mentions.open_ids.length > 0 ? { mentions } : {}),
        category_visibility: categoryVisibility,
        matter_visibility: visibility,
        created_category: createdCategory,
      },
    }),
    enabled: draftLoaded && isDirty && stage === "idle",
    deps: [
      draftLoaded, isDirty, stage,
      title, category, body, initialType,
      matterOwner.pivotUserId, matterOwner.name, owner, ownerDisplayName,
      bodyState.body_source, bodyState.body_source_snapshot,
      mentions.open_ids.length, mentions.comments,
      categoryVisibility.mode, categoryVisibility.authorized_roles.join("|"),
      visibility.mode, visibility.roles.join("|"), visibility.user_ids.join("|"),
      createdCategory,
    ],
  });

  const onBodyChange = (next: string) => {
    setBody(next);
    setBodyState((s) => onUserEdit(s, next));
  };

  const handleBackToList = async () => {
    if (isDirty) {
      const savedId = await saveNow();
      if (!savedId) {
        toast.error("草稿保存失败，请稍后重试");
        return;
      }
      publishDraftsRefresh();
    }
    navigate("/");
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
    setCreatedCategory(next);
    setCategoryVisibility(PUBLIC_CATEGORY_VISIBILITY);
    setCategoryMode("select");
    setNewCategory("");
  };

  const isNewCategory = !!createdCategory && category.trim() === createdCategory;
  const categoryAllowedRoles =
    isNewCategory && categoryVisibility.mode === "restricted"
      ? categoryVisibility.authorized_roles
      : undefined;

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
    let summary = "";
    try {
      summary = await generateSummaryFromBody();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "生成 summary 失败");
      setStage("idle");
      return;
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
        owner_pivot_user_id: matterOwner.pivotUserId || me.id,
        visibility,
        new_category_visibility:
          isNewCategory
            ? categoryVisibility
            : undefined,
        initial_file: {
          type: initialType,
          summary,
          body: body.trim(),
          owner: owner || undefined,
          body_source: sourceForBackend,
          // Match CreateFileDialog's encoding: matter has no top-level
          // mention concept, so the @-mentioned recipients ride on the
          // first mention alongside the user-typed sentence.
          ...(mentions.open_ids.length > 0
            ? {
                mentions: [
                  {
                    body: mentions.comments.trim(),
                    targets: mentions.open_ids,
                  },
                ],
              }
            : {}),
        },
      });
      if (draftId) {
        try {
          await deleteDraft(draftId);
          publishDraftsRefresh();
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

    if (isNewCategory && categoryVisibility.mode === "restricted") {
      if (categoryVisibility.authorized_roles.length === 0) {
        return toast.error("Category 指定角色可见时，至少选择一个角色");
      }
      if (
        visibility.mode === "restricted" &&
        visibility.roles.some((role) => !categoryVisibility.authorized_roles.includes(role))
      ) {
        return toast.error("Matter 可见范围不能超过 Category");
      }
    }

    const finalSource = computeAtPublish(bodyState, body);
    const gate = await confirmPublishQuality({
      bodySource: finalSource,
      // Classic mode has no AI side panel anymore, so "busy" never applies.
      blockedByAIBusy: false,
    });
    if (gate === "cancel") return;
    if (gate === "send_to_ai") {
      // Hand the full form snapshot off to the guided flow. The guided flow
      // skips the manual question-and-answer steps and goes straight to AI
      // drafting based on the user's typed content.
      onSwitchToGuidedWithSnapshot({
        body,
        title: title.trim(),
        category: category.trim(),
        docType: initialType,
        matterOwner,
        mentions,
        categoryVisibility,
        matterVisibility: visibility,
        createdCategory,
      });
      toast.success("已切换到 AI 引导，正在为你重新起草…");
      return;
    }
    await performCreate(finalSource);
  };

  return (
    <div className="h-full min-h-0 overflow-y-auto">
      {qualityDialog}
      <div className="mx-auto w-full max-w-4xl space-y-4 px-3 py-4 sm:px-5 sm:py-5 md:space-y-6">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="rounded-[var(--r-md)] px-3 text-[var(--text-soft)] hover:bg-[var(--surface-alt)]"
            onClick={() => void handleBackToList()}
          >
              <ArrowLeft className="h-4 w-4" />
              返回 matter 列表
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
              直接手写正文。需要 AI 帮你起草，可以
              <button
                type="button"
                onClick={onSwitchToGuided}
                className="ml-1 text-[var(--accent)] underline-offset-2 hover:underline"
              >
                切回 AI 引导
              </button>
              。表单会自动保存草稿。
            </p>
          </div>

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
                  <Label htmlFor="category" className="sr-only">
                    种类
                  </Label>
                  <select
                    id="category"
                    value={categoryMode === "create" ? NEW_CATEGORY_OPTION : category}
                    onChange={(e) => {
                      const next = e.target.value;
                      if (next === NEW_CATEGORY_OPTION) {
                        if (createdCategory) {
                          setAvailableCategories((current) =>
                            current.filter((item) => item !== createdCategory),
                          );
                          setCreatedCategory(null);
                          setCategoryVisibility(PUBLIC_CATEGORY_VISIBILITY);
                        }
                        setCategoryMode("create");
                        setNewCategory("");
                        return;
                      }
                      setCategoryMode("select");
                      setNewCategory("");
                      setCategory(next);
                      if (createdCategory && next !== createdCategory) {
                        setAvailableCategories((current) =>
                          current.filter((item) => item !== createdCategory),
                        );
                        setCreatedCategory(null);
                        setCategoryVisibility(PUBLIC_CATEGORY_VISIBILITY);
                      }
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

              {isNewCategory && (
                <>
                  <div className="editor-divider border-t" />

                  <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
                    <div className="space-y-2">
                      <div className="section-kicker">Category 可见范围</div>
                      <p className="text-sm leading-6 text-[var(--text-mute)]">
                        新 Category 的可见范围会成为下面 Matter 可见范围的上限。
                      </p>
                    </div>
                    <VisibilityScopePicker
                      value={categoryScopeToVisibility(categoryVisibility)}
                      onChange={(next) => {
                        setCategoryVisibility(visibilityToCategoryScope(next));
                        setVisibility(PUBLIC_VISIBILITY);
                      }}
                      disabled={submitting}
                      allowUsers={false}
                      publicLabel="公开"
                      restrictedLabel="指定角色"
                      dialogTitle="设置 Category 可见范围"
                    />
                  </div>
                </>
              )}

              <div className="editor-divider border-t" />

              <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
                <div className="space-y-2">
                  <div className="section-kicker">讨论可见范围</div>
                  <p className="text-sm leading-6 text-[var(--text-mute)]">
                    选择谁能看到这个讨论。
                  </p>
                </div>
                <VisibilityScopePicker
                  category={categoryMode === "select" ? category : undefined}
                  value={visibility}
                  onChange={setVisibility}
                  disabled={submitting}
                  allowedRoles={categoryAllowedRoles}
                  requiredUserId={me.open_id}
                />
              </div>

              <div className="editor-divider border-t" />

              {/* Title */}
              <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
                <div className="space-y-2">
                  <div className="section-kicker">标题</div>
                  <p className="text-sm leading-6 text-[var(--text-mute)]">写一句完整的主题句。</p>
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="title" className="sr-only">
                    标题
                  </Label>
                  <Input
                    id="title"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    required
                    maxLength={200}
                    className="h-11 rounded-[var(--r-md)] bg-[var(--surface-alt)]"
                  />
                </div>
              </div>

              <div className="editor-divider border-t" />

              {/* Matter owner */}
              <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
                <div className="space-y-2">
                  <div className="section-kicker">责任人</div>
                  <p className="text-sm leading-6 text-[var(--text-mute)]">
                    推进这件事的人，可选。默认你自己。
                  </p>
                </div>
                <div className="grid gap-2">
                  <Label>责任人</Label>
                  <OwnerPicker
                    value={matterOwner.pivotUserId}
                    onChange={(pivotUserId, name) => {
                      setMatterOwner({ pivotUserId, name });
                    }}
                    sessionPivotUserId={me.id}
                    sessionName={me.name}
                    displayName={matterOwner.name}
                  />
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
                    <Textarea
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
                        onChange={(pivotUserId, name) => {
                          setOwner(pivotUserId);
                          setOwnerDisplayName(name);
                        }}
                        sessionPivotUserId={me.id}
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
                    resolvedNames={resolvedNames}
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
  );
}
