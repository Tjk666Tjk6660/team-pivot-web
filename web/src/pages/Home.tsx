import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  fetchThreads,
  fetchWorkspaceStatus,
  refreshWorkspace,
  type Me,
  type ThreadMeta,
  type WorkspaceStatus,
} from "../api";
import { UserBar } from "../components/UserBar";
import { StatusBadge } from "../components/StatusBadge";
import { relativeTime } from "../lib/time";

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
      <UserBar me={me} onLogout={onLogout} />

      <div style={{ marginTop: 32, display: "flex", alignItems: "baseline", gap: 12 }}>
        <h2 style={{ margin: 0 }}>Discussions</h2>
        {workspace?.head && (
          <span style={{ fontSize: 12, color: "#888" }}>HEAD {workspace.head}</span>
        )}
        <Link
          to="/new"
          style={{
            marginLeft: "auto",
            padding: "4px 10px",
            background: "#3370ff",
            color: "white",
            borderRadius: 4,
            textDecoration: "none",
            fontSize: 13,
          }}
        >
          + New
        </Link>
        <button
          onClick={onRefresh}
          disabled={refreshing}
          style={{ fontSize: 12 }}
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
              style={{ padding: "12px 0", borderBottom: "1px solid #eee" }}
            >
              <Link
                to={`/t/${encodeURIComponent(t.category)}/${encodeURIComponent(t.slug)}`}
                style={{ textDecoration: "none", color: "inherit", display: "block" }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontWeight: 600 }}>{t.title}</span>
                  <StatusBadge status={t.status} />
                </div>
                <div style={{ fontSize: 12, color: "#888", marginTop: 4 }}>
                  {t.category} · {t.author_display ?? t.author ?? "unknown"} ·{" "}
                  {t.post_count} posts
                  {t.last_updated && ` · ${relativeTime(t.last_updated)}`}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
