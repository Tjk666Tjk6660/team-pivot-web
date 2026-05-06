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
  | "in_my_matter"
  | "in_my_owned_matter";

export type Reader = {
  open_id: string;
  name: string;
  avatar_url: string | null;
  first_read_at: string;
};

export type TimelineFileItem = {
  file: string;
  created_at: string;
  creator: string;
  owner: string;
  owner_display?: string | null;
  owner_avatar_url?: string | null;
  creator_display?: string | null;
  creator_avatar_url?: string | null;
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
  // Invalidation reverse-write fields (P1). All four come together; missing
  // means the file was never invalidated. After a restore, `invalidated`
  // flips back to false but the other three persist as audit trail.
  // See AI-docs/invalidate-self/product-design.md §2.1.
  invalidated?: boolean;
  invalidated_at?: string;
  invalidated_reason?: InvalidationReason;
  invalidated_by?: string;
};

export type InvalidationReason = "misposted" | "inaccurate" | "restored";

export type TimelineInvalidationEventItem = {
  // No `type` field — distinguished from file items by absence of `type`,
  // and from owner_change events by presence of `reason` ∈ InvalidationReason.
  // See AI-docs/invalidate-self/product-design.md §2.2.
  created_at: string;
  creator: string;
  creator_display: string | null;
  creator_avatar_url: string | null;
  quote: string;       // target file path
  reason: InvalidationReason;
  summary?: string;
  readers_count?: number;
  readers?: Reader[];
};

export type TimelineOwnerChangeItem = {
  type: "owner_change";
  created_at: string;
  actor: string;
  actor_display: string | null;
  actor_avatar_url: string | null;
  from_owner: string | null;
  from_owner_display: string | null;
  from_owner_avatar_url: string | null;
  to_owner: string;
  to_owner_display: string | null;
  to_owner_avatar_url: string | null;
  reason: string;
  status_change: StatusChange | null;
  readers_count?: number;
  readers?: Reader[];
};

export type TimelineItem =
  | TimelineFileItem
  | TimelineOwnerChangeItem
  | TimelineInvalidationEventItem;

export function isTimelineFileItem(item: TimelineItem): item is TimelineFileItem {
  // File items carry a `type` field in the file-type whitelist. Owner_change
  // also has `type` but equals "owner_change". Invalidation events have no
  // `type` field at all (per design §2.2).
  return "type" in item && item.type !== "owner_change";
}

export function isTimelineOwnerChangeItem(
  item: TimelineItem,
): item is TimelineOwnerChangeItem {
  return "type" in item && item.type === "owner_change";
}

export function isTimelineInvalidationEventItem(
  item: TimelineItem,
): item is TimelineInvalidationEventItem {
  return !("type" in item);
}

export type MatterSummary = {
  id: string;
  title: string;
  category: string | null;
  current_status: MatterStatus;
  created_at: string;
  updated_at: string;
  // Derived sort key: max(updated_at, latest comment.created_at). Comments
  // do not bump matter.updated_at (per pivot-product.md), so the list
  // would otherwise miss matters that just got a new @-mention. Optional
  // for back-compat with older backends — fall back to updated_at.
  last_activity_at?: string;
  file_count: number;
  last_file_type: DocType | null;
  last_summary: string | null;
  owner: string | null;
  owner_display: string | null;
  owner_avatar_url: string | null;
  creator?: string | null;
  creator_display?: string | null;
  creator_avatar_url?: string | null;
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
  owner_open_id?: string;
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
  item: TimelineFileItem;
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

export type TransferMatterOwnerResponse = {
  matter: MatterMeta;
  item: TimelineOwnerChangeItem;
};

type ApiErrorDetail = string | { code?: string; message?: string };

function transferMatterOwnerErrorMessage(
  detail: ApiErrorDetail | undefined,
  status: number,
): string {
  const code = typeof detail === "object" ? detail?.code : undefined;
  const message = typeof detail === "string" ? detail : detail?.message;
  switch (code) {
    case "owner_unchanged":
      return "新负责人不能与当前负责人相同";
    case "to_owner_required":
      return "请选择新负责人";
    case "owner_unknown":
      return "找不到这个负责人，请重新选择";
    case "reason_required":
      return "请填写转交原因";
    case "owner_stale":
      return "负责人已被其他人更新，请刷新后重试";
    case "status_stale":
      return "状态已被其他人更新，请刷新后重试";
    case "status_change_not_allowed_by_event":
      return "当前状态不支持随转交一起推进";
    default:
      break;
  }
  if (message?.includes("to_owner equals from_owner")) {
    return "新负责人不能与当前负责人相同";
  }
  return message || `转交负责人失败：${status}`;
}

export async function transferMatterOwner(
  matterId: string,
  body: {
    to_owner: string;
    reason: string;
    status_change?: StatusChange | null;
  },
): Promise<TransferMatterOwnerResponse> {
  const r = await fetch(
    `/api/matters/${encodeURIComponent(matterId)}/owner`,
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
    throw new Error(transferMatterOwnerErrorMessage(d.detail, r.status));
  }
  return (await r.json()) as TransferMatterOwnerResponse;
}

export type PostMatterEventResponse = {
  matter_id: string;
  matter: { id: string; title: string; current_status: MatterStatus };
  event: {
    creator: string;
    created_at: string;
    quote: string;
    reason: InvalidationReason;
    summary?: string;
  };
  target: {
    file: string;
    invalidated: boolean;
    invalidated_at: string | null;
    invalidated_reason: InvalidationReason | null;
    invalidated_by: string | null;
  } | null;
};

/** Invalidate or restore a file the current user authored.
 *
 * Per AI-docs/invalidate-self/product-design.md:
 *   - reason ∈ {misposted, inaccurate}: invalidate
 *   - reason === "restored": restore (only allowed on already-invalidated files)
 *
 * Server enforces author-only (creator must equal target file's creator)
 * and same-matter (quote must point to a file in this matter timeline).
 */
export async function postMatterEvent(
  matterId: string,
  body: {
    target_file: string;
    reason: InvalidationReason;
    summary?: string | null;
  },
): Promise<PostMatterEventResponse> {
  const r = await fetch(
    `/api/matters/${encodeURIComponent(matterId)}/events`,
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
    const detail = d.detail;
    const code =
      detail && typeof detail === "object" && "code" in detail
        ? (detail as { code?: string }).code
        : undefined;
    const message =
      (detail && typeof detail === "object" && "message" in detail
        ? (detail as { message?: string }).message
        : null) ||
      (typeof detail === "string" ? detail : null) ||
      r.statusText;
    throw new Error(code ? `${code}: ${message}` : String(message));
  }
  return (await r.json()) as PostMatterEventResponse;
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

export async function markMatterEventsRead(
  matterId: string,
): Promise<{ matter_id: string; cleared: number }> {
  const r = await fetch(
    `/api/matters/${encodeURIComponent(matterId)}/events/read`,
    { method: "POST", credentials: "include" },
  );
  if (!r.ok) {
    await throwIfSessionExpired(r);
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    const detail = typeof d.detail === "string"
      ? d.detail
      : d.detail?.message || d.detail?.code || `mark matter events read failed: ${r.status}`;
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

export async function fetchContactsByIds(open_ids: string[]): Promise<Contact[]> {
  if (open_ids.length === 0) return [];
  const ids = open_ids.join(",");
  const r = await fetch(`/api/contacts/by-ids?ids=${encodeURIComponent(ids)}`, {
    credentials: "include",
  });
  await throwIfSessionExpired(r);
  if (!r.ok) throw new Error(`/api/contacts/by-ids failed: ${r.status}`);
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

// ── Daily report admin (Phase 5) ─────────────────────────────────────────────

// ── Daily Report v2 (multi-job) ─────────────────────────────────────────────

export type DailyReportPushFreq =
  | "daily"
  | "weekdays"
  | "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun"
  | "month_start"
  | "month_end";

export type DailyReportJob = {
  id: number;
  name: string;
  view: "company" | "personal";
  status: "active" | "paused" | "archived";
  push_time: string;                          // "HH:MM"
  push_freq: DailyReportPushFreq;
  window_hours: number;
  channel: "feishu";
  receiver_type: "groups" | "users";
  receiver_ids: string[] | null;              // null = 默认全部 bot 群
  next_run_at: string | null;                 // ISO
  last_run_id: number | null;
  last_status: string | null;
  retry_count: number;
  last_notified_at: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
};

export type DailyReportRun = {
  id: number;
  job_id: number | null;                      // null = 手动触发
  trigger_type: "scheduled" | "manual" | "retry" | "makeup";
  view: string;
  started_at: string;
  finished_at: string | null;
  status: "running" | "succeeded" | "failed" | "partial" | "skipped";
  rc: number | null;
  cards_sent: number | null;
  cards_total: number | null;
  ai_tokens_in: number | null;
  ai_tokens_out: number | null;
  error: string | null;
};

export type DailyReportRunDetail = DailyReportRun & {
  debug_json: string | null;
};

export type DailyReportRunsPage = {
  items: DailyReportRun[];
  page: number;
  size: number;
  total: number;
};

export type AdminNotifyConfig = {
  chat_ids: string[];
  open_ids: string[];
};

export type FeishuChat = {
  chat_id: string;
  name: string;
  avatar: string | null;
};

export type DailyReportJobIn = {
  name: string;
  view: "company" | "personal";
  push_time: string;
  push_freq?: DailyReportPushFreq;
  window_hours?: number;
  receiver_type: "groups" | "users";
  receiver_ids?: string[] | null;
  status?: "active" | "paused";
};

export type DailyReportJobUpdate = Partial<{
  name: string;
  view: "company" | "personal";
  push_time: string;
  push_freq: DailyReportPushFreq;
  window_hours: number;
  receiver_type: "groups" | "users";
  receiver_ids: string[] | null;
}>;

const V2_BASE = "/api/admin/daily-report";

export async function fetchDailyReportJobs(
  includeArchived = false,
): Promise<DailyReportJob[]> {
  const url = `${V2_BASE}/jobs${includeArchived ? "?include_archived=true" : ""}`;
  const r = await adminFetch(url);
  if (!r.ok) throw new Error(`list jobs failed: ${r.status}`);
  return (await r.json()) as DailyReportJob[];
}

export async function createDailyReportJob(
  body: DailyReportJobIn,
): Promise<DailyReportJob> {
  const r = await adminFetch(`${V2_BASE}/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `create job failed: ${r.status}`);
  }
  return (await r.json()) as DailyReportJob;
}

export async function updateDailyReportJob(
  id: number,
  body: DailyReportJobUpdate,
): Promise<DailyReportJob> {
  const r = await adminFetch(`${V2_BASE}/jobs/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `update job failed: ${r.status}`);
  }
  return (await r.json()) as DailyReportJob;
}

export async function setDailyReportJobStatus(
  id: number,
  status: "active" | "paused" | "archived",
): Promise<DailyReportJob> {
  const r = await adminFetch(`${V2_BASE}/jobs/${id}/status`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `set status failed: ${r.status}`);
  }
  return (await r.json()) as DailyReportJob;
}

export async function deleteDailyReportJob(id: number): Promise<void> {
  const r = await adminFetch(`${V2_BASE}/jobs/${id}`, { method: "DELETE" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `delete job failed: ${r.status}`);
  }
}

export type DailyReportTriggerResponse = {
  ok: boolean;
  run_id: number;
  started_at: string;
};

export async function runDailyReportJobNow(
  id: number,
  body: { dry_run?: boolean; no_ai?: boolean } = {},
): Promise<DailyReportTriggerResponse> {
  const r = await adminFetch(`${V2_BASE}/jobs/${id}/run-now`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `run-now failed: ${r.status}`);
  }
  return (await r.json()) as DailyReportTriggerResponse;
}

export async function manualTriggerDailyReport(body: {
  view: "company" | "personal";
  // 模式 A:倒推窗口(默认)
  window_hours?: number;
  // 模式 B:显式时间区间(都给则覆盖 window_hours)。ISO8601 字符串
  since?: string;
  until?: string;
  receiver_type: "groups" | "users";
  receiver_ids?: string[] | null;
  dry_run?: boolean;
  no_ai?: boolean;
}): Promise<DailyReportTriggerResponse> {
  const r = await adminFetch(`${V2_BASE}/manual-trigger`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `manual-trigger failed: ${r.status}`);
  }
  return (await r.json()) as DailyReportTriggerResponse;
}

export async function fetchDailyReportRunsPage(
  jobId: number,
  page = 1,
  size = 20,
): Promise<DailyReportRunsPage> {
  const r = await adminFetch(
    `${V2_BASE}/jobs/${jobId}/runs?page=${page}&size=${size}`,
  );
  if (!r.ok) throw new Error(`runs page failed: ${r.status}`);
  return (await r.json()) as DailyReportRunsPage;
}

export async function fetchDailyReportRun(
  runId: number,
): Promise<DailyReportRunDetail> {
  const r = await adminFetch(`${V2_BASE}/runs/${runId}`);
  if (!r.ok) throw new Error(`get run failed: ${r.status}`);
  return (await r.json()) as DailyReportRunDetail;
}

export async function fetchAdminNotifyConfig(): Promise<AdminNotifyConfig> {
  const r = await adminFetch(`${V2_BASE}/admin-notify`);
  if (!r.ok) throw new Error(`admin-notify get failed: ${r.status}`);
  return (await r.json()) as AdminNotifyConfig;
}

export async function updateAdminNotifyConfig(
  body: AdminNotifyConfig,
): Promise<void> {
  const r = await adminFetch(`${V2_BASE}/admin-notify`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `admin-notify put failed: ${r.status}`);
  }
}

export async function fetchFeishuChats(): Promise<FeishuChat[]> {
  const r = await adminFetch(`${V2_BASE}/feishu-chats`);
  if (!r.ok) throw new Error(`feishu-chats failed: ${r.status}`);
  return (await r.json()) as FeishuChat[];
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
