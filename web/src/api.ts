export type Me = {
  open_id: string;
  name: string;
  avatar_url: string;
  pinyin: string | null;
  github_username: string | null;
  needs_setup: boolean;
};

export async function fetchMe(): Promise<Me | null> {
  const r = await fetch("/me", { credentials: "include" });
  if (r.status === 401) return null;
  if (!r.ok) throw new Error(`/me failed: ${r.status}`);
  return (await r.json()) as Me;
}

export async function updateProfile(
  body: { pinyin?: string; github_username?: string | null },
): Promise<Me> {
  const r = await fetch("/me/profile", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const detail = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(detail.detail || `/me/profile failed: ${r.status}`);
  }
  return (await r.json()) as Me;
}

export async function logout(): Promise<void> {
  await fetch("/logout", { method: "POST", credentials: "include" });
}

export type ThreadMeta = {
  category: string;
  slug: string;
  title: string;
  author: string | null;
  author_display: string | null;
  status: string | null;
  last_updated: string | null;
  post_count: number;
};

export async function fetchThreads(category?: string): Promise<ThreadMeta[]> {
  const qs = category ? `?category=${encodeURIComponent(category)}` : "";
  const r = await fetch(`/api/threads${qs}`, { credentials: "include" });
  if (!r.ok) throw new Error(`/api/threads failed: ${r.status}`);
  const body = (await r.json()) as { items: ThreadMeta[] };
  return body.items;
}

export type WorkspaceStatus = {
  ready: boolean;
  path: string;
  head: string | null;
};

export async function fetchWorkspaceStatus(): Promise<WorkspaceStatus> {
  const r = await fetch("/api/workspace/status", { credentials: "include" });
  if (!r.ok) throw new Error(`/api/workspace/status failed: ${r.status}`);
  return (await r.json()) as WorkspaceStatus;
}

export type Post = {
  filename: string;
  frontmatter: Record<string, unknown>;
  body: string;
  author_display: string | null;
};

export type ThreadDetail = {
  meta: ThreadMeta;
  posts: Post[];
};

export async function fetchThread(category: string, slug: string): Promise<ThreadDetail> {
  const r = await fetch(
    `/api/threads/${encodeURIComponent(category)}/${encodeURIComponent(slug)}`,
    { credentials: "include" },
  );
  if (r.status === 404) throw new Error("thread not found");
  if (!r.ok) throw new Error(`fetch thread failed: ${r.status}`);
  return (await r.json()) as ThreadDetail;
}

export async function createThread(
  body: { category: string; title: string; body: string },
): Promise<{ category: string; slug: string; filename: string }> {
  const r = await fetch("/api/threads", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const detail = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(detail.detail || `create failed: ${r.status}`);
  }
  return await r.json();
}

export async function postReply(
  category: string, slug: string, body: string,
): Promise<{ filename: string }> {
  const r = await fetch(
    `/api/threads/${encodeURIComponent(category)}/${encodeURIComponent(slug)}/posts`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body }),
    },
  );
  if (!r.ok) {
    const detail = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(detail.detail || `reply failed: ${r.status}`);
  }
  return await r.json();
}

export async function refreshWorkspace(): Promise<WorkspaceStatus> {
  const r = await fetch("/api/workspace/refresh", {
    method: "POST",
    credentials: "include",
  });
  if (!r.ok) throw new Error(`/api/workspace/refresh failed: ${r.status}`);
  const body = (await r.json()) as { ok: boolean; head: string | null };
  return { ready: true, path: "", head: body.head };
}
