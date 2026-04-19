import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  deleteDraft,
  fetchDrafts,
  fetchInbox,
  fetchThreads,
  fetchWorkspaceStatus,
  refreshWorkspace,
  syncContacts,
  type Draft,
  type InboxItem,
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
  const [drafts, setDrafts] = useState<Draft[] | null>(null);
  const [inbox, setInbox] = useState<InboxItem[] | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState<
    { text: string; kind: "info" | "success" | "error" } | null
  >(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = async () => {
    try {
      const [t, w, d, ib] = await Promise.all([
        fetchThreads(), fetchWorkspaceStatus(), fetchDrafts(), fetchInbox(),
      ]);
      setThreads(t);
      setWorkspace(w);
      setDrafts(d);
      setInbox(ib);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  useEffect(() => { load(); }, []);

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

  const onSyncContacts = async () => {
    setSyncing(true);
    setSyncMsg({ text: "同步飞书通讯录中…", kind: "info" });
    try {
      const r = await syncContacts();
      setSyncMsg({
        text: `同步完成：共 ${r.total} 位联系人（本次刷新 ${r.synced} 位）`,
        kind: "success",
      });
    } catch (e) {
      setSyncMsg({
        text: `同步失败：${e instanceof Error ? e.message : String(e)}`,
        kind: "error",
      });
    } finally {
      setSyncing(false);
      window.setTimeout(() => setSyncMsg(null), 5000);
    }
  };

  const removeDraft = async (id: string) => {
    if (!confirm("Delete this draft?")) return;
    try {
      await deleteDraft(id);
      setDrafts((ds) => (ds ?? []).filter((d) => d.id !== id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div style={{ padding: 48, fontFamily: "system-ui, sans-serif" }}>
      <UserBar me={me} onLogout={onLogout} />

      {syncMsg && (
        <div
          style={{
            marginTop: 16,
            padding: "10px 14px",
            borderRadius: 4,
            background:
              syncMsg.kind === "error"
                ? "#fce4e4"
                : syncMsg.kind === "success"
                  ? "#e3f6ea"
                  : "#e7efff",
            color:
              syncMsg.kind === "error"
                ? "#c00"
                : syncMsg.kind === "success"
                  ? "#0f7a3b"
                  : "#1650a7",
            fontSize: 13,
          }}
        >
          {syncMsg.text}
        </div>
      )}

      {inbox && inbox.length > 0 && (
        <section style={{ marginTop: 32 }}>
          <h2 style={{ margin: 0 }}>Inbox</h2>
          <ul style={{ marginTop: 12, padding: 0, listStyle: "none" }}>
            {inbox.map((it) => (
              <li
                key={`${it.meta.category}/${it.meta.slug}`}
                style={{ padding: "10px 0", borderBottom: "1px solid #eee" }}
              >
                <Link
                  to={`/t/${encodeURIComponent(it.meta.category)}/${encodeURIComponent(it.meta.slug)}`}
                  style={{ textDecoration: "none", color: "inherit", display: "block" }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ fontWeight: 600 }}>{it.meta.title}</span>
                    <span
                      style={{
                        fontSize: 11,
                        padding: "2px 8px",
                        borderRadius: 10,
                        color: "white",
                        background: "#e54a4a",
                        fontWeight: 500,
                      }}
                    >
                      {it.unread_count}
                    </span>
                  </div>
                  <div style={{ fontSize: 12, color: "#888", marginTop: 4 }}>
                    {it.meta.category}
                    {it.last_post_author_display && ` · 最新: ${it.last_post_author_display}`}
                    {it.meta.last_updated && ` · ${relativeTime(it.meta.last_updated)}`}
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      {drafts && drafts.length > 0 && (
        <section style={{ marginTop: 32 }}>
          <h2 style={{ margin: 0 }}>Drafts</h2>
          <ul style={{ marginTop: 12, padding: 0, listStyle: "none" }}>
            {drafts.map((d) => (
              <li
                key={d.id}
                style={{
                  padding: "10px 0",
                  borderBottom: "1px solid #eee",
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                }}
              >
                <Link
                  to={
                    d.type === "proposal"
                      ? `/new?draft=${d.id}`
                      : d.thread_key
                        ? `/t/${d.thread_key}`
                        : "#"
                  }
                  style={{ textDecoration: "none", color: "inherit", flex: 1 }}
                >
                  <div style={{ fontWeight: 500 }}>
                    {d.type === "proposal"
                      ? (d.title?.trim() || "(untitled)")
                      : `Reply: ${d.thread_key ?? ""}`}
                  </div>
                  <div style={{ fontSize: 12, color: "#888", marginTop: 2 }}>
                    {d.type} · {relativeTime(new Date(d.updated_at * 1000).toISOString())}
                  </div>
                </Link>
                <button
                  onClick={() => removeDraft(d.id)}
                  style={{
                    fontSize: 12, color: "#c00", background: "none",
                    border: "none", cursor: "pointer",
                  }}
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

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
        <button
          onClick={onSyncContacts}
          disabled={syncing}
          style={{ fontSize: 12 }}
          title="从飞书通讯录拉取最新联系人（供 @mention 使用）"
        >
          {syncing ? "同步中…" : "同步联系人"}
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
