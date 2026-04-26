import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft } from "lucide-react";
import {
  createMatter,
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

const NEW_CATEGORY_OPTION = "__new_category__";
const CATEGORY_PATTERN = /^[^/\\:*?"<>|\t\n\r]{1,20}$/;

export function NewMatter({ me, onLogout }: { me: Me; onLogout: () => void }) {
  const navigate = useNavigate();
  const [category, setCategory] = useState("general");
  const [newCategory, setNewCategory] = useState("");
  const [categoryMode, setCategoryMode] = useState<"select" | "create">("select");
  const [availableCategories, setAvailableCategories] = useState<string[]>([]);
  const [title, setTitle] = useState("");
  const [initialType, setInitialType] = useState<DocType>("think");
  const [body, setBody] = useState("");
  const [owner, setOwner] = useState<string>(me.pinyin ?? "");
  const [stage, setStage] = useState<"idle" | "generating" | "submitting">("idle");
  const submitting = stage !== "idle";

  useEffect(() => {
    // categories come from existing matters for discovery; fall back to empty
    fetchMatters()
      .then((items) => {
        // 当前 /api/matters 返回没有 category，但后端目录仍然按 category 分组。
        // 第一版先允许用户手填，初始值留一个 general，不从服务端猜测。
        void items;
      })
      .catch(() => {});
    // best-effort: look up categories from threads list if available
    fetch("/api/threads")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!data?.items) return;
        const cats = Array.from(
          new Set((data.items as { category: string }[]).map((x) => x.category).filter(Boolean)),
        );
        setAvailableCategories(cats);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (category.trim() && !availableCategories.includes(category.trim())) {
      setCategoryMode("create");
      setNewCategory(category.trim());
      return;
    }
    setCategoryMode("select");
    setNewCategory("");
  }, [availableCategories, category]);

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
              新事项
            </h1>
          </div>
          <p className="max-w-2xl text-sm leading-7 text-slate-600">
            第一版：category（分组标签）+ title + 首篇文件（think 或 act）。首篇允许没有 quote。
          </p>
        </div>

        <Card className="paper-panel rounded-[1.25rem] border sm:rounded-[1.75rem]">
          <form onSubmit={submit} className="space-y-6 p-4 sm:p-8">
            {/* Category */}
            <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
              <div className="space-y-2">
                <div className="section-kicker">Category</div>
                <p className="text-sm leading-6 text-slate-500">
                  分组标签，决定磁盘位置 <span className="font-mono">discussions/{category}/...</span>
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
                )}
              </div>
            </div>

            <div className="editor-divider border-t" />

            {/* Title */}
            <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
              <div className="space-y-2">
                <div className="section-kicker">Title</div>
                <p className="text-sm leading-6 text-slate-500">事项标题；列表上一眼能认出是什么事。</p>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="title">Title</Label>
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
                  创建事项的同时写一篇 <span className="font-mono">think</span> 或{" "}
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
                    Body（markdown）<span className="text-red-500"> *</span>
                  </Label>
                  <p className="text-xs text-slate-500">
                    创建时 AI 将基于正文生成 summary，无需手填。
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
