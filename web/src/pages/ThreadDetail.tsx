import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import Markdown from "react-markdown";
import { fetchThread, postReply, type Me, type Post, type ThreadDetail as ThreadDetailData } from "../api";
import { UserBar } from "../components/UserBar";
import { StatusBadge } from "../components/StatusBadge";
import { relativeTime } from "../lib/time";

export function ThreadDetail({ me, onLogout }: { me: Me; onLogout: () => void }) {
  const { category, slug } = useParams<{ category: string; slug: string }>();
  const [data, setData] = useState<ThreadDetailData | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    if (!category || !slug) return;
    fetchThread(category, slug)
      .then(setData)
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
            <StatusBadge status={data.meta.status} />
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

function ReplyForm({
  category, slug, onPosted,
}: { category: string; slug: string; onPosted: () => void }) {
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await postReply(category, slug, body);
      setBody("");
      onPosted();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
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
      <div style={{ fontWeight: 600 }}>Reply</div>
      <textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        rows={6}
        maxLength={50000}
        placeholder="Write a reply in markdown…"
        style={{
          width: "100%",
          padding: 8,
          fontSize: 14,
          fontFamily: "ui-monospace, SFMono-Regular, monospace",
        }}
      />
      {error && <div style={{ color: "#c00" }}>{error}</div>}
      <div>
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
      </div>
    </form>
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
