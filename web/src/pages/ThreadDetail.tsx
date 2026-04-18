import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import Markdown from "react-markdown";
import { fetchThread, type Me, type Post, type ThreadDetail as ThreadDetailData } from "../api";
import { UserBar } from "../components/UserBar";

export function ThreadDetail({ me, onLogout }: { me: Me; onLogout: () => void }) {
  const { category, slug } = useParams<{ category: string; slug: string }>();
  const [data, setData] = useState<ThreadDetailData | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!category || !slug) return;
    fetchThread(category, slug)
      .then(setData)
      .catch((e) => {
        setError(e instanceof Error ? e.message : String(e));
        setData(null);
      });
  }, [category, slug]);

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
          <h1 style={{ marginTop: 24, marginBottom: 4 }}>{data.meta.title}</h1>
          <div style={{ fontSize: 13, color: "#888" }}>
            {data.meta.category} ·{" "}
            {data.meta.author_display ?? data.meta.author ?? "unknown"} ·{" "}
            {data.meta.post_count} posts
          </div>
          <div style={{ marginTop: 32 }}>
            {data.posts.map((p) => (
              <PostCard key={p.filename} post={p} />
            ))}
          </div>
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
