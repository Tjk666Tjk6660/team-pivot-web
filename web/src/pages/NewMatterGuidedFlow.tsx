import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import {
  ArrowLeft,
  Bot,
  Maximize2,
  Minimize2,
  Send,
  Sparkles,
  User as UserIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  createMatter,
  deleteDraft,
  fetchMatters,
  searchContacts,
  streamAIChat,
  type ChatMessage,
  type CategoryVisibilityScope,
  type DocType,
  type Me,
  type MentionBlock,
  type VisibilityScope,
} from "@/api";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { MentionField, emptyMention } from "@/components/MentionField";
import { OwnerPicker } from "@/components/matter/OwnerPicker";
import { VisibilityScopePicker } from "@/components/visibility/VisibilityScopePicker";
import { useDraftAutosave } from "@/hooks/useDraftAutosave";
import { publishDraftsRefresh } from "@/events/listRefresh";

/** Snapshot the classic form hands to the guided flow when the user picks
 *  "进行 AI 讨论" in the publish quality gate. The guided flow skips the
 *  manual Q&A steps and goes straight to AI drafting. */
export type ClassicBridgeSnapshot = {
  body: string;
  title: string;
  category: string;
  docType: DocType;
  matterOwner: { pivotUserId: string; name: string };
  mentions: MentionBlock;
  categoryVisibility: CategoryVisibilityScope;
  matterVisibility: VisibilityScope;
  createdCategory?: string | null;
};

const PREVIEW_MIN_WIDTH = 320;
const PREVIEW_MAX_WIDTH = 880;
const PREVIEW_DEFAULT_WIDTH = 460;

const NEW_CATEGORY_OPTION = "__new_category__";
const CATEGORY_PATTERN = /^[^/\\:*?"<>|\t\n\r]{1,20}$/;
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

type Phase =
  | "topic"
  | "type"
  | "category"
  | "title"
  | "owner"
  | "mentions"
  | "drafting"
  | "review";

const PHASE_ORDER: Phase[] = [
  "topic",
  "type",
  "category",
  "title",
  "owner",
  "mentions",
  "drafting",
  "review",
];

const PHASE_LABEL: Record<Phase, string> = {
  topic: "话题",
  type: "类型",
  category: "种类",
  title: "标题",
  owner: "责任人",
  mentions: "圈人",
  drafting: "AI 起草",
  review: "确认发布",
};

type StepData = {
  topic: string;
  docType: DocType;
  category: string;
  title: string;
  matterOwner: { pivotUserId: string; name: string };
  mentions: MentionBlock;
  categoryVisibility: CategoryVisibilityScope;
  matterVisibility: VisibilityScope;
  body: string;
  summary: string;
};

const initialData = (me: Me): StepData => ({
  topic: "",
  docType: "think",
  category: "",
  title: "",
  matterOwner: { pivotUserId: me.id, name: me.name },
  mentions: emptyMention(),
  categoryVisibility: PUBLIC_CATEGORY_VISIBILITY,
  matterVisibility: PUBLIC_VISIBILITY,
  body: "",
  summary: "",
});

type Bubble =
  | { kind: "ai"; text: string; key: string }
  | { kind: "user"; text: string; key: string };

const aiOpener: Bubble = {
  kind: "ai",
  key: "opener",
  text: "你好，我会用 7 步帮你把想发起的讨论整理成一篇可发布的 matter。先告诉我，你想讨论什么？一句话即可。",
};

export function NewMatterGuidedFlow({
  me,
  onSwitchToClassic,
  initialBridge,
}: {
  me: Me;
  onSwitchToClassic: (snapshot?: ClassicBridgeSnapshot) => void;
  /** When set, the user is arriving from the classic form's quality gate.
   *  All fields are already filled — skip the manual Q&A and go directly to
   *  AI drafting using the user's typed body as base. */
  initialBridge?: ClassicBridgeSnapshot;
}) {
  const navigate = useNavigate();
  const hasBridge = !!initialBridge && !!initialBridge.title.trim();
  const [phase, setPhase] = useState<Phase>(hasBridge ? "drafting" : "topic");
  const [data, setData] = useState<StepData>(() =>
    hasBridge
      ? {
          topic: initialBridge!.body.trim(),
          docType: initialBridge!.docType,
          category: initialBridge!.category,
          title: initialBridge!.title,
          matterOwner: initialBridge!.matterOwner,
          mentions: initialBridge!.mentions,
          categoryVisibility: initialBridge!.categoryVisibility,
          matterVisibility: initialBridge!.matterVisibility,
          body: "",
          summary: "",
        }
      : initialData(me),
  );
  const [bubbles, setBubbles] = useState<Bubble[]>(() =>
    hasBridge ? buildBridgeBubbles(initialBridge!) : [aiOpener],
  );
  const [availableCategories, setAvailableCategories] = useState<string[]>(() =>
    hasBridge && initialBridge!.category
      ? [initialBridge!.category]
      : [],
  );
  const [createdCategory, setCreatedCategory] = useState<string | null>(
    () => initialBridge?.createdCategory ?? null,
  );
  const [draftId, setDraftId] = useState<string | null>(null);
  const [resolvedNames, setResolvedNames] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  // Used during phase=drafting (initial or revision) for streaming preview.
  const [streamingBody, setStreamingBody] = useState("");
  // Full multi-turn AI conversation history for revisions on top of the first
  // draft. Each revision appends to this list so the AI keeps context.
  const [aiHistory, setAIHistory] = useState<ChatMessage[]>([]);
  // True while a revision call is streaming — disables the chat composer and
  // tells the preview to show the streaming body instead of the saved one.
  const [revising, setRevising] = useState(false);
  // Right preview panel: explicit pixel width on md+ (drag to resize) and a
  // fullscreen toggle that overlays it on top of the page.
  const [previewWidth, setPreviewWidth] = useState(PREVIEW_DEFAULT_WIDTH);
  const [previewFullscreen, setPreviewFullscreen] = useState(false);
  const draftedOnceRef = useRef(false);
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  // Scroll chat to bottom on new bubbles.
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [bubbles, phase]);

  // Initial categories load.
  useEffect(() => {
    fetchMatters()
      .then((items) => {
        const cats = Array.from(
          new Set(
            items
              .map((m) => m.category)
              .filter((c): c is string => typeof c === "string" && !!c),
          ),
        );
        setAvailableCategories(cats);
      })
      .catch(() => {});
  }, []);

  // Resolve mention open_ids → display names lazily so chips don't show "@ou_xxx".
  useEffect(() => {
    const missing = data.mentions.open_ids.filter((oid) => !(oid in resolvedNames));
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
          /* swallow per-id failure */
        }
      }
      if (cancelled || Object.keys(fresh).length === 0) return;
      setResolvedNames((prev) => ({ ...prev, ...fresh }));
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.mentions.open_ids]);

  const phaseIndex = PHASE_ORDER.indexOf(phase);
  const phaseDisplayIndex = phase === "review" ? 7 : phaseIndex + 1;
  const isNewCategory = !!createdCategory && data.category.trim() === createdCategory;
  const categoryAllowedRoles =
    isNewCategory && data.categoryVisibility.mode === "restricted"
      ? data.categoryVisibility.authorized_roles
      : undefined;
  const draftBody = data.body || streamingBody;
  const hasDraftContent =
    data.topic.trim().length > 0 ||
    data.title.trim().length > 0 ||
    data.category.trim().length > 0 ||
    draftBody.trim().length > 0 ||
    data.summary.trim().length > 0 ||
    data.mentions.open_ids.length > 0;
  const draftPayload = () => ({
    title: data.title.trim() || null,
    category: data.category.trim() || null,
    body_md: draftBody,
    matter_payload: {
      doc_type: data.docType,
      summary: data.summary.trim(),
      matter_owner: data.matterOwner.pivotUserId,
      matter_owner_display: data.matterOwner.name,
      owner: me.open_id,
      owner_display: me.name,
      body_source: draftBody.trim() ? "ai" : "manual",
      ...(draftBody.trim() ? { body_source_snapshot: draftBody } : {}),
      ...(data.topic.trim() ? { topic: data.topic.trim() } : {}),
      ...(data.mentions.open_ids.length > 0 ? { mentions: data.mentions } : {}),
      category_visibility: data.categoryVisibility,
      matter_visibility: data.matterVisibility,
      created_category: createdCategory,
    },
  });
  const { saveNow } = useDraftAutosave({
    draftId,
    setDraftId,
    type: "proposal",
    payload: draftPayload,
    enabled: hasDraftContent && !submitting,
    deps: [
      hasDraftContent,
      submitting,
      data.topic,
      data.docType,
      data.category,
      data.title,
      data.matterOwner.pivotUserId,
      data.matterOwner.name,
      data.mentions.open_ids.length,
      data.mentions.comments,
      data.body,
      data.summary,
      data.categoryVisibility.mode,
      data.categoryVisibility.authorized_roles.join("|"),
      data.matterVisibility.mode,
      data.matterVisibility.roles.join("|"),
      data.matterVisibility.user_ids.join("|"),
      createdCategory,
      streamingBody,
    ],
  });

  const handleBackToList = async () => {
    if (hasDraftContent) {
      const savedId = await saveNow();
      if (!savedId) {
        toast.error("草稿保存失败，请稍后重试");
        return;
      }
      publishDraftsRefresh();
    }
    navigate("/");
  };

  const buildClassicSnapshot = (): ClassicBridgeSnapshot => ({
    body: draftBody,
    title: data.title,
    category: data.category,
    docType: data.docType,
    matterOwner: data.matterOwner,
    mentions: data.mentions,
    categoryVisibility: data.categoryVisibility,
    matterVisibility: data.matterVisibility,
    createdCategory,
  });

  const advanceToNextAI = (next: Phase) => {
    setPhase(next);
    const text = aiQuestionFor(next, data, availableCategories);
    if (text) {
      setBubbles((prev) => [...prev, { kind: "ai", text, key: `ai-${next}-${Date.now()}` }]);
    }
  };

  const recordUserAndAdvance = (userText: string, next: Phase) => {
    setBubbles((prev) => [
      ...prev,
      { kind: "user", text: userText, key: `u-${next}-${Date.now()}` },
    ]);
    // Defer AI bubble one tick so the user's bubble flushes first.
    queueMicrotask(() => advanceToNextAI(next));
  };

  // Step submit handlers ────────────────────────────────────────────
  const submitTopic = (val: string) => {
    const trimmed = val.trim();
    if (!trimmed) return toast.error("请描述一下你想讨论什么");
    setData((d) => ({ ...d, topic: trimmed }));
    recordUserAndAdvance(trimmed, "type");
  };

  const submitType = (val: DocType) => {
    setData((d) => ({ ...d, docType: val }));
    recordUserAndAdvance(
      val === "think" ? "记录判断 / 方案 (think)" : "推进一项行动 (act)",
      "category",
    );
  };

  const submitCategory = (val: string) => {
    const trimmed = val.trim();
    if (!trimmed) return toast.error("请选择或输入一个种类");
    if (!CATEGORY_PATTERN.test(trimmed)) {
      return toast.error('种类需 1-20 字，且不能包含 / \\\\ : * ? " < > | 或换行');
    }
    const wasNewCategory = !availableCategories.includes(trimmed);
    if (wasNewCategory) {
      setCreatedCategory(trimmed);
    } else if (createdCategory && trimmed !== createdCategory) {
      setCreatedCategory(null);
      setAvailableCategories((cats) =>
        cats.filter((item) => item !== createdCategory),
      );
    }
    setData((d) => ({
      ...d,
      category: trimmed,
      categoryVisibility:
        wasNewCategory ? PUBLIC_CATEGORY_VISIBILITY : d.categoryVisibility,
      matterVisibility: PUBLIC_VISIBILITY,
    }));
    setAvailableCategories((cats) =>
      cats.includes(trimmed) ? cats : [...cats, trimmed],
    );
    recordUserAndAdvance(`种类：${trimmed}`, "title");
  };

  const submitTitle = (val: string) => {
    const trimmed = val.trim();
    if (!trimmed) return toast.error("请填一个标题");
    if (trimmed.length > 200) return toast.error("标题不能超过 200 字");
    setData((d) => ({ ...d, title: trimmed }));
    recordUserAndAdvance(`标题：${trimmed}`, "owner");
  };

  const submitOwner = (owner: { pivotUserId: string; name: string }) => {
    setData((d) => ({ ...d, matterOwner: owner }));
    recordUserAndAdvance(`责任人：${owner.name || owner.pivotUserId || "我"}`, "mentions");
  };

  const skipOwner = () => {
    const self = { pivotUserId: me.id, name: me.name };
    setData((d) => ({ ...d, matterOwner: self }));
    recordUserAndAdvance("责任人：默认我自己", "mentions");
  };

  const submitMentions = (mb: MentionBlock) => {
    if (mb.open_ids.length > 0 && !mb.comments.trim()) {
      return toast.error("圈了人就要留一句话");
    }
    setData((d) => ({ ...d, mentions: mb }));
    const userMsg =
      mb.open_ids.length > 0
        ? `圈了 ${mb.open_ids.length} 人 · ${mb.comments.trim()}`
        : "暂不圈人";
    recordUserAndAdvance(userMsg, "drafting");
  };

  const skipMentions = () => {
    setData((d) => ({ ...d, mentions: emptyMention() }));
    recordUserAndAdvance("暂不圈人", "drafting");
  };

  // Drafting phase ──────────────────────────────────────────────────
  // Trigger the single AI streaming call exactly once when entering drafting.
  useEffect(() => {
    if (phase !== "drafting") return;
    if (draftedOnceRef.current) return;
    draftedOnceRef.current = true;
    void runInitialDrafting();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  const runInitialDrafting = async () => {
    setStreamingBody("");
    const prompt = buildDraftPrompt(data, initialBridge?.body);
    const userMsg: ChatMessage = { role: "user", content: prompt };
    let acc = "";
    try {
      for await (const ev of streamAIChat(
        NEW_MATTER_PSEUDO_ID,
        [userMsg],
        null,
        undefined,
        "new-matter",
      )) {
        if (ev.kind === "delta") {
          acc += ev.delta;
          // Show whatever's inside <draft> as it streams (best-effort regex on
          // partial text). The full extraction happens at end.
          const partial = extractPartialDraft(acc);
          if (partial !== null) setStreamingBody(partial);
        }
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`AI 起草失败：${msg}`);
      // Roll back to mentions so user can retry without losing prior state.
      // For bridge users (no mentions step in their history), fall back to
      // mentions step too — they can retry from there or jump to classic.
      draftedOnceRef.current = false;
      setPhase("mentions");
      setBubbles((prev) => [
        ...prev,
        {
          kind: "ai",
          key: `ai-err-${Date.now()}`,
          text: `AI 起草失败（${msg}），可以再试一次或直接跳到「自己写」模式。`,
        },
      ]);
      return;
    }

    const ext = extractDraftFinal(acc);
    if (!ext || !ext.body) {
      toast.error("AI 没有给出可用草稿，请重试或切换到自己写模式");
      draftedOnceRef.current = false;
      setPhase("mentions");
      return;
    }
    setData((d) => ({
      ...d,
      body: ext.body,
      summary: ext.summary || d.summary,
    }));
    // Save the multi-turn history so revisions can build on this draft.
    setAIHistory([userMsg, { role: "assistant", content: acc }]);
    setBubbles((prev) => [
      ...prev,
      {
        kind: "ai",
        key: `ai-drafted-${Date.now()}`,
        text: "草稿已经在右侧。如果想让 AI 再调整，下面告诉我哪里要改；也可以直接在右侧微调或点「立即发布」。",
      },
    ]);
    setPhase("review");
  };

  // Revision: user types a follow-up in review phase, AI regenerates the
  // <draft>/<summary> while keeping the prior turn(s) as context.
  const runRevision = async (userRequest: string) => {
    const trimmed = userRequest.trim();
    if (!trimmed) return;
    setBubbles((prev) => [
      ...prev,
      { kind: "user", text: trimmed, key: `u-rev-${Date.now()}` },
    ]);
    setRevising(true);
    setStreamingBody("");

    const userMsg: ChatMessage = {
      role: "user",
      content: [
        `请根据下面的反馈重新起草整篇文档，覆盖之前的版本，仍保持 <draft type="${data.docType}">…</draft><summary>…</summary> 的格式。除非反馈里明确要求改动，标题（${data.title}）、种类（${data.category}）和讨论方向保持不变。`,
        "",
        `反馈：${trimmed}`,
      ].join("\n"),
    };
    const messages: ChatMessage[] = [...aiHistory, userMsg];
    let acc = "";
    try {
      for await (const ev of streamAIChat(
        NEW_MATTER_PSEUDO_ID,
        messages,
        null,
        undefined,
        "new-matter",
      )) {
        if (ev.kind === "delta") {
          acc += ev.delta;
          const partial = extractPartialDraft(acc);
          if (partial !== null) setStreamingBody(partial);
        }
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`AI 修订失败：${msg}`);
      setBubbles((prev) => [
        ...prev,
        {
          kind: "ai",
          key: `ai-rev-err-${Date.now()}`,
          text: `修订失败（${msg}），上一版草稿没动，可以再试一次。`,
        },
      ]);
      setRevising(false);
      return;
    }

    const ext = extractDraftFinal(acc);
    if (!ext || !ext.body) {
      toast.error("AI 没有给出新草稿，请换个说法再试");
      setBubbles((prev) => [
        ...prev,
        {
          kind: "ai",
          key: `ai-rev-empty-${Date.now()}`,
          text: "我没能给出可用的新版本，可以换个说法或更具体一点再告诉我。",
        },
      ]);
      setRevising(false);
      return;
    }
    setData((d) => ({
      ...d,
      body: ext.body,
      summary: ext.summary || d.summary,
    }));
    setAIHistory([...messages, { role: "assistant", content: acc }]);
    setBubbles((prev) => [
      ...prev,
      {
        kind: "ai",
        key: `ai-rev-${Date.now()}`,
        text: "好，已经按你的反馈重新起草了，看看右侧有没有要再改的。",
      },
    ]);
    setRevising(false);
  };

  // Resize the preview pane by dragging the divider. Body listeners are added
  // on mousedown and removed on mouseup; cursor + select-none are toggled on
  // <body> so the drag feels stable even when the pointer leaves the handle.
  const onResizeStart = (e: React.MouseEvent) => {
    if (previewFullscreen) return;
    e.preventDefault();
    const startX = e.clientX;
    const startWidth = previewWidth;
    const onMove = (ev: MouseEvent) => {
      // Aside is on the right, so dragging left increases its width.
      const next = clamp(
        startWidth - (ev.clientX - startX),
        PREVIEW_MIN_WIDTH,
        PREVIEW_MAX_WIDTH,
      );
      setPreviewWidth(next);
    };
    const onUp = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  const publish = async () => {
    if (!data.title.trim()) return toast.error("标题必填");
    if (!data.body.trim()) return toast.error("正文必填");
    if (!data.summary.trim()) return toast.error("摘要必填");
    if (isNewCategory && data.categoryVisibility.mode === "restricted") {
      if (data.categoryVisibility.authorized_roles.length === 0) {
        return toast.error("Category 指定角色可见时，至少选择一个角色");
      }
      if (
        data.matterVisibility.mode === "restricted" &&
        data.matterVisibility.roles.some(
          (role) => !data.categoryVisibility.authorized_roles.includes(role),
        )
      ) {
        return toast.error("Matter 可见范围不能超过 Category");
      }
    }
    setSubmitting(true);
    try {
      const r = await createMatter({
        category: data.category.trim(),
        title: data.title.trim(),
        owner_pivot_user_id: data.matterOwner.pivotUserId || me.id,
        visibility: data.matterVisibility,
        new_category_visibility: isNewCategory
          ? data.categoryVisibility
          : undefined,
        initial_file: {
          type: data.docType,
          summary: data.summary.trim(),
          body: data.body.trim(),
          owner: me.open_id,
          // Guided flow → AI co-wrote the draft. body_source skips the gate.
          body_source: "ai",
          ...(data.mentions.open_ids.length > 0
            ? {
                mentions: [
                  {
                    body: data.mentions.comments.trim(),
                    targets: data.mentions.open_ids,
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
          // Draft cleanup failure should not block the successfully published matter.
        }
      }
      navigate(`/m/${encodeURIComponent(r.matter_id)}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
      setSubmitting(false);
    }
  };

  return (
    // Narrow: simple block flow inside Dashboard's <main> scroll container.
    // md+: rigid two-column with each column owning its own scroll. The
    // narrow path is the simplest possible — header → chat → input → preview
    // stacked vertically — so the user can see the AI greeting immediately
    // without nested scroll containers fighting for space.
    <div className="flex flex-col md:h-full md:min-h-0 md:flex-row md:overflow-hidden">
      {/* Left: chat + step input */}
      <div className="flex flex-col md:min-h-0 md:flex-1 md:overflow-hidden">
        <div className="border-b border-[var(--line)] bg-[var(--surface)] px-4 py-3 sm:px-6">
          <div className="flex items-center justify-between gap-3">
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
            <div className="flex items-center gap-3">
              <span className="text-xs text-[var(--text-mute)]">
                第 {phaseDisplayIndex} / 7 步 · {PHASE_LABEL[phase]}
              </span>
              <button
                type="button"
                onClick={() => onSwitchToClassic(buildClassicSnapshot())}
                className="text-xs text-[var(--text-mute)] underline-offset-2 hover:text-[var(--accent)] hover:underline"
                title="切换到表单模式"
              >
                跳过引导，直接写
              </button>
            </div>
          </div>
        </div>

        <div className="px-3 py-4 sm:px-6 sm:py-6 md:flex-1 md:overflow-y-auto">
          <div className="mx-auto w-full max-w-2xl space-y-4">
            {bubbles.map((b) => (
              <ChatBubble key={b.key} bubble={b} userName={me.name} />
            ))}
            {phase === "drafting" && (
              <ChatBubble
                bubble={{
                  kind: "ai",
                  key: "ai-drafting-status",
                  text: "AI 正在为你起草正文…右侧会实时显示。",
                }}
                userName={me.name}
              />
            )}
            <div ref={chatEndRef} />
          </div>
        </div>

        {/* Step input widget docked at the bottom */}
        <div className="border-t border-[var(--line)] bg-[var(--surface)] px-3 py-3 sm:px-6 sm:py-4">
          <div className="mx-auto w-full max-w-2xl">
            {phase === "topic" && (
              <TopicStep onSubmit={submitTopic} defaultValue="" />
            )}
            {phase === "type" && <TypeStep onSubmit={submitType} />}
            {phase === "category" && (
              <CategoryStep
                available={availableCategories}
                onSubmit={submitCategory}
              />
            )}
            {phase === "title" && (
              <TitleStep
                topic={data.topic}
                docType={data.docType}
                onSubmit={submitTitle}
              />
            )}
            {phase === "owner" && (
              <OwnerStep
                value={data.matterOwner}
                me={me}
                onSubmit={submitOwner}
                onSkip={skipOwner}
              />
            )}
            {phase === "mentions" && (
              <MentionsStep
                value={data.mentions}
                resolvedNames={resolvedNames}
                onSubmit={submitMentions}
                onSkip={skipMentions}
              />
            )}
            {phase === "drafting" && (
              <div className="text-center text-sm text-[var(--text-mute)]">
                <span className="inline-flex items-center gap-2">
                  <Sparkles className="h-4 w-4 animate-pulse text-[var(--accent)]" />
                  {revising ? "AI 修订中…" : "AI 起草中…"}
                </span>
              </div>
            )}
            {phase === "review" && (
              <div className="space-y-3">
                <ReviseStep onSend={runRevision} busy={revising} />
                <div className="space-y-3 rounded-[var(--r-md)] border border-[var(--line)] bg-[var(--surface-alt)] p-3">
                  {isNewCategory && (
                    <div className="space-y-2">
                      <Label className="text-xs font-semibold text-[var(--text-soft)]">
                        Category 可见范围
                      </Label>
                      <VisibilityScopePicker
                        value={categoryScopeToVisibility(data.categoryVisibility)}
                        onChange={(next) => {
                          setData((d) => ({
                            ...d,
                            categoryVisibility: visibilityToCategoryScope(next),
                            matterVisibility: PUBLIC_VISIBILITY,
                          }));
                        }}
                        disabled={submitting || revising}
                        allowUsers={false}
                        publicLabel="公开"
                        restrictedLabel="指定角色"
                        dialogTitle="设置 Category 可见范围"
                      />
                    </div>
                  )}
                  <div className="space-y-2">
                    <Label className="text-xs font-semibold text-[var(--text-soft)]">
                      讨论可见范围
                    </Label>
                    <VisibilityScopePicker
                      category={isNewCategory ? undefined : data.category}
                      value={data.matterVisibility}
                      onChange={(next) => setData((d) => ({ ...d, matterVisibility: next }))}
                      disabled={submitting || revising}
                      allowedRoles={categoryAllowedRoles}
                      requiredUserId={me.open_id}
                    />
                  </div>
                </div>
                <div className="flex flex-wrap items-center justify-end gap-2">
                  <span className="mr-auto text-xs text-[var(--text-mute)]">
                    跟 AI 继续讨论会覆盖右侧草稿；也可直接微调后发布。
                  </span>
                  {!hasBridge && (
                    <Button
                      type="button"
                      variant="ghost"
                      className="rounded-[var(--r-md)]"
                      disabled={revising}
                      onClick={() => {
                        draftedOnceRef.current = false;
                        setPhase("mentions");
                      }}
                    >
                      返回上一步
                    </Button>
                  )}
                  <Button
                    type="button"
                    className="rounded-[var(--r-md)] px-5"
                    disabled={
                      submitting ||
                      revising ||
                      !data.body.trim() ||
                      !data.title.trim()
                    }
                    onClick={() => void publish()}
                  >
                    {submitting ? "发布中…" : "立即发布"}
                  </Button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Drag handle between left chat and right preview (md+ only). The
          handle straddles a 1px line; the wider hit area makes it easier
          to grab with a mouse. */}
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="拖动调整左右宽度"
        onMouseDown={onResizeStart}
        className={cn(
          "hidden shrink-0 select-none md:block",
          previewFullscreen ? "md:hidden" : "",
          "md:w-1.5 md:cursor-col-resize md:bg-[var(--line)] md:hover:bg-[var(--accent-bg)]",
        )}
      />

      {/* Right: live preview panel.
          On narrow it just stacks naturally below the chat (no fixed height,
          no nested scroll). On md+ it's a resizable right column whose
          width is driven by the inline CSS variable below. When fullscreen
          is on, the panel overlays the whole viewport. */}
      <aside
        style={
          {
            "--preview-w": `${previewWidth}px`,
          } as React.CSSProperties
        }
        className={cn(
          "flex flex-col border-t border-[var(--line)] bg-[var(--surface-alt)]",
          previewFullscreen
            ? "fixed inset-0 z-50 border-t-0"
            : "md:h-full md:w-[var(--preview-w)] md:shrink-0 md:border-l md:border-t-0",
        )}
      >
        <div className="flex items-start justify-between gap-3 border-b border-[var(--line)] px-4 py-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-medium text-[var(--text)]">
              <Bot className="h-4 w-4 text-[var(--accent)]" />
              讨论草稿预览
            </div>
            <div className="mt-1 text-xs text-[var(--text-mute)]">
              随对话实时构建，发布前可在右侧直接编辑。
            </div>
          </div>
          <button
            type="button"
            onClick={() => setPreviewFullscreen((v) => !v)}
            className="rounded-[var(--r-sm)] p-1.5 text-[var(--text-mute)] hover:bg-[var(--surface)] hover:text-[var(--text)]"
            title={previewFullscreen ? "退出全屏" : "全屏查看"}
            aria-label={previewFullscreen ? "退出全屏" : "全屏查看"}
          >
            {previewFullscreen ? (
              <Minimize2 className="h-4 w-4" />
            ) : (
              <Maximize2 className="h-4 w-4" />
            )}
          </button>
        </div>
        <div
          className={cn(
            "p-4",
            previewFullscreen
              ? "flex-1 overflow-y-auto"
              : "md:flex-1 md:overflow-y-auto",
          )}
        >
          <PreviewPanel
            data={data}
            phase={phase}
            me={me}
            availableCategories={availableCategories}
            // Show streaming body during initial drafting AND active revision.
            streamingBody={revising || phase === "drafting" ? streamingBody : ""}
            isStreaming={revising || phase === "drafting"}
            resolvedNames={resolvedNames}
            onUpdateData={(patch) => setData((d) => ({ ...d, ...patch }))}
            onSelectCategory={(category) => setData((d) => ({ ...d, category }))}
            onEditBody={(b) => setData((d) => ({ ...d, body: b }))}
            onEditSummary={(s) => setData((d) => ({ ...d, summary: s }))}
            canEdit={phase === "review" && !revising}
          />
        </div>
      </aside>
    </div>
  );
}

// ── Helpers ────────────────────────────────────────────────────────

function aiQuestionFor(
  next: Phase,
  data: StepData,
  cats: string[],
): string | null {
  switch (next) {
    case "type":
      return "好的。这篇你倾向于「think（记录判断 / 方案）」还是「act（推进一项待办行动）」？";
    case "category":
      return cats.length > 0
        ? `归到哪个种类？已有：${cats.slice(0, 6).join(" / ")}${cats.length > 6 ? " …" : ""}。也可以直接新建一个。`
        : "归到哪个种类？还没有种类，请直接新建一个名字（≤ 20 字）。";
    case "title":
      return `标题想叫什么？建议写一句完整的主题句，不要太短。${data.topic ? `（话题：${data.topic.slice(0, 40)}${data.topic.length > 40 ? "…" : ""}）` : ""}`;
    case "owner":
      return "这件事由谁负责推进？默认是你，也可以指定别人。";
    case "mentions":
      return "想圈谁来 review？可选——可以加几个人 + 留一句话，也可以跳过。";
    case "drafting":
      return "好。我已经收齐信息，开始为你起草正文 + 摘要…";
    case "review":
      return null; // handled inline after streaming completes
    case "topic":
      return null;
  }
}

function buildDraftPrompt(d: StepData, existingBody?: string): string {
  const fromClassic = !!existingBody && !!existingBody.trim();
  const lines = [
    fromClassic
      ? "[[GENERATE_REPLY_DRAFT]] 用户先在「自己写」里草拟了一份内容，希望 AI 在保留原意的前提下重新整理 / 润色，输出更结构化、更适合发布的版本。"
      : "[[GENERATE_REPLY_DRAFT]] 请基于下面用户在引导式对话里给出的信息，为这个全新的 matter 生成首篇文档：",
    "",
    `- 类型：${d.docType}（think = 判断/方案，act = 推进一项行动）`,
    `- 种类：${d.category}`,
    `- 标题（用户已选）：${d.title}`,
    `- Matter 责任人：${d.matterOwner.name || d.matterOwner.pivotUserId || "默认当前用户"}`,
    `- 用户想讨论的话题：${d.topic || (existingBody?.slice(0, 80) ?? "")}`,
  ];
  if (d.mentions.open_ids.length > 0) {
    lines.push(
      `- 圈了 ${d.mentions.open_ids.length} 个人来 review，对他们说的话：${d.mentions.comments.trim()}`,
    );
  }
  if (fromClassic) {
    lines.push(
      "",
      "用户原始草稿如下（请保留事实、观点、关键数据，不要凭空增减；只做表达和结构上的优化）：",
      "```",
      existingBody!.trim(),
      "```",
    );
  }
  lines.push(
    "",
    "请输出三段：",
    `1) <draft type="${d.docType}">完整正文（Markdown）</draft>，正文要把话题展开成有结构的段落，反映用户真实想表达的内容，不要凭空添加事实。`,
    "2) <summary>不超过 80 字的中文摘要，概括这篇文档推进 / 判断 / 结论了什么</summary>",
    "3) <title>一句不超过 30 字的标题建议（仅供参考，用户已经填了标题）</title>",
  );
  return lines.join("\n");
}

function clamp(v: number, min: number, max: number): number {
  return Math.min(Math.max(v, min), max);
}

// When the user arrives via the classic-form bridge, seed the chat history
// with a concise summary so the conversation looks coherent. We show a user
// bubble for what they wrote and an AI bubble announcing AI drafting.
function buildBridgeBubbles(b: ClassicBridgeSnapshot): Bubble[] {
  const bodyPreview = b.body.trim();
  const preview =
    bodyPreview.length > 240
      ? `${bodyPreview.slice(0, 240)}…`
      : bodyPreview;
  return [
    {
      kind: "user",
      key: "bridge-snapshot",
      text: [
        `标题：${b.title}`,
        `种类：${b.category}`,
        `类型：${b.docType}`,
        `责任人：${b.matterOwner.name || b.matterOwner.pivotUserId || "默认我自己"}`,
        b.mentions.open_ids.length > 0
          ? `圈了 ${b.mentions.open_ids.length} 人 · ${b.mentions.comments.trim()}`
          : "暂不圈人",
        "",
        "我已经写了一份草稿：",
        preview,
      ].join("\n"),
    },
    {
      kind: "ai",
      key: "bridge-ack",
      text: "收到。我来基于你写的内容重新整理一版正文 + 摘要，看看右侧。",
    },
  ];
}

const DRAFT_RE = /<draft(?:\s+type="[^"]*")?\s*>([\s\S]*?)<\/draft>/i;
const SUMMARY_RE = /<summary>([\s\S]*?)<\/summary>/i;

function extractDraftFinal(text: string): { body: string; summary: string } | null {
  const m = text.match(DRAFT_RE);
  if (!m) return null;
  const summaryMatch = text.match(SUMMARY_RE);
  return {
    body: m[1].trim(),
    summary: summaryMatch ? summaryMatch[1].trim() : "",
  };
}

// Best-effort: while streaming, the </draft> tag may not yet be present; pull
// whatever sits between <draft …> and the current end of the buffer.
function extractPartialDraft(text: string): string | null {
  const open = text.match(/<draft(?:\s+type="[^"]*")?\s*>/i);
  if (!open) return null;
  const tail = text.slice(open.index! + open[0].length);
  const closeIdx = tail.search(/<\/draft>/i);
  return closeIdx >= 0 ? tail.slice(0, closeIdx).trim() : tail.trim();
}

// ── Sub-components ─────────────────────────────────────────────────

function ChatBubble({ bubble, userName }: { bubble: Bubble; userName: string }) {
  if (bubble.kind === "ai") {
    return (
      <div className="flex items-start gap-3">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[var(--r-md)] bg-gradient-to-br from-[var(--accent)] to-purple-500 text-xs font-bold text-white">
          AI
        </div>
        <div className="rounded-[var(--r-md)] border border-[var(--line)] bg-[var(--surface)] px-4 py-2.5 text-sm leading-6 text-[var(--text)] shadow-sm">
          {bubble.text}
        </div>
      </div>
    );
  }
  return (
    <div className="flex flex-row-reverse items-start gap-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[var(--r-md)] bg-[var(--surface-alt)] text-xs font-bold text-[var(--text)]">
        <UserIcon className="h-4 w-4" />
      </div>
      <div className="max-w-[88%] rounded-[var(--r-md)] bg-[var(--accent)] px-4 py-2.5 text-sm leading-6 text-white shadow-sm">
        {bubble.text}
      </div>
      <span className="sr-only">{userName}</span>
    </div>
  );
}

function TopicStep({
  onSubmit,
  defaultValue,
}: {
  onSubmit: (v: string) => void;
  defaultValue?: string;
}) {
  const [val, setVal] = useState(defaultValue ?? "");
  // Prefilled bridges (from classic form) tend to be longer than the
  // one-line ideal; use a taller textarea so the user can see what was
  // brought over.
  const isLong = (defaultValue?.length ?? 0) > 80;
  return (
    <div className="space-y-2">
      <Textarea
        autoFocus
        value={val}
        onChange={(e) => setVal(e.target.value)}
        placeholder="例如：客服流程优化方案 / 我们的定价是不是该调整 / 新功能 X 怎么落地"
        rows={isLong ? 6 : 2}
        maxLength={2000}
        className="min-h-[4rem] rounded-[var(--r-md)] border-[var(--line-strong)] bg-[var(--surface-alt)] text-sm"
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            onSubmit(val);
          }
        }}
      />
      <div className="flex justify-end">
        <Button
          type="button"
          className="rounded-[var(--r-md)]"
          onClick={() => onSubmit(val)}
          disabled={!val.trim()}
        >
          继续 →
        </Button>
      </div>
    </div>
  );
}

function TypeStep({ onSubmit }: { onSubmit: (v: DocType) => void }) {
  const [val, setVal] = useState<DocType>("think");
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-3 text-sm">
        <label className="flex flex-1 cursor-pointer items-start gap-2 rounded-[var(--r-md)] border border-[var(--line)] p-3 hover:border-[var(--accent)]">
          <input
            type="radio"
            checked={val === "think"}
            onChange={() => setVal("think")}
            className="mt-0.5"
          />
          <span>
            <span className="block font-semibold">think</span>
            <span className="block text-xs text-[var(--text-mute)]">
              记录判断 / 方案 / 待讨论问题
            </span>
          </span>
        </label>
        <label className="flex flex-1 cursor-pointer items-start gap-2 rounded-[var(--r-md)] border border-[var(--line)] p-3 hover:border-[var(--accent)]">
          <input
            type="radio"
            checked={val === "act"}
            onChange={() => setVal("act")}
            className="mt-0.5"
          />
          <span>
            <span className="block font-semibold">act</span>
            <span className="block text-xs text-[var(--text-mute)]">
              推进一项待执行的行动
            </span>
          </span>
        </label>
      </div>
      <div className="flex justify-end">
        <Button
          type="button"
          className="rounded-[var(--r-md)]"
          onClick={() => onSubmit(val)}
        >
          继续 →
        </Button>
      </div>
    </div>
  );
}

function CategoryStep({
  available,
  onSubmit,
}: {
  available: string[];
  onSubmit: (v: string) => void;
}) {
  const [picked, setPicked] = useState<string>(
    available.length > 0 ? available[0] : NEW_CATEGORY_OPTION,
  );
  const [fresh, setFresh] = useState("");
  const isCreating = picked === NEW_CATEGORY_OPTION;
  return (
    <div className="space-y-2">
      <select
        value={picked}
        onChange={(e) => setPicked(e.target.value)}
        className="flex h-10 w-full rounded-[var(--r-md)] border border-input bg-[var(--surface-alt)] px-3 text-sm"
      >
        {available.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
        <option value={NEW_CATEGORY_OPTION}>+ 新建种类…</option>
      </select>
      {isCreating && (
        <Input
          autoFocus
          value={fresh}
          onChange={(e) => setFresh(e.target.value)}
          placeholder="输入新种类名称（≤ 20 字）"
          maxLength={20}
        />
      )}
      <div className="flex justify-end">
        <Button
          type="button"
          className="rounded-[var(--r-md)]"
          onClick={() => onSubmit(isCreating ? fresh : picked)}
          disabled={isCreating ? !fresh.trim() : !picked || picked === NEW_CATEGORY_OPTION}
        >
          继续 →
        </Button>
      </div>
    </div>
  );
}

function TitleStep({
  topic,
  docType,
  onSubmit,
}: {
  topic: string;
  docType: DocType;
  onSubmit: (v: string) => void;
}) {
  const suggested = useMemo(() => suggestTitle(topic, docType), [topic, docType]);
  const [val, setVal] = useState(suggested);
  useEffect(() => {
    setVal(suggested);
  }, [suggested]);
  return (
    <div className="space-y-2">
      <Input
        autoFocus
        value={val}
        onChange={(e) => setVal(e.target.value)}
        placeholder="一句话主题句"
        maxLength={200}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            onSubmit(val);
          }
        }}
      />
      <div className="flex items-center justify-between">
        <span className="text-xs text-[var(--text-mute)]">
          已根据话题自动填了一个建议，可以改。
        </span>
        <Button
          type="button"
          className="rounded-[var(--r-md)]"
          onClick={() => onSubmit(val)}
          disabled={!val.trim()}
        >
          继续 →
        </Button>
      </div>
    </div>
  );
}

function suggestTitle(topic: string, type: DocType): string {
  const t = topic.trim();
  if (!t) return "";
  // Cheap heuristic — chop to ~30 chars and add suffix per doc type.
  const base = t.length > 30 ? `${t.slice(0, 28)}…` : t;
  return type === "act" ? `推进：${base}` : base;
}

function OwnerStep({
  value,
  me,
  onSubmit,
  onSkip,
}: {
  value: { pivotUserId: string; name: string };
  me: Me;
  onSubmit: (v: { pivotUserId: string; name: string }) => void;
  onSkip: () => void;
}) {
  const [local, setLocal] = useState(value);
  return (
    <div className="space-y-2">
      <OwnerPicker
        value={local.pivotUserId}
        onChange={(pivotUserId, name) => setLocal({ pivotUserId, name })}
        sessionPivotUserId={me.id}
        sessionName={me.name}
        displayName={local.name}
        dropdownMode="inline"
      />
      <div className="flex flex-wrap items-center justify-end gap-2">
        <Button
          type="button"
          variant="ghost"
          className="rounded-[var(--r-md)]"
          onClick={onSkip}
        >
          默认我自己
        </Button>
        <Button
          type="button"
          className="rounded-[var(--r-md)]"
          onClick={() => onSubmit(local)}
          disabled={!local.pivotUserId}
        >
          继续 →
        </Button>
      </div>
    </div>
  );
}

function MentionsStep({
  value,
  resolvedNames,
  onSubmit,
  onSkip,
}: {
  value: MentionBlock;
  resolvedNames: Record<string, string>;
  onSubmit: (v: MentionBlock) => void;
  onSkip: () => void;
}) {
  const [local, setLocal] = useState<MentionBlock>(value);
  return (
    <div className="space-y-2">
      <MentionField
        value={local}
        onChange={setLocal}
        resolvedNames={resolvedNames}
      />
      <div className="flex flex-wrap items-center justify-end gap-2">
        <Button
          type="button"
          variant="ghost"
          className="rounded-[var(--r-md)]"
          onClick={onSkip}
        >
          跳过，不圈人
        </Button>
        <Button
          type="button"
          className="rounded-[var(--r-md)]"
          onClick={() => onSubmit(local)}
          disabled={local.open_ids.length === 0}
          title={
            local.open_ids.length === 0
              ? "可点「跳过，不圈人」直接进入下一步"
              : ""
          }
        >
          继续 →
        </Button>
      </div>
    </div>
  );
}

function ReviseStep({
  onSend,
  busy,
}: {
  onSend: (msg: string) => void;
  busy: boolean;
}) {
  const [val, setVal] = useState("");
  const send = () => {
    const t = val.trim();
    if (!t) return;
    onSend(t);
    setVal("");
  };
  return (
    <div className="space-y-2">
      <Textarea
        value={val}
        onChange={(e) => setVal(e.target.value)}
        placeholder="再让 AI 改一改？例如：再精简一些 / 加一段背景介绍 / 风格更正式…（Ctrl + Enter 发送）"
        rows={2}
        maxLength={2000}
        disabled={busy}
        className="min-h-[3.5rem] rounded-[var(--r-md)] border-[var(--line-strong)] bg-[var(--surface-alt)] text-sm"
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            send();
          }
        }}
      />
      <div className="flex justify-end">
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="rounded-[var(--r-md)] gap-1.5"
          onClick={send}
          disabled={busy || !val.trim()}
        >
          <Send className="h-3.5 w-3.5" />
          {busy ? "AI 修订中…" : "发送给 AI 修订"}
        </Button>
      </div>
    </div>
  );
}

function CategoryPicker({
  value,
  options,
  onChange,
}: {
  value: string;
  options: string[];
  onChange: (category: string) => void;
}) {
  const [query, setQuery] = useState(value);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setQuery(value);
  }, [value]);

  const normalizedQuery = query.trim();
  const filtered = options
    .filter((cat) => cat.toLowerCase().includes(normalizedQuery.toLowerCase()))
    .slice(0, 8);
  const exact = options.some(
    (cat) => cat.toLowerCase() === normalizedQuery.toLowerCase(),
  );
  const isSelectedCustom =
    normalizedQuery.length > 0 &&
    value.trim().toLowerCase() === normalizedQuery.toLowerCase() &&
    !exact;
  const canCreate = normalizedQuery.length > 0 && !exact;

  const choose = (category: string) => {
    const next = category.trim();
    if (!CATEGORY_PATTERN.test(next)) {
      toast.error('种类需为 1-20 个字符，且不能包含 / \\ : * ? " < > | 或换行');
      return;
    }
    onChange(next);
    setQuery(next);
    setOpen(false);
  };

  return (
    <div className="relative">
      <div className="flex h-9 items-center rounded-[var(--r-sm)] border border-[var(--line-strong)] bg-[var(--surface-alt)] focus-within:border-[var(--accent)]">
        <input
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => window.setTimeout(() => setOpen(false), 120)}
          onKeyDown={(e) => {
            if (e.key !== "Enter") return;
            e.preventDefault();
            if (exact) {
              const match = options.find(
                (cat) => cat.toLowerCase() === normalizedQuery.toLowerCase(),
              );
              if (match) choose(match);
              return;
            }
            if (canCreate) choose(normalizedQuery);
          }}
          placeholder="搜索或新建种类"
          className="h-full min-w-0 flex-1 bg-transparent px-3 text-sm outline-none"
        />
        <button
          type="button"
          className="h-full px-3 text-xs text-[var(--text-mute)] hover:text-[var(--text)]"
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => setOpen((v) => !v)}
          aria-label="展开种类"
        >
          ▼
        </button>
      </div>

      {open && (
        <div className="absolute left-0 right-0 top-full z-30 mt-1 max-h-64 overflow-auto rounded-[var(--r-md)] border border-[var(--line)] bg-[var(--surface)] p-1 shadow-lg">
          {filtered.length > 0 && (
            <>
              <div className="px-2 py-1 text-[10px] font-medium text-[var(--text-mute)]">
                已有种类
              </div>
              {filtered.map((cat) => (
                <button
                  key={cat}
                  type="button"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => choose(cat)}
                  className={cn(
                    "block w-full rounded-[var(--r-sm)] px-2 py-1.5 text-left text-sm hover:bg-[var(--surface-alt)]",
                    cat === value ? "font-medium text-[var(--accent)]" : "text-[var(--text)]",
                  )}
                >
                  {cat}
                </button>
              ))}
            </>
          )}

          {isSelectedCustom && (
            <>
              {filtered.length > 0 && (
                <div className="my-1 border-t border-[var(--line)]" />
              )}
              <div className="rounded-[var(--r-sm)] px-2 py-1.5 text-sm text-[var(--text-soft)]">
                当前新建：{normalizedQuery}
              </div>
            </>
          )}

          {canCreate && !isSelectedCustom && (
            <>
              {filtered.length > 0 && (
                <div className="my-1 border-t border-[var(--line)]" />
              )}
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => choose(normalizedQuery)}
                className="block w-full rounded-[var(--r-sm)] px-2 py-1.5 text-left text-sm text-[var(--accent)] hover:bg-[var(--accent-bg)]"
              >
                + 新建 “{normalizedQuery}”
              </button>
            </>
          )}

          {filtered.length === 0 && !canCreate && (
            <div className="px-2 py-2 text-sm text-[var(--text-mute)]">
              输入种类名称
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function PreviewPanel({
  data,
  phase,
  me,
  availableCategories,
  streamingBody,
  isStreaming,
  resolvedNames,
  onUpdateData,
  onSelectCategory,
  onEditBody,
  onEditSummary,
  canEdit,
}: {
  data: StepData;
  phase: Phase;
  me: Me;
  availableCategories: string[];
  streamingBody: string;
  isStreaming: boolean;
  resolvedNames: Record<string, string>;
  onUpdateData: (patch: Partial<StepData>) => void;
  onSelectCategory: (category: string) => void;
  onEditBody: (b: string) => void;
  onEditSummary: (s: string) => void;
  canEdit: boolean;
}) {
  const reached = (p: Phase) => PHASE_ORDER.indexOf(p) <= PHASE_ORDER.indexOf(phase);
  const bodyToShow = isStreaming ? streamingBody : data.body;

  return (
    <Card className="space-y-4 rounded-[var(--r-md)] border border-[var(--line)] bg-[var(--surface)] p-4">
      <PreviewRow label="话题" filled={reached("type") && !!data.topic}>
        {data.topic || <Empty />}
      </PreviewRow>

      <PreviewRow label="类型" filled={reached("category")}>
        {canEdit ? (
          <div className="inline-flex rounded-[var(--r-sm)] border border-[var(--line)] bg-[var(--surface-alt)] p-0.5">
            {(["think", "act"] as const).map((type) => (
              <button
                key={type}
                type="button"
                onClick={() => onUpdateData({ docType: type })}
                className={cn(
                  "rounded-[var(--r-sm)] px-2.5 py-1 font-mono text-xs",
                  data.docType === type
                    ? "bg-[var(--accent)] text-white"
                    : "text-[var(--text-soft)] hover:bg-[var(--surface)]",
                )}
              >
                {type}
              </button>
            ))}
          </div>
        ) : reached("category") ? (
          <span className="font-mono">{data.docType}</span>
        ) : (
          <Empty />
        )}
      </PreviewRow>

      <PreviewRow label="种类" filled={reached("title") && !!data.category}>
        {canEdit ? (
          <CategoryPicker
            value={data.category}
            options={availableCategories}
            onChange={onSelectCategory}
          />
        ) : (
          data.category || <Empty />
        )}
      </PreviewRow>

      <PreviewRow label="标题" filled={reached("owner") && !!data.title}>
        {canEdit ? (
          <Input
            value={data.title}
            onChange={(e) => onUpdateData({ title: e.target.value })}
            maxLength={200}
            className="h-9 text-sm"
          />
        ) : (
          data.title || <Empty />
        )}
      </PreviewRow>

      <PreviewRow label="责任人" filled={reached("mentions") && !!data.matterOwner.pivotUserId}>
        {!reached("mentions") ? (
          <Empty />
        ) : canEdit ? (
          <OwnerPicker
            value={data.matterOwner.pivotUserId}
            onChange={(pivotUserId, name) => onUpdateData({ matterOwner: { pivotUserId, name } })}
            sessionPivotUserId={me.id}
            sessionName={me.name}
            displayName={data.matterOwner.name}
            dropdownMode="inline"
          />
        ) : (
          <span>{data.matterOwner.name || data.matterOwner.pivotUserId || "我"}</span>
        )}
      </PreviewRow>

      <PreviewRow label="圈人" filled={reached("drafting")}>
        {!reached("drafting") ? (
          <Empty />
        ) : canEdit ? (
          <MentionField
            value={data.mentions}
            onChange={(mentions) => onUpdateData({ mentions })}
            resolvedNames={resolvedNames}
          />
        ) : data.mentions.open_ids.length === 0 ? (
          <span className="text-[var(--text-mute)]">未圈人</span>
        ) : (
          <div>
            <div className="flex flex-wrap gap-1">
              {data.mentions.open_ids.map((oid) => (
                <span
                  key={oid}
                  className="rounded bg-[var(--accent-bg)] px-1.5 py-0.5 text-xs text-[var(--accent)]"
                >
                  @{resolvedNames[oid] ?? oid.slice(0, 6)}
                </span>
              ))}
            </div>
            {data.mentions.comments.trim() && (
              <div className="mt-1 text-xs text-[var(--text-mute)]">
                {data.mentions.comments.trim()}
              </div>
            )}
          </div>
        )}
      </PreviewRow>

      <PreviewRow
        label="正文"
        filled={!!bodyToShow}
        action={
          isStreaming ? (
            <span className="text-xs text-[var(--accent)]">
              <Sparkles className="inline h-3 w-3 animate-pulse" /> 正在生成...
            </span>
          ) : null
        }
      >
        {!bodyToShow ? (
          <Empty hint="AI 起草后显示" />
        ) : canEdit ? (
          <Textarea
            value={data.body}
            onChange={(e) => onEditBody(e.target.value)}
            rows={12}
            maxLength={50000}
            className="min-h-[14rem] rounded-[var(--r-sm)] border-[var(--line-strong)] bg-[var(--surface-alt)] font-mono text-xs"
          />
        ) : (
          <pre className="whitespace-pre-wrap rounded-[var(--r-sm)] bg-[var(--surface-alt)] p-2 font-mono text-xs leading-relaxed">
            {bodyToShow}
          </pre>
        )}
      </PreviewRow>

      <PreviewRow label="摘要" filled={!!data.summary}>
        {!data.summary ? (
          <Empty hint="AI 起草后显示" />
        ) : canEdit ? (
          <Input
            value={data.summary}
            onChange={(e) => onEditSummary(e.target.value)}
            maxLength={500}
            className="text-xs"
          />
        ) : (
          <span className="text-xs">{data.summary}</span>
        )}
      </PreviewRow>
    </Card>
  );
}
function PreviewRow({
  label,
  filled,
  children,
  action,
}: {
  label: string;
  filled: boolean;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "rounded-[var(--r-sm)] border-l-2 px-3 py-2 transition-opacity",
        filled
          ? "border-l-[var(--accent)] opacity-100"
          : "border-l-transparent opacity-50",
      )}
    >
      <div className="mb-1 flex items-center justify-between">
        <Label className="text-[11px] uppercase tracking-wider text-[var(--text-mute)]">
          {label}
        </Label>
        {action}
      </div>
      <div className="text-sm leading-6 text-[var(--text)]">{children}</div>
    </div>
  );
}

function Empty({ hint }: { hint?: string } = {}) {
  return (
    <span className="text-xs italic text-[var(--text-mute)]">
      {hint || "等待中…"}
    </span>
  );
}
