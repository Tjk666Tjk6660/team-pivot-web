import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import Markdown from "react-markdown";
import {
  changeThreadStatus,
  deleteDraft,
  fetchDrafts,
  fetchThread,
  markThreadRead,
  publishDraft,
  type Me,
  type Post,
  type ThreadDetail as ThreadDetailData,
} from "../api";
import { UserBar } from "../components/UserBar";
import { StatusControl } from "../components/StatusControl";
import { relativeTime } from "../lib/time";
import { formatSaveStatus, useDraftAutosave } from "../hooks/useDraftAutosave";

export function ThreadDetail({ me, onLogout }: { me: Me; onLogout: () => void }) {
  const { category, slug } = useParams<{ category: string; slug: string }>();
  const [data, setData] = useState<ThreadDetailData | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    if (!category || !slug) return;
    fetchThread(category, slug)
      .then((d) => {
        setData(d);
        markThreadRead(category, slug).catch(() => {});
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : String(e));
        setData(null);
      });
  };

  useEffect(load, [category, slug]);

  return (
    <div style={{ padding: 48, maxWidth: 820, fontFamily: "system-ui, sans-serif" }}>
      <UserBar me={me} onLogout={onLogout} />
      <div style={{ marginTop: 24 }}>
        <Link to="/" style={{ fontSize: 13, color: "#666" }}>
          ← Back to discussions
        </Link>
      </div>
      {error && <div style={{ color: "#c00", marginTop: 16 }}>{error}</div>}
      {data === undefined && !error && (
        <div style={{ marginTop: 16, color: "#888" }}>Loading…</div>
      )}
      {data && (
        <>
          <div
            style={{
              marginTop: 24,
              display: "flex",
              alignItems: "center",
              gap: 12,
              flexWrap: "wrap",
            }}
          >
            <h1 style={{ margin: 0 }}>{data.meta.title}</h1>
            <StatusControl
              status={data.meta.status}
              onChange={async (to, reason) => {
                if (!category || !slug) return;
                await changeThreadStatus(category, slug, to, reason);
                load();
              }}
            />
          </div>
          <div style={{ fontSize: 13, color: "#888", marginTop: 4 }}>
            {data.meta.category} ·{" "}
            {data.meta.author_display ?? data.meta.author ?? "unknown"} ·{" "}
            {data.meta.post_count} posts
            {data.meta.last_updated &&
              ` · last activity ${relativeTime(data.meta.last_updated)}`}
          </div>
          <div style={{ marginTop: 32 }}>
            {data.posts.map((p) => (
              <PostCard key={p.filename} post={p} />
            ))}
          </div>
          {category && slug && (
            <ReplyForm category={category} slug={slug} onPosted={load} />
          )}
        </>
      )}
    </div>
  );
}

function PostCard({ post }: { post: Post }) {
  const author =
    post.author_display ?? (post.frontmatter.author as string) ?? "unknown";
  const type = (post.frontmatter.type as string) ?? "";
  return (
    <article
      style={{
        borderLeft: "3px solid #eee",
        paddingLeft: 16,
        marginBottom: 32,
      }}
    >
      <div style={{ fontSize: 12, color: "#888", marginBottom: 8 }}>
        {post.filename} {type && `· ${type}`} · {author}
      </div>
      <div style={{ lineHeight: 1.6 }}>
        <Markdown>{post.body}</Markdown>
      </div>
    </article>
  );
}

function ReplyForm({
  category, slug, onPosted,
}: { category: string; slug: string; onPosted: () => void }) {
  const threadKey = `${category}/${slug}`;
  const [draftId, setDraftId] = useState<string | null>(null);
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    fetchDrafts()
      .then((items) => {
        const existing = items.find((d) => d.type === "reply" && d.thread_key === threadKey);
        if (existing) {
          setDraftId(existing.id);
          setBody(existing.body_md);
        }
      })
      .catch(() => {});
  }, [threadKey]);

  const { status, saveNow } = useDraftAutosave({
    draftId,
    setDraftId,
    type: "reply",
    payload: () => ({ body_md: body, thread_key: threadKey }),
    enabled: body.trim().length > 0,
    deps: [body],
  });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const id = await saveNow();
      if (!id) throw new Error("failed to save draft before posting");
      await publishDraft(id);
      setDraftId(null);
      setBody("");
      onPosted();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const discard = async () => {
    if (!draftId) { setBody(""); return; }
    if (!confirm("Discard this reply draft?")) return;
    try {
      await deleteDraft(draftId);
      setDraftId(null);
      setBody("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <form
      onSubmit={submit}
      style={{
        marginTop: 32,
        borderTop: "2px solid #eee",
        paddingTop: 24,
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
        <div style={{ fontWeight: 600 }}>Reply</div>
        <span style={{ fontSize: 12, color: status === "error" ? "#c00" : "#888" }}>
          {formatSaveStatus(status)}
        </span>
      </div>
      <textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        rows={6}
        maxLength={50000}
        placeholder="Write a reply in markdown…"
        style={{
          width: "100%", padding: 8, fontSize: 14,
          fontFamily: "ui-monospace, SFMono-Regular, monospace",
        }}
      />
      {error && <div style={{ color: "#c00" }}>{error}</div>}
      <div style={{ display: "flex", gap: 12 }}>
        <button
          type="submit"
          disabled={submitting || !body.trim()}
          style={{
            padding: "8px 16px",
            background: "#3370ff",
            color: "white",
            border: "none",
            borderRadius: 4,
            cursor: "pointer",
          }}
        >
          {submitting ? "Posting…" : "Post reply"}
        </button>
        {draftId && (
          <button
            type="button"
            onClick={discard}
            style={{
              padding: "8px 16px",
              background: "white",
              color: "#c00",
              border: "1px solid #e0c0c0",
              borderRadius: 4,
              cursor: "pointer",
            }}
          >
            Discard draft
          </button>
        )}
      </div>
    </form>
  );
}
