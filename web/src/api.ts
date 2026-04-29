export type Me = {
  open_id: string;
  name: string;
  avatar_url: string;
  pinyin: string | null;
  github_username: string | null;
  markdown_style: string | null;
  needs_setup: boolean;
};

export class SessionExpiredError extends Error {
  constructor() {
    super("登录已失效，正在跳转登录页。");
    this.name = "SessionExpiredError";
  }
}

let loginRedirectStarted = false;

function isSessionExpiredDetail(detail: unknown): boolean {
  return detail === "invalid_token" || detail === "not logged in";
}

function redirectToLogin(): void {
  if (loginRedirectStarted || typeof window === "undefined") return;
  loginRedirectStarted = true;
  const current = window.location.href;
  const next = window.location.pathname.startsWith("/login")
    ? window.location.origin + "/"
    : current;
  window.location.assign(`/login?next=${encodeURIComponent(next)}`);
}

async function throwIfSessionExpired(resp: Response): Promise<void> {
  if (resp.status !== 401) return;
  const body = await resp.clone().json().catch(() => ({}));
  if (isSessionExpiredDetail((body as { detail?: unknown }).detail)) {
    redirectToLogin();
    throw new SessionExpiredError();
  }
}

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
    await throwIfSessionExpired(r);
    const detail = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(detail.detail || `/me/profile failed: ${r.status}`);
  }
  return (await r.json()) as Me;
}

export async function logout(): Promise<void> {
  await fetch("/logout", { method: "POST", credentials: "include" });
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
  author_display?: string;
  created_at: string;
  body: string;
  mentions?: string[];
  mentions_display?: string[];
  // True when the current user is mentioned in this comment AND has not
  // marked the host file as read (via POST /matters/{id}/files/{f}/read).
  // Detail interface populates this; missing for old backends or for users
  // not in the mentions list.
  mention_unread_for_me?: boolean;
};

// File-level relevance reasons. Comment-level @ mentions are tracked
// separately via TimelineComment.mention_unread_for_me, not by this enum.
export type FileRelevanceReason =
  | "owner_assigned"
  | "reply_to_my_file"
  | "reply_to_my_owned"
  | "verify_my_file"
  | "in_my_matter";

export type Reader = {
  open_id: string;
  name: string;
  avatar_url: string | null;
  first_read_at: string;
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
  readers_count?: number;
  readers?: Reader[];
  // File-level relevance reason for the current user. null / missing means
  // not relevant. Populated by detail interface from relevance_events table.
  relevance_reason?: FileRelevanceReason | null;
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
  // Red = unread items that are relevant to the current user; gray = the rest
  // of unread_count. Together they sum to unread_count (red + gray ===
  // unread_count). Both fields are optional for backwards compatibility — old
  // backends only return unread_count.
  red_unread_count?: number;
  gray_unread_count?: number;
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
  await throwIfSessionExpired(r);
  if (!r.ok) throw new Error(`/api/matters failed: ${r.status}`);
  const body = (await r.json()) as { items: MatterSummary[] };
  return body.items;
}

export async function fetchMatter(matterId: string): Promise<MatterDetail> {
  const r = await fetch(`/api/matters/${encodeURIComponent(matterId)}`, {
    credentials: "include",
  });
  await throwIfSessionExpired(r);
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
  body_source?: "ai" | "manual";
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
    await throwIfSessionExpired(r);
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
  body_source?: "ai" | "manual";
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
    await throwIfSessionExpired(r);
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
    await throwIfSessionExpired(r);
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

export async function markFileRead(
  matterId: string,
  filename: string,
): Promise<{ matter_id: string; filename: string; first_read_at: string }> {
  const r = await fetch(
    `/api/matters/${encodeURIComponent(matterId)}/files/${encodeURIComponent(filename)}/read`,
    { method: "POST", credentials: "include" },
  );
  if (!r.ok) {
    await throwIfSessionExpired(r);
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    const detail = typeof d.detail === "string"
      ? d.detail
      : d.detail?.message || d.detail?.code || `mark file read failed: ${r.status}`;
    throw new Error(detail);
  }
  return await r.json();
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
    await throwIfSessionExpired(r);
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
    await throwIfSessionExpired(r);
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
  await throwIfSessionExpired(r);
  if (!r.ok) throw new Error(`/api/workspace/status failed: ${r.status}`);
  return (await r.json()) as WorkspaceStatus;
}

export async function fetchWorkspaceMirror(): Promise<WorkspaceMirrorConfig> {
  const r = await fetch("/api/workspace/mirror", { credentials: "include" });
  if (!r.ok) {
    await throwIfSessionExpired(r);
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `/api/workspace/mirror failed: ${r.status}`);
  }
  return (await r.json()) as WorkspaceMirrorConfig;
}

export async function fetchAppHome(): Promise<AppHomePayload> {
  const r = await fetch("/api/app/home", { credentials: "include" });
  await throwIfSessionExpired(r);
  if (!r.ok) throw new Error(`/api/app/home failed: ${r.status}`);
  return (await r.json()) as AppHomePayload;
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
  matter_payload: Record<string, unknown> | null;
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
  await throwIfSessionExpired(r);
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
  await throwIfSessionExpired(r);
  if (!r.ok) throw new Error(`/api/drafts failed: ${r.status}`);
  const body = (await r.json()) as { items: Draft[] };
  return body.items;
}

export async function fetchDraft(id: string): Promise<Draft> {
  const r = await fetch(`/api/drafts/${id}`, { credentials: "include" });
  await throwIfSessionExpired(r);
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
  matter_payload?: Record<string, unknown> | null;
}): Promise<Draft> {
  const r = await fetch("/api/drafts", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    await throwIfSessionExpired(r);
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
    matter_payload?: Record<string, unknown> | null;
  },
): Promise<Draft> {
  const r = await fetch(`/api/drafts/${id}`, {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    await throwIfSessionExpired(r);
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
  await throwIfSessionExpired(r);
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
    await throwIfSessionExpired(r);
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `publish failed: ${r.status}`);
  }
  return await r.json();
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
  await throwIfSessionExpired(r);
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

export type MarkdownStyleMeta = {
  id: string;
  label: string;
  description: string;
  tone: "light" | "dark";
};

export type MarkdownStylesPayload = {
  styles: MarkdownStyleMeta[];
  system_default_style: string | null;
  user_style: string | null;
  effective_style: string;
  builtin_default_style: string;
};

export type AdminMarkdownSettings = {
  styles: MarkdownStyleMeta[];
  system_default_style: string | null;
  effective_system_default_style: string;
};

export async function fetchMarkdownStyles(): Promise<MarkdownStylesPayload> {
  const r = await fetch("/api/markdown/styles", { credentials: "include" });
  await throwIfSessionExpired(r);
  if (!r.ok) throw new Error(`/api/markdown/styles failed: ${r.status}`);
  return (await r.json()) as MarkdownStylesPayload;
}

export async function updateMyMarkdownStyle(style: string): Promise<{
  user_style: string;
  effective_style: string;
}> {
  const r = await fetch("/api/me/markdown-style", {
    method: "PUT",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ style }),
  });
  if (!r.ok) {
    await throwIfSessionExpired(r);
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `update markdown style failed: ${r.status}`);
  }
  return (await r.json()) as { user_style: string; effective_style: string };
}

// ── Per-user preferences (generic KV; keys are server-whitelisted) ──────────
//
// Currently used keys:
//   - "matter_list_filter": "all" | "mine"
//
// The server enforces a key whitelist on PUT — sending an unknown key returns
// 400. fetchPreferences returns the full bag (keys absent from the user's
// row simply won't appear in the dict).

export type UserPreferences = Record<string, string>;

export async function fetchPreferences(): Promise<UserPreferences> {
  const r = await fetch("/api/me/preferences", { credentials: "include" });
  await throwIfSessionExpired(r);
  if (!r.ok) throw new Error(`/api/me/preferences failed: ${r.status}`);
  return (await r.json()) as UserPreferences;
}

export async function setPreference(
  key: string,
  value: string,
): Promise<{ key: string; value: string }> {
  const r = await fetch(`/api/me/preferences/${encodeURIComponent(key)}`, {
    method: "PUT",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  });
  if (!r.ok) {
    await throwIfSessionExpired(r);
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `set preference failed: ${r.status}`);
  }
  return (await r.json()) as { key: string; value: string };
}

export async function fetchAdminMarkdownSettings(): Promise<AdminMarkdownSettings> {
  const r = await adminFetch("/api/admin/markdown-settings");
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `/api/admin/markdown-settings failed: ${r.status}`);
  }
  return (await r.json()) as AdminMarkdownSettings;
}

export async function updateAdminMarkdownSettings(body: {
  system_default_style: string;
}): Promise<void> {
  const r = await adminFetch("/api/admin/markdown-settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `update markdown settings failed: ${r.status}`);
  }
}

export type ChatMessage = { role: "user" | "assistant"; content: string };

export type AIToolUse = {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  output_summary?: { size: number; head: string };
};

export type AIConversation = {
  messages: ChatMessage[];
  reply_target: string | null;
};

export async function fetchAIConversation(
  matter_id: string,
): Promise<AIConversation> {
  const r = await fetch(
    `/api/ai/matters/${encodeURIComponent(matter_id)}/conversation`,
    { credentials: "include" },
  );
  await throwIfSessionExpired(r);
  if (!r.ok) throw new Error(`fetch conversation failed: ${r.status}`);
  return (await r.json()) as AIConversation;
}

export async function saveAIConversation(
  matter_id: string,
  messages: ChatMessage[],
  reply_target: string | null,
): Promise<void> {
  const r = await fetch(
    `/api/ai/matters/${encodeURIComponent(matter_id)}/conversation`,
    {
      method: "PUT",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages, reply_target }),
    },
  );
  await throwIfSessionExpired(r);
  if (!r.ok) throw new Error(`save conversation failed: ${r.status}`);
}

export async function clearAIConversation(matter_id: string): Promise<void> {
  await fetch(
    `/api/ai/matters/${encodeURIComponent(matter_id)}/conversation`,
    { method: "DELETE", credentials: "include" },
  );
}

export type AIStreamEvent =
  | { kind: "delta"; delta: string }
  | { kind: "tool_start"; id: string; name: string; arguments: Record<string, unknown> }
  | {
      kind: "tool_end";
      id: string;
      name: string;
      output_summary: { size: number; head: string };
    };

/**
 * Streams AI chat events. Yields structured events (text deltas and
 * tool_call lifecycle). Throws on error.
 * Usage: for await (const ev of streamAIChat(...)) { ... }
 */
export async function* streamAIChat(
  matter_id: string,
  messages: ChatMessage[],
  reply_target: string | null,
  signal?: AbortSignal,
  mode: "reply" | "new-matter" = "reply",
): AsyncGenerator<AIStreamEvent> {
  const resp = await fetch(
    `/api/ai/matters/${encodeURIComponent(matter_id)}/chat`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages, reply_target, mode }),
      signal,
    },
  );
  if (!resp.ok) {
    const d = await resp.json().catch(() => ({ detail: resp.statusText }));
    if (resp.status === 401 && isSessionExpiredDetail(d.detail)) {
      redirectToLogin();
      throw new SessionExpiredError();
    }
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
        const msg = JSON.parse(data) as {
          delta?: string;
          error?: string;
          tool_call_start?: {
            id: string;
            name: string;
            arguments: Record<string, unknown>;
          };
          tool_call_end?: {
            id: string;
            name: string;
            output_summary: { size: number; head: string };
          };
        };
        if (msg.error) throw new Error(msg.error);
        if (msg.delta) yield { kind: "delta", delta: msg.delta };
        if (msg.tool_call_start)
          yield { kind: "tool_start", ...msg.tool_call_start };
        if (msg.tool_call_end) yield { kind: "tool_end", ...msg.tool_call_end };
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
  await throwIfSessionExpired(r);
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
  await throwIfSessionExpired(r);
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
    await throwIfSessionExpired(r);
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `create token failed: ${r.status}`);
  }
  return (await r.json()) as ApiTokenCreated;
}

export async function deleteApiToken(id: string): Promise<void> {
  const r = await fetch(`/api/tokens/${id}`, { method: "DELETE", credentials: "include" });
  await throwIfSessionExpired(r);
  if (!r.ok) throw new Error(`delete token failed: ${r.status}`);
}
