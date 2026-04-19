import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { deleteDraft, fetchDraft, publishDraft, type Me, type MentionBlock } from "../api";
import { UserBar } from "../components/UserBar";
import { MentionField, emptyMention, isMentionValid } from "../components/MentionField";
import { formatSaveStatus, useDraftAutosave } from "../hooks/useDraftAutosave";

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
  const [error, setError] = useState<string | null>(null);
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
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [initialDraftId]);

  const setDraftId = (id: string) => {
    setDraftIdState(id);
    setSearchParams({ draft: id }, { replace: true });
  };

  const hasContent = title.trim().length > 0 || body.trim().length > 0;

  const { status, saveNow } = useDraftAutosave({
    draftId,
    setDraftId,
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
      setError("圈人后必须填一句话");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const id = await saveNow();
      if (!id) throw new Error("failed to save draft before publish");
      const r = await publishDraft(id);
      navigate(
        `/t/${encodeURIComponent(r.published.category!)}/${encodeURIComponent(r.published.slug!)}`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const discard = async () => {
    if (!draftId) {
      navigate("/");
      return;
    }
    if (!confirm("Discard this draft?")) return;
    try {
      await deleteDraft(draftId);
      navigate("/");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div style={{ padding: 48, maxWidth: 820, fontFamily: "system-ui, sans-serif" }}>
      <UserBar me={me} onLogout={onLogout} />
      <div style={{ marginTop: 24 }}>
        <Link to="/" style={{ fontSize: 13, color: "#666" }}>
          ← Back to discussions
        </Link>
      </div>
      <div style={{ marginTop: 24, display: "flex", alignItems: "baseline", gap: 12 }}>
        <h1 style={{ margin: 0 }}>
          {draftId ? "Edit draft" : "New discussion"}
        </h1>
        <span style={{ fontSize: 12, color: status === "error" ? "#c00" : "#888" }}>
          {formatSaveStatus(status)}
        </span>
      </div>
      <form
        onSubmit={submit}
        style={{ display: "flex", flexDirection: "column", gap: 16, marginTop: 16 }}
      >
        <label>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Category</div>
          <input
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            required
            pattern="^[a-zA-Z0-9_-]{1,40}$"
            style={{ width: "100%", padding: 8, fontSize: 14 }}
          />
        </label>
        <label>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Title</div>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            maxLength={200}
            style={{ width: "100%", padding: 8, fontSize: 14 }}
          />
        </label>
        <label>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Body (markdown)</div>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            required
            rows={16}
            maxLength={50000}
            style={{
              width: "100%", padding: 8, fontSize: 14,
              fontFamily: "ui-monospace, SFMono-Regular, monospace",
            }}
          />
        </label>
        <MentionField
          value={mentions}
          onChange={setMentions}
          resolvedNames={resolvedNames.current}
        />
        {error && <div style={{ color: "#c00" }}>{error}</div>}
        <div style={{ display: "flex", gap: 12 }}>
          <button
            type="submit"
            disabled={submitting || !title.trim() || !body.trim()}
            style={{
              padding: "10px 20px",
              background: "#3370ff",
              color: "white",
              border: "none",
              borderRadius: 6,
              cursor: "pointer",
            }}
          >
            {submitting ? "Publishing…" : "Publish"}
          </button>
          {draftId && (
            <button
              type="button"
              onClick={discard}
              style={{
                padding: "10px 20px",
                background: "white",
                color: "#c00",
                border: "1px solid #e0c0c0",
                borderRadius: 6,
                cursor: "pointer",
              }}
            >
              Discard draft
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
