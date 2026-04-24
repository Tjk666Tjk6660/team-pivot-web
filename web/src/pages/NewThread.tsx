import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft } from "lucide-react";
import {
  deleteDraft,
  fetchDraft,
  fetchThreads,
  publishDraft,
  type Me,
  type MentionBlock,
} from "@/api";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Layout } from "@/components/Layout";
import { MentionField, emptyMention, isMentionValid } from "@/components/MentionField";
import { formatSaveStatus, useDraftAutosave } from "@/hooks/useDraftAutosave";

const NEW_CATEGORY_OPTION = "__new_category__";
const CATEGORY_PATTERN = /^[^/\\:*?"<>|\t\n\r]{1,20}$/;

export function NewThread({ me, onLogout }: { me: Me; onLogout: () => void }) {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const initialDraftId = searchParams.get("draft");

  const [draftId, setDraftIdState] = useState<string | null>(initialDraftId);
  const [category, setCategory] = useState("general");
  const [availableCategories, setAvailableCategories] = useState<string[]>([]);
  const [categoryMode, setCategoryMode] = useState<"select" | "create">("select");
  const [newCategory, setNewCategory] = useState("");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [mentions, setMentions] = useState<MentionBlock>(emptyMention());
  const resolvedNames = useRef<Record<string, string>>({});
  const [loading, setLoading] = useState(initialDraftId !== null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    fetchThreads()
      .then((items) => {
        setAvailableCategories(
          Array.from(new Set(items.map((item) => item.category.trim()).filter(Boolean))),
        );
      })
      .catch((e) => toast.error(e instanceof Error ? e.message : String(e)));
  }, []);

  useEffect(() => {
    if (!initialDraftId) return;
    fetchDraft(initialDraftId)
      .then((d) => {
        if (d.type !== "proposal") return;
        setCategory(d.category ?? "general");
        setTitle(d.title ?? "");
        setBody(d.body_md);
        if (d.mentions) setMentions(d.mentions);
      })
      .catch((e) => toast.error(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [initialDraftId]);

  useEffect(() => {
    if (category.trim() && !availableCategories.includes(category.trim())) {
      setCategoryMode("create");
      setNewCategory(category.trim());
      return;
    }
    setCategoryMode("select");
    setNewCategory("");
  }, [availableCategories, category]);

  const setDraftId = (id: string) => {
    setDraftIdState(id);
    setSearchParams({ draft: id }, { replace: true });
  };

  const hasContent = title.trim().length > 0 || body.trim().length > 0;
  const { status, saveNow } = useDraftAutosave({
    draftId, setDraftId,
    type: "proposal",
    payload: () => ({
      title: title.trim() || null,
      category: category.trim() || null,
      body_md: body,
      mentions: mentions.open_ids.length > 0 || mentions.comments ? mentions : null,
    }),
    enabled: !loading && hasContent,
    deps: [category, title, body, loading, mentions],
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
    setAvailableCategories((current) => (
      current.includes(next) ? current : [...current, next]
    ));
    setCategory(next);
    setCategoryMode("select");
    setNewCategory("");
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isMentionValid(mentions)) {
      toast.error("圈人后必须填一句话");
      return;
    }
    setSubmitting(true);
    try {
      const id = await saveNow();
      if (!id) throw new Error("failed to save draft before publish");
      const r = await publishDraft(id);
      navigate(
        `/t/${encodeURIComponent(r.published.category!)}/${encodeURIComponent(r.published.slug!)}`,
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const discard = async () => {
    if (!draftId) { navigate("/"); return; }
    if (!confirm("Discard this draft?")) return;
    try {
      await deleteDraft(draftId);
      navigate("/");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <Layout me={me} onLogout={onLogout}>
      <div className="mx-auto max-w-4xl space-y-4 sm:space-y-6">
        <Button asChild variant="ghost" size="sm" className="rounded-xl px-3 text-[var(--text-soft)] hover:bg-[var(--surface-alt)]">
          <Link to="/"><ArrowLeft className="h-4 w-4" /> 返回讨论列表</Link>
        </Button>
        <div className="space-y-2">
          <div className="section-kicker">New Discussion</div>
          <div className="flex flex-wrap items-baseline gap-3">
            <h1 className="text-2xl font-semibold tracking-[-0.03em] text-[var(--text)] sm:text-3xl">
              {draftId ? "编辑草稿" : "新讨论"}
            </h1>
            <span className={`text-xs ${status === "error" ? "text-destructive" : "text-muted-foreground"}`}>
              {formatSaveStatus(status)}
            </span>
          </div>
          <p className="max-w-2xl text-sm leading-7 text-[var(--text-soft)]">
            这里直接进入 thread 的起草区。先确定分类和标题，再把正文写清楚；表单会自动保存草稿，不需要额外操作。
          </p>
        </div>
        <Card className="paper-panel rounded-[1.25rem] border sm:rounded-[1.75rem]">
          <form onSubmit={submit} className="space-y-6 p-4 sm:p-8">
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
                  className="flex h-11 w-full rounded-xl border border-input bg-[var(--surface-alt)] px-3 py-2 text-sm ring-offset-background"
                >
                  {categoryOptions.map((option) => (
                    <option key={option} value={option}>{option}</option>
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
                      pattern={'^[^/\\\\:*?"<>|\\t\\n\\r]{1,20}$'}
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
                <p className="text-xs text-muted-foreground">
                  支持中文，最长 20 个字符；不能包含 <code>/ \\ : * ? " &lt; &gt; |</code> 或换行。
                </p>
              </div>
            </div>
            <div className="editor-divider border-t" />
            <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
              <div className="space-y-2">
                <div className="section-kicker">Title</div>
                <p className="text-sm leading-6 text-[var(--text-mute)]">
                  标题决定 thread 在左侧目录里的可读性，尽量写成一个完整的主题句。
                </p>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="title">标题</Label>
                <Input
                  id="title"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  required
                  maxLength={200}
                  className="h-11 rounded-xl bg-[var(--surface-alt)]"
                />
              </div>
            </div>
            <div className="editor-divider border-t" />
            <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
              <div className="space-y-2">
                <div className="section-kicker">Body</div>
                <p className="text-sm leading-6 text-[var(--text-mute)]">
                  正文支持 Markdown，适合直接写提案、背景、判断和待讨论问题。
                </p>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="body">正文（markdown）</Label>
                <Textarea
                  id="body"
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  required
                  rows={16}
                  maxLength={50000}
                  className="min-h-[18rem] rounded-2xl border-[var(--line-strong)] bg-[var(--surface-alt)] font-mono text-sm sm:min-h-[24rem]"
                />
                <p className="text-xs text-muted-foreground">
                  若你没写 <code># 标题</code>，会自动以表单 title 作为 H1。
                </p>
              </div>
            </div>
            <div className="editor-divider border-t" />
            <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
              <div className="space-y-2">
                <div className="section-kicker">Mention</div>
                <p className="text-sm leading-6 text-[var(--text-mute)]">
                  如果这条讨论需要明确提及某些人，可以直接在这里补上。
                </p>
              </div>
              <MentionField
                value={mentions}
                onChange={setMentions}
                resolvedNames={resolvedNames.current}
              />
            </div>
            <div className="flex flex-wrap gap-3 pt-2">
              <Button
                type="submit"
                className="rounded-xl px-5"
                disabled={submitting || !title.trim() || !body.trim()}
              >
                {submitting ? "发布中…" : "Publish"}
              </Button>
              {draftId && (
                <Button type="button" variant="outline" className="rounded-xl" onClick={discard}>
                  删除草稿
                </Button>
              )}
            </div>
          </form>
        </Card>
      </div>
    </Layout>
  );
}
