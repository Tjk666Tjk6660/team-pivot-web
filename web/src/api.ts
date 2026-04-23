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
  unread_count: number;
  favorite: boolean;
};

export async function fetchThreads(category?: string): Promise<ThreadMeta[]> {
  const qs = category ? `?category=${encodeURIComponent(category)}` : "";
  const r = await fetch(`/api/threads${qs}`, { credentials: "include" });
  if (!r.ok) throw new Error(`/api/threads failed: ${r.status}`);
  const body = (await r.json()) as { items: ThreadMeta[] };
  return body.items;
}

// ── Matter (pivot-interface.md §Matter API) ────────────────────────────────

export type MatterStatus =
  | "planning" | "executing" | "paused" | "finished" | "cancelled" | "reviewed";

export type DocType = "think" | "act" | "verify" | "result" | "insight";

export type Judgement = "passed" | "failed" | "cancelled";

export type Outcome = "finished" | "cancelled";

export type StatusChange = { from: MatterStatus; to: MatterStatus };

export type Verification = {
  target: string;
  judgement: Judgement;
  comment: string;
};

export type TimelineComment = {
  author: string;
  created_at: string;
  body: string;
  mentions?: string[];
};

export type TimelineItem = {
  file: string;
  created_at: string;
  creator: string;
  owner: string;
  type: DocType;
  summary: string;
  quote: string | null;
  refer: string[];
  comments: TimelineComment[];
  status_change: StatusChange | null;
  expanded: boolean;
  body: string;
  verifications?: Verification[];
  outcome?: Outcome;
};

export type MatterSummary = {
  id: string;
  title: string;
  category: string | null;
  current_status: MatterStatus;
  created_at: string;
  updated_at: string;
  file_count: number;
  last_file_type: DocType | null;
  last_summary: string | null;
  unread_count: number;
  favorite: boolean;
};

export type MatterMeta = MatterSummary;

export type MatterDetail = {
  matter: MatterMeta;
  timeline: TimelineItem[];
};

export async function fetchMatters(query?: {
  status?: MatterStatus;
  owner?: string;
  q?: string;
}): Promise<MatterSummary[]> {
  const params = new URLSearchParams();
  if (query?.status) params.set("status", query.status);
  if (query?.owner) params.set("owner", query.owner);
  if (query?.q) params.set("q", query.q);
  const qs = params.toString() ? `?${params}` : "";
  const r = await fetch(`/api/matters${qs}`, { credentials: "include" });
  if (!r.ok) throw new Error(`/api/matters failed: ${r.status}`);
  const body = (await r.json()) as { items: MatterSummary[] };
  return body.items;
}

export async function fetchMatter(matterId: string): Promise<MatterDetail> {
  const r = await fetch(`/api/matters/${encodeURIComponent(matterId)}`, {
    credentials: "include",
  });
  if (r.status === 404) throw new Error("matter not found");
  if (!r.ok) throw new Error(`fetch matter failed: ${r.status}`);
  return (await r.json()) as MatterDetail;
}

export type InitialFileIn = {
  type: DocType;
  summary: string;
  body?: string;
  owner?: string | null;
  comments?: { body: string; mentions?: string[] }[];
};

export type NewMatterResponse = {
  matter: MatterMeta;
  initial_timeline_item: TimelineItem;
  matter_id: string;
  file: string;
};

export async function createMatter(body: {
  category: string;
  title: string;
  initial_file: InitialFileIn;
}): Promise<NewMatterResponse> {
  const r = await fetch("/api/matters", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    const detail = typeof d.detail === "string"
      ? d.detail
      : d.detail?.message || d.detail?.code || `create matter failed: ${r.status}`;
    throw new Error(detail);
  }
  return (await r.json()) as NewMatterResponse;
}

export type NewFileIn = {
  type: DocType;
  summary: string;
  body?: string;
  owner?: string | null;
  quote?: string | null;
  refer?: string[];
  comments?: { body: string; mentions?: string[] }[];
  verifications?: Verification[];
  outcome?: Outcome;
  status_change?: StatusChange;
};

export type AppendFileResponse = {
  item: TimelineItem;
  matter: MatterMeta;
};

export async function appendMatterFile(
  matterId: string,
  body: NewFileIn,
): Promise<AppendFileResponse> {
  const r = await fetch(
    `/api/matters/${encodeURIComponent(matterId)}/files`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    const detail = typeof d.detail === "string"
      ? d.detail
      : d.detail?.message || d.detail?.code || `append file failed: ${r.status}`;
    throw new Error(detail);
  }
  return (await r.json()) as AppendFileResponse;
}

export async function appendMatterResult(
  matterId: string,
  body: {
    summary: string;
    body?: string;
    outcome: Outcome;
    comments?: { body: string; mentions?: string[] }[];
  },
): Promise<AppendFileResponse> {
  const r = await fetch(
    `/api/matters/${encodeURIComponent(matterId)}/result`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    const detail = typeof d.detail === "string"
      ? d.detail
      : d.detail?.message || d.detail?.code || `append result failed: ${r.status}`;
    throw new Error(detail);
  }
  return (await r.json()) as AppendFileResponse;
}

export async function markMatterRead(matterId: string): Promise<void> {
  await fetch(
    `/api/matters/${encodeURIComponent(matterId)}/read`,
    { method: "POST", credentials: "include" },
  );
}

export async function setMatterFavorite(
  matterId: string,
  favorite: boolean,
): Promise<{ ok: true; thread_key: string; favorite: boolean }> {
  const r = await fetch(
    `/api/matters/${encodeURIComponent(matterId)}/favorite`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ favorite }),
    },
  );
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    const detail = typeof d.detail === "string"
      ? d.detail
      : d.detail?.message || d.detail?.code || `favorite failed: ${r.status}`;
    throw new Error(detail);
  }
  return await r.json();
}

export async function appendMatterComment(
  matterId: string,
  body: { target_file: string; body: string; mentions?: string[] },
): Promise<{ item: TimelineItem }> {
  const r = await fetch(
    `/api/matters/${encodeURIComponent(matterId)}/comments`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    const detail = typeof d.detail === "string"
      ? d.detail
      : d.detail?.message || d.detail?.code || `append comment failed: ${r.status}`;
    throw new Error(detail);
  }
  return (await r.json()) as { item: TimelineItem };
}

export type WorkspaceStatus = {
  ready: boolean;
  path: string;
  head: string | null;
};

export type ReleaseSummary = {
  version: string;
  date: string;
  title: string;
  body_md: string;
};

export type AppHomePayload = {
  app: {
    name: string;
    version: string;
    head: string | null;
  };
  welcome: {
    title: string;
    body_md: string;
  };
  latest_release: ReleaseSummary | null;
  recent_releases: ReleaseSummary[];
};

export type WorkspaceAdminConfig = {
  repo_url: string;
  visibility: "public" | "private" | "";
  write_token: string;
  readonly_token: string;
  branch: "main";
};

export type WorkspaceMirrorConfig = {
  repo_url: string;
  visibility: "public" | "private";
  branch: "main";
  repo_name: string;
  provider: string;
  readonly: true;
  git_username: string | null;
  git_token: string | null;
  head: string | null;
};

export async function fetchWorkspaceStatus(): Promise<WorkspaceStatus> {
  const r = await fetch("/api/workspace/status", { credentials: "include" });
  if (!r.ok) throw new Error(`/api/workspace/status failed: ${r.status}`);
  return (await r.json()) as WorkspaceStatus;
}

export async function fetchWorkspaceMirror(): Promise<WorkspaceMirrorConfig> {
  const r = await fetch("/api/workspace/mirror", { credentials: "include" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `/api/workspace/mirror failed: ${r.status}`);
  }
  return (await r.json()) as WorkspaceMirrorConfig;
}

export async function fetchAppHome(): Promise<AppHomePayload> {
  const r = await fetch("/api/app/home", { credentials: "include" });
  if (!r.ok) throw new Error(`/api/app/home failed: ${r.status}`);
  return (await r.json()) as AppHomePayload;
}

export type MentionEntry = {
  time: string | null;
  author_id: string | null;
  author_display: string | null;
  users: { user: string; open_id: string }[];
  comments: string | null;
};

export type Post = {
  filename: string;
  frontmatter: Record<string, unknown>;
  body: string;
  author_display: string | null;
  author_avatar_url: string | null;
  mentions: MentionEntry[];
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
  opts?: { reply_to?: string | null; references?: string[] },
): Promise<{ filename: string }> {
  const r = await fetch(
    `/api/threads/${encodeURIComponent(category)}/${encodeURIComponent(slug)}/posts`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        body,
        reply_to: opts?.reply_to ?? null,
        references: opts?.references ?? [],
      }),
    },
  );
  if (!r.ok) {
    const detail = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(detail.detail || `reply failed: ${r.status}`);
  }
  return await r.json();
}

export type MentionBlock = {
  open_ids: string[];
  comments: string;
};

export type Draft = {
  id: string;
  type: "proposal" | "reply";
  title: string | null;
  category: string | null;
  body_md: string;
  thread_key: string | null;
  mentions: MentionBlock | null;
  reply_to: string | null;
  references: string[];
  created_at: number;
  updated_at: number;
};

export type Contact = {
  open_id: string;
  name: string;
  en_name: string | null;
  avatar_url: string;
};

export async function searchContacts(q: string): Promise<Contact[]> {
  const r = await fetch(`/api/contacts?q=${encodeURIComponent(q)}&limit=20`, {
    credentials: "include",
  });
  if (!r.ok) throw new Error(`/api/contacts failed: ${r.status}`);
  const body = (await r.json()) as { items: Contact[] };
  return body.items;
}

export async function syncContacts(): Promise<{ ok: true; synced: number; total: number }> {
  const r = await adminFetch("/api/contacts/sync", { method: "POST" });
  const body = await r.json().catch(() => ({ detail: r.statusText }));
  if (!r.ok) throw new Error(body.detail || `sync failed: ${r.status}`);
  return body;
}

export async function fetchDrafts(): Promise<Draft[]> {
  const r = await fetch("/api/drafts", { credentials: "include" });
  if (!r.ok) throw new Error(`/api/drafts failed: ${r.status}`);
  const body = (await r.json()) as { items: Draft[] };
  return body.items;
}

export async function fetchDraft(id: string): Promise<Draft> {
  const r = await fetch(`/api/drafts/${id}`, { credentials: "include" });
  if (!r.ok) throw new Error(`fetch draft failed: ${r.status}`);
  return (await r.json()) as Draft;
}

export async function createDraft(body: {
  type: "proposal" | "reply";
  title?: string | null;
  category?: string | null;
  body_md?: string;
  thread_key?: string | null;
  reply_to?: string | null;
  references?: string[];
}): Promise<Draft> {
  const r = await fetch("/api/drafts", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `create draft failed: ${r.status}`);
  }
  return (await r.json()) as Draft;
}

export async function updateDraft(
  id: string,
  body: {
    title?: string | null;
    category?: string | null;
    body_md?: string;
    thread_key?: string | null;
    reply_to?: string | null;
    references?: string[];
  },
): Promise<Draft> {
  const r = await fetch(`/api/drafts/${id}`, {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `update draft failed: ${r.status}`);
  }
  return (await r.json()) as Draft;
}

export async function deleteDraft(id: string): Promise<void> {
  const r = await fetch(`/api/drafts/${id}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!r.ok) throw new Error(`delete draft failed: ${r.status}`);
}

export async function publishDraft(
  id: string,
): Promise<{ published: { category?: string; slug?: string; filename: string }; draft_id: string }> {
  const r = await fetch(`/api/drafts/${id}/publish`, {
    method: "POST",
    credentials: "include",
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `publish failed: ${r.status}`);
  }
  return await r.json();
}

export async function addMention(
  category: string,
  slug: string,
  target_filename: string,
  mentions: MentionBlock,
): Promise<{ ok: true }> {
  const r = await fetch(
    `/api/threads/${encodeURIComponent(category)}/${encodeURIComponent(slug)}/mentions`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_filename, mentions }),
    },
  );
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `mention failed: ${r.status}`);
  }
  return await r.json();
}

export async function changeThreadStatus(
  category: string, slug: string, to: string, reason?: string,
): Promise<{ ok: true; from: string; to: string }> {
  const r = await fetch(
    `/api/threads/${encodeURIComponent(category)}/${encodeURIComponent(slug)}/status`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ to, reason }),
    },
  );
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `status change failed: ${r.status}`);
  }
  return await r.json();
}

export async function setThreadFavorite(
  category: string,
  slug: string,
  favorite: boolean,
): Promise<{ ok: true; thread_key: string; favorite: boolean }> {
  const r = await fetch(
    `/api/threads/${encodeURIComponent(category)}/${encodeURIComponent(slug)}/favorite`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ favorite }),
    },
  );
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `favorite failed: ${r.status}`);
  }
  return await r.json();
}

export async function markThreadRead(category: string, slug: string): Promise<void> {
  await fetch(
    `/api/threads/${encodeURIComponent(category)}/${encodeURIComponent(slug)}/read`,
    { method: "POST", credentials: "include" },
  );
}

// ── AI ──────────────────────────────────────────────────────────────────────

export type AISettings = {
  base_url: string;
  model: string;
  has_key: boolean;
  max_context_tokens: number;
  min_rounds: number;
  max_rounds: number;
};

// Admin password is held in sessionStorage (cleared on browser close)
const ADMIN_PW_KEY = "admin_password";
export const ADMIN_PW_HEADER = "X-Admin-Password";

export function getAdminPassword(): string | null {
  return sessionStorage.getItem(ADMIN_PW_KEY);
}

export function setAdminPassword(pw: string): void {
  sessionStorage.setItem(ADMIN_PW_KEY, pw);
}

export function clearAdminPassword(): void {
  sessionStorage.removeItem(ADMIN_PW_KEY);
}

function adminHeaders(): Record<string, string> {
  const pw = getAdminPassword();
  return pw ? { [ADMIN_PW_HEADER]: pw } : {};
}

export class AdminRequiredError extends Error {
  constructor() { super("admin_required"); this.name = "AdminRequiredError"; }
}

async function adminFetch(url: string, init?: RequestInit): Promise<Response> {
  const r = await fetch(url, {
    ...init,
    credentials: "include",
    headers: { ...(init?.headers || {}), ...adminHeaders() },
  });
  if (r.status === 401) {
    const body = await r.clone().json().catch(() => ({}));
    if (body.detail === "admin_required") {
      clearAdminPassword();
      throw new AdminRequiredError();
    }
  }
  return r;
}

export async function fetchAISettings(): Promise<AISettings> {
  const r = await adminFetch("/api/ai/settings");
  if (!r.ok) throw new Error(`/api/ai/settings failed: ${r.status}`);
  return (await r.json()) as AISettings;
}

export async function updateAISettings(body: {
  api_key?: string;
  base_url?: string;
  model?: string;
  max_context_tokens?: number;
  min_rounds?: number;
  max_rounds?: number;
}): Promise<void> {
  const r = await adminFetch("/api/ai/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `update ai settings failed: ${r.status}`);
  }
}

export async function fetchWorkspaceAdminConfig(): Promise<WorkspaceAdminConfig> {
  const r = await adminFetch("/api/admin/workspace-config");
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `/api/admin/workspace-config failed: ${r.status}`);
  }
  return (await r.json()) as WorkspaceAdminConfig;
}

export async function updateWorkspaceAdminConfig(body: {
  repo_url: string;
  visibility: "public" | "private";
  write_token: string;
  readonly_token: string;
}): Promise<void> {
  const r = await adminFetch("/api/admin/workspace-config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `update workspace config failed: ${r.status}`);
  }
}

export type ChatMessage = { role: "user" | "assistant"; content: string };

export type AIConversation = {
  messages: ChatMessage[];
  reply_target: string | null;
  reference_files: string[];
};

export async function fetchAIConversation(
  category: string,
  slug: string,
): Promise<AIConversation> {
  const r = await fetch(
    `/api/ai/threads/${encodeURIComponent(category)}/${encodeURIComponent(slug)}/conversation`,
    { credentials: "include" },
  );
  if (!r.ok) throw new Error(`fetch conversation failed: ${r.status}`);
  return (await r.json()) as AIConversation;
}

export async function saveAIConversation(
  category: string,
  slug: string,
  messages: ChatMessage[],
  reply_target: string | null,
  reference_files: string[],
): Promise<void> {
  const r = await fetch(
    `/api/ai/threads/${encodeURIComponent(category)}/${encodeURIComponent(slug)}/conversation`,
    {
      method: "PUT",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages, reply_target, reference_files }),
    },
  );
  if (!r.ok) throw new Error(`save conversation failed: ${r.status}`);
}

export async function clearAIConversation(
  category: string,
  slug: string,
): Promise<void> {
  await fetch(
    `/api/ai/threads/${encodeURIComponent(category)}/${encodeURIComponent(slug)}/conversation`,
    { method: "DELETE", credentials: "include" },
  );
}

export type AIFileEntry = {
  path: string;
  filename: string;
  type: string;
  author: string;
  created: string;
};

export type AIThreadFiles = {
  category: string;
  slug: string;
  title: string;
  files: AIFileEntry[];
};

export async function fetchAIFiles(): Promise<AIThreadFiles[]> {
  const r = await fetch("/api/ai/files", { credentials: "include" });
  if (!r.ok) throw new Error(`/api/ai/files failed: ${r.status}`);
  const body = (await r.json()) as { items: AIThreadFiles[] };
  return body.items;
}

/**
 * Streams AI chat deltas. Yields string chunks. Throws on error.
 * Usage: for await (const chunk of streamAIChat(...)) { ... }
 */
export async function* streamAIChat(
  category: string,
  slug: string,
  messages: ChatMessage[],
  reply_target: string | null,
  reference_files: string[],
  signal?: AbortSignal,
): AsyncGenerator<string> {
  const resp = await fetch(
    `/api/ai/threads/${encodeURIComponent(category)}/${encodeURIComponent(slug)}/chat`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages, reply_target, reference_files }),
      signal,
    },
  );
  if (!resp.ok) {
    const d = await resp.json().catch(() => ({ detail: resp.statusText }));
    const detail = Array.isArray(d.detail)
      ? d.detail
        .map((item: unknown) => {
          if (typeof item === "string") return item;
          if (item && typeof item === "object") {
            const record = item as { loc?: unknown; msg?: unknown };
            const loc = Array.isArray(record.loc) ? record.loc.join(".") : "";
            const msg = typeof record.msg === "string" ? record.msg : JSON.stringify(item);
            return loc ? `${loc}: ${msg}` : msg;
          }
          return String(item);
        })
        .join("; ")
      : d.detail;
    throw new Error(detail || `AI chat failed: ${resp.status}`);
  }
  const reader = resp.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const data = line.slice(6);
      if (data === "[DONE]") return;
      try {
        const msg = JSON.parse(data) as { delta?: string; error?: string };
        if (msg.error) throw new Error(msg.error);
        if (msg.delta) yield msg.delta;
      } catch (e) {
        if (e instanceof Error && e.message !== "") throw e;
      }
    }
  }
}

// ── Workspace ────────────────────────────────────────────────────────────────

export async function refreshWorkspace(): Promise<WorkspaceStatus> {
  const r = await fetch("/api/workspace/refresh", {
    method: "POST",
    credentials: "include",
  });
  if (!r.ok) throw new Error(`/api/workspace/refresh failed: ${r.status}`);
  const body = (await r.json()) as { ok: boolean; head: string | null };
  return { ready: true, path: "", head: body.head };
}

// ── API Tokens (Personal Access Tokens) ─────────────────────────────────────

export type ApiTokenSummary = {
  id: string;
  name: string;
  created_at: number;
  last_used_at: number | null;
  expires_at: number;
};

export type ApiTokenCreated = ApiTokenSummary & { token: string };

export async function fetchApiTokens(): Promise<ApiTokenSummary[]> {
  const r = await fetch("/api/tokens", { credentials: "include" });
  if (!r.ok) throw new Error(`/api/tokens failed: ${r.status}`);
  const body = (await r.json()) as { items: ApiTokenSummary[] };
  return body.items;
}

export async function createApiToken(
  name: string,
  ttl_days = 90,
): Promise<ApiTokenCreated> {
  const r = await fetch("/api/tokens", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, ttl_days }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `create token failed: ${r.status}`);
  }
  return (await r.json()) as ApiTokenCreated;
}

export async function deleteApiToken(id: string): Promise<void> {
  const r = await fetch(`/api/tokens/${id}`, { method: "DELETE", credentials: "include" });
  if (!r.ok) throw new Error(`delete token failed: ${r.status}`);
}
