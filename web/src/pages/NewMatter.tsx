import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
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
import { Layout } from "@/components/Layout";
import { formatSaveStatus, useDraftAutosave } from "@/hooks/useDraftAutosave";

const NEW_CATEGORY_OPTION = "__new_category__";
const CATEGORY_PATTERN = /^[^/\\:*?"<>|\t\n\r]{1,20}$/;

export function NewMatter({ me, onLogout }: { me: Me; onLogout: () => void }) {
  const navigate = useNavigate();
  const [category, setCategory] = useState("");
  const [newCategory, setNewCategory] = useState("");
  const [categoryMode, setCategoryMode] = useState<"select" | "create">("select");
  const [availableCategories, setAvailableCategories] = useState<string[]>([]);
  const [title, setTitle] = useState("");
  const [initialType, setInitialType] = useState<DocType>("think");
  const [body, setBody] = useState("");
  const [owner, setOwner] = useState<string>(me.pinyin ?? "");
  const [stage, setStage] = useState<"idle" | "generating" | "submitting">("idle");
  const submitting = stage !== "idle";
  const [draftId, setDraftId] = useState<string | null>(null);
  const [draftLoaded, setDraftLoaded] = useState(false);

  useEffect(() => {
    // /api/matters 返回里已经带 category,直接从已存在 matter 推断当前
    // workspace 用过哪些 category;空 workspace 时直接进入 create 模式,
    // 让用户当场新建第一个分类。同时拉一遍 drafts,把上次没发布完的
    // matter 草稿(type=proposal && thread_key==null)恢复到表单。
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

        const candidate = drafts
          .filter((d) => d.type === "proposal" && !d.thread_key)
          .sort((a, b) => b.updated_at - a.updated_at)[0];

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
          const payload = candidate.matter_payload ?? {};
          const dt = String((payload as Record<string, unknown>).doc_type ?? "");
          if (dt === "act" || dt === "think") setInitialType(dt);
          const ow = String((payload as Record<string, unknown>).owner ?? "");
          if (ow) setOwner(ow);
        } else if (cats.length === 0) {
          setCategoryMode("create");
        } else {
          setCategory((current) => current || cats[0]);
        }
      })
      .catch(() => {})
      .finally(() => setDraftLoaded(true));
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
        ...(owner.trim() ? { owner: owner.trim() } : {}),
      },
    }),
    enabled: draftLoaded && isDirty && stage === "idle",
    deps: [draftLoaded, isDirty, stage, title, category, body, initialType, owner],
  });

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

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return toast.error("title 必填");
    if (!body.trim()) return toast.error("正文必填（AI 将基于此生成 summary）");

    setStage("generating");
    let summary = "";
    try {
      const userMsg = [
        `请为下面这篇新增的 ${initialType} 文件生成一句不超过 80 字的中文 summary。`,
        `要求：`,
        `- 直接输出这一句话本身，不要加引号，也不要任何前后解释。`,
        `- 用最精简的语言概括这篇文件推进 / 判断 / 结论了什么。`,
        ``,
        `事项标题：${title.trim()}`,
        ``,
        `新文件正文：`,
        "```",
        body.trim(),
        "```",
      ].join("\n");
      // 复用现有 chat 端点：NewMatter 还没有真实文件作起点帖子，传一个占位
      // 字符串。后端 build_starting_post_block 对路径不合法 / 文件不存在的情况
      // 静默降级为空 starting block，AI 仅基于下面 userMsg 里的 body 总结。
      let acc = "";
      for await (const ev of streamAIChat(
        category.trim() || "general",
        "_new_matter_",
        [{ role: "user", content: userMsg }],
        "_new_matter_summary_",
      )) {
        if (ev.kind === "delta") acc += ev.delta;
      }
      summary = acc.trim();
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
        initial_file: {
          type: initialType,
          summary,
          body: body.trim(),
          owner: owner.trim() || undefined,
        },
      });
      if (draftId) {
        try {
          await deleteDraft(draftId);
        } catch {
          // 草稿删除失败不影响 matter 已发布的事实，仅吞掉错误。
        }
      }
      navigate(`/m/${encodeURIComponent(r.matter_id)}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setStage("idle");
    }
  };

  return (
    <Layout me={me} onLogout={onLogout}>
      <div className="mx-auto max-w-4xl space-y-4 sm:space-y-6">
        <Button
          asChild
          variant="ghost"
          size="sm"
          className="rounded-xl px-3 text-slate-700 hover:bg-slate-100"
        >
          <Link to="/">
            <ArrowLeft className="h-4 w-4" />
            返回 matter 列表
          </Link>
        </Button>
        <div className="space-y-2">
          <div className="section-kicker">New Matter</div>
          <div className="flex flex-wrap items-baseline gap-3">
            <h1 className="text-2xl font-semibold tracking-[-0.03em] text-slate-950 sm:text-3xl">
              新讨论
            </h1>
            {draftStatus !== "idle" && (
              <span
                className={
                  draftStatus === "error"
                    ? "text-xs text-red-600"
                    : "text-xs text-slate-500"
                }
              >
                {formatSaveStatus(draftStatus)}
              </span>
            )}
          </div>
          <p className="max-w-2xl text-sm leading-7 text-slate-600">
            这里直接进入 matter 的起草区。先确定分类和标题，再把正文写清楚；表单会自动保存草稿，不需要额外操作。
          </p>
        </div>

        <Card className="paper-panel rounded-[1.25rem] border sm:rounded-[1.75rem]">
          <form onSubmit={submit} className="space-y-6 p-4 sm:p-8">
            {/* Category */}
            <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
              <div className="space-y-2">
                <div className="section-kicker">Category</div>
                <p className="text-sm leading-6 text-slate-500">
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
                  className="flex h-11 w-full rounded-xl border border-input bg-slate-100/90 px-3 py-2 text-sm ring-offset-background"
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
                      <Button type="button" variant="outline" className="rounded-xl" onClick={createCategory}>
                        创建并选中
                      </Button>
                    </div>
                    <p className="text-xs leading-5 text-slate-500">
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
                <p className="text-sm leading-6 text-slate-500">标题决定 matter 在左侧目录里的可读性，尽量写成一个完整的主题句。</p>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="title">标题</Label>
                <Input
                  id="title"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  required
                  maxLength={200}
                  className="h-11 rounded-xl bg-slate-100/90"
                />
              </div>
            </div>

            <div className="editor-divider border-t" />

            {/* Initial file type */}
            <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
              <div className="space-y-2">
                <div className="section-kicker">首篇文件</div>
                <p className="text-sm leading-6 text-slate-500">
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
                    正文（markdown）<span className="text-red-500"> *</span>
                  </Label>
                  <p className="text-xs text-slate-500">
                    创建时 AI 将基于正文生成 summary。
                  </p>
                  <Textarea
                    id="body"
                    value={body}
                    onChange={(e) => setBody(e.target.value)}
                    required
                    rows={10}
                    maxLength={50000}
                    className="min-h-[14rem] rounded-2xl border-slate-300 bg-slate-100/92 font-mono text-sm"
                  />
                </div>
                {initialType === "act" && (
                  <div className="grid gap-2">
                    <Label htmlFor="owner">Owner（执行人 · 可选；默认你自己）</Label>
                    <Input
                      id="owner"
                      value={owner}
                      onChange={(e) => setOwner(e.target.value)}
                      placeholder={me.pinyin ?? "pinyin"}
                      className="h-11 rounded-xl bg-slate-100/90"
                    />
                  </div>
                )}
              </div>
            </div>

            <div className="flex flex-wrap gap-3 pt-2">
              <Button
                type="submit"
                className="rounded-xl px-5"
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
    </Layout>
  );
}
