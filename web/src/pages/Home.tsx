import { useEffect, useState } from "react";
import {
  fetchThreads,
  fetchWorkspaceStatus,
  refreshWorkspace,
  type Me,
  type ThreadMeta,
  type WorkspaceStatus,
} from "../api";

export function Home({ me, onLogout }: { me: Me; onLogout: () => void }) {
  const [threads, setThreads] = useState<ThreadMeta[] | null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = async () => {
    try {
      const [t, w] = await Promise.all([fetchThreads(), fetchWorkspaceStatus()]);
      setThreads(t);
      setWorkspace(w);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  useEffect(() => {
    load();
  }, []);

  const onRefresh = async () => {
    setRefreshing(true);
    try {
      await refreshWorkspace();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <div style={{ padding: 48, fontFamily: "system-ui, sans-serif" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        {me.avatar_url && (
          <img
            src={me.avatar_url}
            alt=""
            width={40}
            height={40}
            style={{ borderRadius: "50%" }}
          />
        )}
        <div>
          <div style={{ fontWeight: 600 }}>{me.name}</div>
          <div style={{ fontSize: 12, color: "#666" }}>
            {me.pinyin}
            {me.github_username ? ` · @${me.github_username}` : ""}
          </div>
        </div>
        <button onClick={onLogout} style={{ marginLeft: "auto" }}>
          Sign out
        </button>
      </div>

      <div style={{ marginTop: 32, display: "flex", alignItems: "baseline", gap: 12 }}>
        <h2 style={{ margin: 0 }}>Discussions</h2>
        {workspace?.head && (
          <span style={{ fontSize: 12, color: "#888" }}>
            HEAD {workspace.head}
          </span>
        )}
        <button
          onClick={onRefresh}
          disabled={refreshing}
          style={{ marginLeft: "auto", fontSize: 12 }}
        >
          {refreshing ? "Pulling…" : "Refresh"}
        </button>
      </div>

      {error && <div style={{ color: "#c00", marginTop: 12 }}>{error}</div>}

      {threads === null ? (
        <div style={{ marginTop: 16, color: "#888" }}>Loading threads…</div>
      ) : threads.length === 0 ? (
        <div style={{ marginTop: 16, color: "#888" }}>
          No threads yet. Repository may be empty or has no proposal-type posts.
        </div>
      ) : (
        <ul style={{ marginTop: 16, padding: 0, listStyle: "none" }}>
          {threads.map((t) => (
            <li
              key={`${t.category}/${t.slug}`}
              style={{
                padding: "12px 0",
                borderBottom: "1px solid #eee",
                display: "flex",
                gap: 12,
              }}
            >
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600 }}>{t.title}</div>
                <div style={{ fontSize: 12, color: "#888", marginTop: 4 }}>
                  {t.category} · {t.author ?? "unknown"} · {t.post_count} posts
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
