import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft } from "lucide-react";
import { deleteDraft, fetchDraft, publishDraft, type Me, type MentionBlock } from "@/api";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Layout } from "@/components/Layout";
import { MentionField, emptyMention, isMentionValid } from "@/components/MentionField";
import { formatSaveStatus, useDraftAutosave } from "@/hooks/useDraftAutosave";

export function NewThread({ me, onLogout }: { me: Me; onLogout: () => void }) {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const initialDraftId = searchParams.get("draft");

  const [draftId, setDraftIdState] = useState<string | null>(initialDraftId);
  const [category, setCategory] = useState("general");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [mentions, setMentions] = useState<MentionBlock>(emptyMention());
  const resolvedNames = useRef<Record<string, string>>({});
  const [loading, setLoading] = useState(initialDraftId !== null);
  const [submitting, setSubmitting] = useState(false);

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
      <div className="max-w-3xl space-y-4">
        <Button asChild variant="ghost" size="sm">
          <Link to="/"><ArrowLeft className="h-4 w-4" /> 返回讨论列表</Link>
        </Button>
        <div className="flex items-baseline gap-3">
          <h1 className="text-2xl font-semibold">
            {draftId ? "编辑草稿" : "新讨论"}
          </h1>
          <span className={`text-xs ${status === "error" ? "text-destructive" : "text-muted-foreground"}`}>
            {formatSaveStatus(status)}
          </span>
        </div>
        <Card>
          <form onSubmit={submit} className="space-y-4 p-6">
            <div className="grid gap-2">
              <Label htmlFor="category">Category</Label>
              <Input
                id="category"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                required
                pattern="^[a-zA-Z0-9_-]{1,40}$"
              />
              <p className="text-xs text-muted-foreground">
                ASCII 字母/数字/<code>- _</code>，最长 40 字符。
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
              />
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
                className="font-mono text-sm"
              />
              <p className="text-xs text-muted-foreground">
                若你没写 <code># 标题</code>，会自动以表单 title 作为 H1。
              </p>
            </div>
            <MentionField
              value={mentions}
              onChange={setMentions}
              resolvedNames={resolvedNames.current}
            />
            <div className="flex gap-3">
              <Button
                type="submit"
                disabled={submitting || !title.trim() || !body.trim()}
              >
                {submitting ? "发布中…" : "Publish"}
              </Button>
              {draftId && (
                <Button type="button" variant="outline" onClick={discard}>
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
