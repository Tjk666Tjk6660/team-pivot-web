export type Me = {
  id: string;
  open_id: string;
  name: string;
  display_name: string;
  email: string | null;
  avatar_url: string;
  pinyin: string | null;
  github_username: string | null;
  markdown_style: string | null;
  needs_setup: boolean;
  role: string;
  roles: string[];
  status: "active" | "suspended" | "deleted";
  /** 当前用户绑定的外部身份 provider 列表（'feishu' / 'invite' / ...）。
   *  前端用它决定是否显示 provider-specific 的 admin 动作，例如
   *  "联系人同步"只对绑了飞书的 admin 可见。 */
  providers: string[];
};

export class SessionExpiredError extends Error {
  constructor() {
    super("登录已失效，正在跳转登录页。");
    this.name = "SessionExpiredError";
  }
}

let loginRedirectStarted = false;

const SESSION_DEAD_DETAILS = new Set([
  "invalid_token",
  "not logged in",
]);

const STATUS_REASON_DETAILS = new Set([
  "suspended",
  "deleted",
]);

function redirectToLogin(reason?: string): void {
  if (loginRedirectStarted || typeof window === "undefined") return;
  loginRedirectStarted = true;
  const current = window.location.href;
  const params = new URLSearchParams();
  // 只在不是从 /login 来 + 没有 reason 时才带 next，避免循环或覆盖 reason 的视觉。
  if (reason) {
    params.set("reason", reason);
  } else if (!window.location.pathname.startsWith("/login")) {
    params.set("next", current);
  }
  const qs = params.toString();
  window.location.assign(`/login${qs ? `?${qs}` : ""}`);
}

async function throwIfSessionExpired(resp: Response): Promise<void> {
  if (resp.status !== 401) return;
  const body = await resp.clone().json().catch(() => ({}));
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail !== "string") return;
  if (STATUS_REASON_DETAILS.has(detail)) {
    redirectToLogin(detail);
    throw new SessionExpiredError();
  }
  if (SESSION_DEAD_DETAILS.has(detail)) {
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

export type AuthorView = {
  user_id: string;
  open_id: string;
  display_name: string;
  avatar_url: string | null;
  status: "active" | "suspended" | "deleted" | "unknown";
};

export type TimelineMention = {
  author: string;
  author_display?: string;
  author_view?: AuthorView | null;
  created_at: string;
  body: string;
  targets?: string[];
  targets_display?: string[];
  targets_view?: (AuthorView | null)[];
  // True when the current user is one of the mention's targets AND has not
  // marked the host file as read (via POST /matters/{id}/files/{f}/read).
  // Detail interface populates this; missing for old backends or for users
  // not in the targets list. Field name is intentionally preserved across
  // the comments → mentions rename (design §3.5) — renaming would touch
  // the entire frontend without behavior change.
  mention_unread_for_me?: boolean;
};

// File-level relevance reasons. Mention-level @-targets are tracked
// separately via TimelineMention.mention_unread_for_me, not by this enum.
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
  view?: AuthorView | null;
  first_read_at: string;
};

export type TimelineFileItem = {
  file: string;
  created_at: string;
  creator: string;
  owner: string;
  owner_display?: string | null;
  owner_avatar_url?: string | null;
  owner_view?: AuthorView | null;
  creator_display?: string | null;
  creator_avatar_url?: string | null;
  creator_view?: AuthorView | null;
  type: DocType;
  summary: string;
  quote: string | null;
  refer: string[];
  mentions: TimelineMention[];
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

export type TimelineOwnerChangeItem = {
  type: "owner_change";
  created_at: string;
  actor: string;
  actor_display: string | null;
  actor_avatar_url: string | null;
  actor_view?: AuthorView | null;
  from_owner: string | null;
  from_owner_display: string | null;
  from_owner_avatar_url: string | null;
  from_owner_view?: AuthorView | null;
  to_owner: string;
  to_owner_display: string | null;
  to_owner_avatar_url: string | null;
  to_owner_view?: AuthorView | null;
  reason: string;
  status_change: StatusChange | null;
  readers_count?: number;
  readers?: Reader[];
};

export type TimelineItem = TimelineFileItem | TimelineOwnerChangeItem;

export function isTimelineFileItem(item: TimelineItem): item is TimelineFileItem {
  return item.type !== "owner_change";
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
  owner_view?: AuthorView | null;
  creator?: string | null;
  creator_display?: string | null;
  creator_avatar_url?: string | null;
  creator_view?: AuthorView | null;
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

export type VisibilityScope = {
  mode: "public" | "restricted";
  roles: string[];
  user_ids: string[];
};

export type CategoryVisibilityScope = {
  mode: "public" | "restricted";
  authorized_roles: string[];
};

export type VisibilityUserOption = {
  id: string;
  display_name: string;
  pinyin: string | null;
  avatar_url: string | null;
};

export type VisibilityRoleOption = {
  role: string;
  name: string;
  label?: string;
  users: VisibilityUserOption[];
};

export type VisibilityOptions = {
  all: { label: string; value: "public" };
  roles: VisibilityRoleOption[];
  users: VisibilityUserOption[];
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

export async function fetchVisibilityOptions(
  category?: string,
): Promise<VisibilityOptions> {
  const params = new URLSearchParams();
  if (category) params.set("category", category);
  const qs = params.toString() ? `?${params}` : "";
  const r = await fetch(`/api/visibility-options${qs}`, { credentials: "include" });
  await throwIfSessionExpired(r);
  if (!r.ok) throw new Error(`fetch visibility options failed: ${r.status}`);
  return (await r.json()) as VisibilityOptions;
}

export async function fetchMatterVisibility(
  matterId: string,
): Promise<VisibilityScope> {
  const r = await fetch(
    `/api/matters/${encodeURIComponent(matterId)}/visibility`,
    { credentials: "include" },
  );
  await throwIfSessionExpired(r);
  if (r.status === 404) throw new Error("matter not found");
  if (!r.ok) throw new Error(`fetch matter visibility failed: ${r.status}`);
  const body = (await r.json()) as { visibility: VisibilityScope };
  return body.visibility;
}

export async function updateMatterVisibility(
  matterId: string,
  visibility: VisibilityScope,
): Promise<VisibilityScope> {
  const r = await fetch(
    `/api/matters/${encodeURIComponent(matterId)}/visibility`,
    {
      method: "PUT",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(visibility),
    },
  );
  await throwIfSessionExpired(r);
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    const code = typeof d.detail === "object" ? d.detail?.code : undefined;
    if (code === "visibility_scope_exceeds_category") {
      throw new Error("可见范围不能超过所属分类");
    }
    if (r.status === 403) throw new Error("你没有权限修改这个讨论的可见范围");
    if (r.status === 404) throw new Error("matter not found");
    const detail = typeof d.detail === "string"
      ? d.detail
      : d.detail?.message || d.detail?.code || `update visibility failed: ${r.status}`;
    throw new Error(detail);
  }
  const body = (await r.json()) as { visibility: VisibilityScope };
  return body.visibility;
}

export type InitialFileIn = {
  type: DocType;
  summary: string;
  body?: string;
  owner?: string | null;
  mentions?: { body: string; targets?: string[] }[];
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
  visibility?: VisibilityScope;
  new_category_visibility?: CategoryVisibilityScope;
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

export type AdminRoleOption = {
  role: string;
  name: string;
  label?: string;
  kind: "system" | "business";
  description: string | null;
  is_active: boolean;
  user_count: number;
  created_at: number;
  updated_at: number;
};

type AdminRoleErrorDetail =
  | string
  | {
    code?: string;
    message?: string;
    unknown_roles?: string[];
    suggestions?: string[];
  };

function adminRoleErrorMessage(detail: AdminRoleErrorDetail | undefined, status: number): string {
  const code = typeof detail === "object" ? detail?.code : detail;
  const message = typeof detail === "object" ? detail?.message : undefined;
  switch (code) {
    case "role already exists":
      return "这个角色已经存在";
    case "role cannot be empty":
    case "role_required":
      return "请输入角色名称";
    case "role is too long":
      return "角色名称不能超过 40 个字符";
    case "role contains control characters":
      return "角色名称不能包含换行、制表符等控制字符";
    case "invalid role kind":
      return "角色类型不正确";
    case "role_not_found":
      return "角色不存在或已被删除，请刷新后重试";
    case "system_role_protected":
      return "系统角色不能停用";
    case "last_active_admin_protected":
      return "至少需要保留一个可用的 admin";
    case "unknown_role": {
      const unknown = typeof detail === "object" ? detail.unknown_roles ?? [] : [];
      const suggestions = typeof detail === "object" ? detail.suggestions ?? [] : [];
      const suffix = suggestions.length ? `，可选：${suggestions.join("、")}` : "";
      return unknown.length
        ? `角色 ${unknown.join("、")} 还不存在${suffix}`
        : `角色还不存在${suffix}`;
    }
    default:
      break;
  }
  if (status === 403) return "你没有权限操作角色";
  if (status === 404) return "角色不存在或已被删除，请刷新后重试";
  if (status === 409) return "这个角色已经存在";
  if (status === 422) return message || "角色信息不符合要求，请检查后重试";
  return message || code || `角色操作失败：${status}`;
}

export async function listAdminRoles(): Promise<AdminRoleOption[]> {
  const r = await fetch("/api/admin/roles", { credentials: "include" });
  await throwIfSessionExpired(r);
  if (!r.ok) throw new Error(`fetch roles failed: ${r.status}`);
  const body = (await r.json()) as { items: AdminRoleOption[] };
  return body.items;
}

export async function changeUserRoles(
  userId: string,
  roles: string[],
  confirmCreateRole = false,
): Promise<void> {
  const r = await fetch(`/api/admin/users/${encodeURIComponent(userId)}/role`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ roles, confirm_create_role: confirmCreateRole }),
  });
  await throwIfSessionExpired(r);
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    const code = typeof d.detail === "object" ? d.detail?.code : undefined;
    if (code === "unknown_role") {
      throw new Error(adminRoleErrorMessage(d.detail, r.status));
    }
    const detail = typeof d.detail === "string"
      ? d.detail
      : d.detail?.message || d.detail?.code || `change user roles failed: ${r.status}`;
    throw new Error(detail);
  }
}

export async function createAdminRole(
  name: string,
  description?: string,
): Promise<AdminRoleOption> {
  const r = await fetch("/api/admin/roles", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, description }),
  });
  await throwIfSessionExpired(r);
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(adminRoleErrorMessage(d.detail, r.status));
  }
  return r.json();
}

export async function setAdminRoleMembers(
  role: string,
  userIds: string[],
): Promise<{ role: AdminRoleOption; members: AdminUser[] }> {
  const r = await fetch(`/api/admin/roles/${encodeURIComponent(role)}/members`, {
    method: "PUT",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_ids: userIds }),
  });
  await throwIfSessionExpired(r);
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(adminRoleErrorMessage(d.detail, r.status));
  }
  return r.json();
}

export type NewFileIn = {
  type: DocType;
  summary: string;
  body?: string;
  owner?: string | null;
  quote?: string | null;
  refer?: string[];
  mentions?: { body: string; targets?: string[] }[];
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

export async function appendMatterResult(
  matterId: string,
  body: {
    summary: string;
    body?: string;
    outcome: Outcome;
    mentions?: { body: string; targets?: string[] }[];
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

export async function appendMatterMention(
  matterId: string,
  body: { target_file: string; body: string; targets?: string[] },
): Promise<{ item: TimelineItem }> {
  const r = await fetch(
    `/api/matters/${encodeURIComponent(matterId)}/mentions`,
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
      : d.detail?.message || d.detail?.code || `append mention failed: ${r.status}`;
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

export type PivotUserOption = {
  id: string;
  display_name: string;
  pinyin: string | null;
  avatar_url: string;
};

export async function searchPivotUsers(q: string): Promise<PivotUserOption[]> {
  const r = await fetch(`/api/users/search?q=${encodeURIComponent(q)}&limit=20`, {
    credentials: "include",
  });
  await throwIfSessionExpired(r);
  if (!r.ok) throw new Error(`/api/users/search failed: ${r.status}`);
  const body = (await r.json()) as { items: PivotUserOption[] };
  return body.items;
}

export async function searchContacts(q: string): Promise<Contact[]> {
  const r = await fetch(`/api/contacts?q=${encodeURIComponent(q)}&limit=20`, {
    credentials: "include",
  });
  await throwIfSessionExpired(r);
  if (!r.ok) throw new Error(`/api/contacts failed: ${r.status}`);
  const body = (await r.json()) as { items: Contact[] };
  return body.items;
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

/** Thrown by adminFetch when the server returns admin_required (401/403).
 *  Callers (admin sections in AdminPage.tsx) catch this to surface a toast
 *  prompting the admin to refresh / re-login. */
export class AdminRequiredError extends Error {
  constructor() { super("admin_required"); this.name = "AdminRequiredError"; }
}

async function adminFetch(url: string, init?: RequestInit): Promise<Response> {
  const r = await fetch(url, {
    ...init,
    credentials: "include",
    headers: { ...(init?.headers || {}) },
  });
  if (r.status === 401 || r.status === 403) {
    const body = await r.clone().json().catch(() => ({}));
    if (body.detail === "admin_required") {
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

export type DailyReportConfig = {
  enabled: boolean;
  company_enabled: boolean;
  personal_enabled: boolean;
  time_window_hours: number;
  push_time: string;                // "HH:MM" Asia/Shanghai
  push_freq: "daily" | "weekdays";  // 默认 weekdays(仅周一到周五)
};

export type DailyReportLastRun = {
  run_id: string | null;
  started_at: string | null;
  finished_at: string | null;
  rc: number | null;
  debug: Record<string, unknown> | null;
  error: string | null;
};

export async function fetchDailyReportConfig(): Promise<DailyReportConfig> {
  const r = await adminFetch("/api/admin/daily-report/config");
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `/api/admin/daily-report/config failed: ${r.status}`);
  }
  return (await r.json()) as DailyReportConfig;
}

export async function updateDailyReportConfig(body: DailyReportConfig): Promise<void> {
  const r = await adminFetch("/api/admin/daily-report/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `update daily-report config failed: ${r.status}`);
  }
}

export async function triggerDailyReport(body: {
  dry_run: boolean;
  no_ai: boolean;
}): Promise<{ ok: boolean; run_id: string; started_at: string }> {
  const r = await adminFetch("/api/admin/daily-report/trigger", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `trigger daily-report failed: ${r.status}`);
  }
  return r.json();
}

export async function fetchDailyReportLastRun(): Promise<DailyReportLastRun> {
  const r = await adminFetch("/api/admin/daily-report/last-run");
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `last-run failed: ${r.status}`);
  }
  return (await r.json()) as DailyReportLastRun;
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

// 方案 B 错误归一化：所有 AI 失败都会归到这一份 detail，前端用 code 决定走哪个
// 兜底 UI（auth → 提示联系管理员；retryable=true → 给"重试"按钮；其余仅气泡）。
export type AIErrorDetail = {
  code: string;
  retryable: boolean;
  message: string;
  status: number | null;
};

/** Thrown by `streamAIChat` when the backend emits an `error` event. The
 * `.detail` carries the structured payload so callers can render branded
 * retry UI without parsing message strings. Falls back to `Error` semantics
 * when the backend only sent a legacy `error: <string>` field (older 部署). */
export class AIChatError extends Error {
  constructor(public readonly detail: AIErrorDetail) {
    super(detail.message);
    this.name = "AIChatError";
  }
}

export type AIStreamEvent =
  | { kind: "delta"; delta: string }
  | { kind: "tool_start"; id: string; name: string; arguments: Record<string, unknown> }
  | {
      kind: "tool_end";
      id: string;
      name: string;
      output_summary: { size: number; head: string };
    }
  // 方案 B：服务端在上游静默 ≥ heartbeat_interval_s 时下发；前端据此把 AIPane
  // 切到"AI 响应较慢…" 状态。since_last_token_ms 是上游连续静默时长。
  | { kind: "heartbeat"; since_last_token_ms: number };

/**
 * Streams AI chat events. Yields structured events (text deltas, tool_call
 * lifecycle, and heartbeats). Throws on error — preferring `AIChatError`
 * with structured `detail`; falls back to plain `Error` on older backends.
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
    if (resp.status === 401 && typeof d.detail === "string") {
      if (STATUS_REASON_DETAILS.has(d.detail)) {
        redirectToLogin(d.detail);
        throw new SessionExpiredError();
      }
      if (SESSION_DEAD_DETAILS.has(d.detail)) {
        redirectToLogin();
        throw new SessionExpiredError();
      }
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
          // 方案 B：服务端结构化错误。旧后端仍只下发 `error: <string>`，新后端
          // 同时下发 `error_detail: {...}`；都向后兼容。
          error_detail?: Partial<AIErrorDetail>;
          heartbeat?: { since_last_token_ms?: number };
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
        if (msg.error) {
          const detail: AIErrorDetail = {
            code: msg.error_detail?.code ?? "unknown",
            retryable: msg.error_detail?.retryable ?? true,
            message: msg.error_detail?.message ?? msg.error,
            status: msg.error_detail?.status ?? null,
          };
          throw new AIChatError(detail);
        }
        if (msg.delta) yield { kind: "delta", delta: msg.delta };
        if (msg.heartbeat) {
          yield {
            kind: "heartbeat",
            since_last_token_ms: msg.heartbeat.since_last_token_ms ?? 0,
          };
        }
        if (msg.tool_call_start)
          yield { kind: "tool_start", ...msg.tool_call_start };
        if (msg.tool_call_end) yield { kind: "tool_end", ...msg.tool_call_end };
      } catch (e) {
        if (e instanceof AIChatError) throw e;
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

// ── User management (Tasks 12-18) ─────────────────────────────────────────

async function jsonGet<T>(path: string): Promise<T> {
  const r = await fetch(path, { credentials: "include" });
  await throwIfSessionExpired(r);
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `${path} failed: ${r.status}`);
  }
  return (await r.json()) as T;
}

async function jsonPost<T = unknown>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  await throwIfSessionExpired(r);
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `${path} failed: ${r.status}`);
  }
  return (await r.json()) as T;
}

async function jsonDelete<T = unknown>(path: string): Promise<T> {
  const r = await fetch(path, { method: "DELETE", credentials: "include" });
  await throwIfSessionExpired(r);
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `${path} failed: ${r.status}`);
  }
  return (await r.json()) as T;
}

export type InitStatus = { needs_init: boolean };

export async function getInitStatus(): Promise<InitStatus> {
  return jsonGet<InitStatus>("/api/init/status");
}

export type InitCompleteBody = {
  method: "email_password";
  email: string;
  password: string;
  display_name: string;
  pinyin: string;
};

export async function postInitComplete(body: InitCompleteBody) {
  return jsonPost("/api/init/complete", body);
}

export async function postEmailPasswordLogin(body: { email: string; password: string }) {
  return jsonPost("/auth/login_email_password", body);
}

export type InvitePreview = {
  email: string;
  display_name: string | null;
  expires_at: number;
};

export async function getInvite(token: string): Promise<InvitePreview> {
  return jsonGet<InvitePreview>(`/api/invite/${encodeURIComponent(token)}`);
}

export async function postInviteAccept(
  token: string,
  body: { password: string; display_name: string; pinyin: string },
) {
  return jsonPost(`/api/invite/${encodeURIComponent(token)}/accept`, body);
}

// ── Admin: applications ───────────────────────────────────────────────────

export type ApplicationMergedInto = {
  user_id: string;
  display_name: string;
  email: string | null;
  avatar_url: string;
  /** true 表示是合并到了已有 pivot_user；false 表示当时是新建账号 */
  merged: boolean;
};

export type Application = {
  id: string;
  provider: string;
  external_id: string;
  external_union_id: string | null;
  raw_profile: Record<string, unknown>;
  suggested_match_user_id: string | null;
  status: "pending" | "approved" | "rejected";
  applied_at: number;
  reviewed_at: number | null;
  reviewed_by: string | null;
  reject_reason: string | null;
  /** approved 状态下展示"目标 pivot_user"信息；其它状态为 null */
  merged_into: ApplicationMergedInto | null;
};

export type MatchCandidate = {
  user_id: string;
  display_name: string;
  email: string | null;
  avatar_url: string;
  reason: "email_exact" | "name_exact" | "pinyin_full" | "pinyin_initials";
};

export async function listApplications(
  status?: "pending" | "approved" | "rejected",
): Promise<{ items: Application[] }> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  return jsonGet(`/api/admin/applications${qs}`);
}

export async function getMatchCandidates(
  applicationId: string,
): Promise<{ candidates: MatchCandidate[] }> {
  return jsonGet(
    `/api/admin/applications/${encodeURIComponent(applicationId)}/match-candidates`,
  );
}

export async function approveApplication(
  id: string, target_pivot_user_id?: string,
): Promise<{ approved: true; user_id: string; merged: boolean }> {
  return jsonPost(
    `/api/admin/applications/${encodeURIComponent(id)}/approve`,
    { target_pivot_user_id },
  );
}

export async function rejectApplication(
  id: string, reason?: string,
): Promise<{ rejected: true }> {
  return jsonPost(
    `/api/admin/applications/${encodeURIComponent(id)}/reject`,
    { reason },
  );
}

export async function unblockApplication(
  id: string,
): Promise<{ unblocked: true }> {
  return jsonPost(
    `/api/admin/applications/${encodeURIComponent(id)}/unblock`, {},
  );
}

// ── Admin: users ──────────────────────────────────────────────────────────

export type ExternalBindingView = {
  id: string;
  provider: string;            // 'feishu' | 'invite' | ...
  external_id: string;         // feishu open_id / invite email / etc.
  external_union_id: string | null;
  bound_at: number;
  raw_profile: Record<string, unknown> | null;
};

export type AdminUser = {
  id: string;
  display_name: string;
  pinyin: string | null;
  email: string | null;
  avatar_url: string;
  role: string;
  roles: string[];
  status: "active" | "suspended" | "deleted";
  status_note: string | null;
  created_at: number;
  last_login_at: number | null;
  status_changed_at: number | null;
  /** Legacy 字段：仅 provider 名列表（保留一段过渡期，下游 UI 应迁到 bindings） */
  providers: string[];
  /** 详细 binding 列表 — 多条同 provider 的条目代表合并过的多份身份 */
  bindings: ExternalBindingView[];
};

export async function listAdminUsers(opts?: {
  include_deleted?: boolean;
  search?: string;
}): Promise<{ items: AdminUser[] }> {
  const q = new URLSearchParams();
  if (opts?.include_deleted) q.set("include_deleted", "true");
  if (opts?.search) q.set("search", opts.search);
  const qs = q.toString();
  return jsonGet(`/api/admin/users${qs ? `?${qs}` : ""}`);
}

export async function suspendUser(id: string, note?: string): Promise<AdminUser> {
  return jsonPost(`/api/admin/users/${encodeURIComponent(id)}/suspend`, { note });
}

export async function resumeUser(id: string, note?: string): Promise<AdminUser> {
  return jsonPost(`/api/admin/users/${encodeURIComponent(id)}/resume`, { note });
}

export async function markUserDeleted(
  id: string, confirm_display_name: string, note?: string,
): Promise<AdminUser> {
  return jsonPost(
    `/api/admin/users/${encodeURIComponent(id)}/mark-deleted`,
    { note, confirm_display_name },
  );
}

export async function restoreUser(
  id: string, confirm_display_name: string, note?: string,
): Promise<AdminUser> {
  return jsonPost(
    `/api/admin/users/${encodeURIComponent(id)}/restore`,
    { note, confirm_display_name },
  );
}

export async function resetUserPassword(
  id: string, new_password: string,
): Promise<{ reset: true }> {
  return jsonPost(
    `/api/admin/users/${encodeURIComponent(id)}/reset-password`,
    { new_password },
  );
}

// ── Admin: invites ────────────────────────────────────────────────────────

export type AdminInvite = {
  id: string;
  email: string;
  display_name: string | null;
  created_by: string;
  created_at: number;
  expires_at: number;
  used_at: number | null;
};

export type CreatedInvite = AdminInvite & {
  token: string; // plaintext, returned exactly once
  link_path: string; // /invite/<token>
};

export async function listInvites(
  include_used = false,
): Promise<{ items: AdminInvite[] }> {
  const qs = include_used ? "?include_used=true" : "";
  return jsonGet(`/api/admin/invites${qs}`);
}

export async function createInvite(
  email: string, display_name?: string, ttl_days = 7,
): Promise<CreatedInvite> {
  return jsonPost(`/api/admin/invites`, { email, display_name, ttl_days });
}

export async function revokeInvite(id: string): Promise<{ revoked: true }> {
  return jsonDelete(`/api/admin/invites/${encodeURIComponent(id)}`);
}

// ─────────────────────────────────────────────────────────────────────────────
// Scoring (admin only — uses session cookie + role check via adminFetch)
// ─────────────────────────────────────────────────────────────────────────────

export type ScoringConfig = {
  enabled: boolean;
  visibility: "admin_only" | "subjects" | "all";
  model: string;
  timeout_seconds: number;
};

export type ScoringRunSummary = {
  run_id: string;
  matter_id: string;
  matter_title: string | null;
  matter_category: string;
  subject_user_id: string;
  subject_display: string | null;
  subject_avatar_url: string | null;
  subject_status: string | null;
  triggered_by: string;
  triggered_actor_id: string | null;
  status: "queued" | "running" | "success" | "failed" | "skipped";
  error: string | null;
  model: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  started_at: number;
  finished_at: number | null;
  timeline_hash: string;
  score: {
    overall: number;
    confidence: string;
    /** 人工修正后的总分。null = 未修正过；非 null = 列表视图应显示这个值
     *  并加 ✏ 标记，hover 提示 AI 原始分。 */
    override_overall: number | null;
  } | null;
};

export type ScoringRunsList = {
  items: ScoringRunSummary[];
  total: number;
  has_more: boolean;
};

export type ScoringDimensions = {
  delivery: number | null;
  accountability: number | null;
  collaboration: number | null;
  judgment: number | null;
  process: number | null;
};

export type ScoringEvidenceItem = {
  id: number;
  dimension: keyof ScoringDimensions;
  polarity: "positive" | "negative" | "neutral";
  confidence: "low" | "medium" | "high";
  source_kind: "file" | "comment";
  source_filename: string;
  source_file_type: string;
  source_comment_created_at: string | null;
  source_comment_author_id: string | null;
  source_comment_author_display: string | null;
  weight_applied: number;
  quote: string;
  explanation: string;
};

export type ScoringRunDetail = {
  run: ScoringRunSummary;
  score: {
    run_id: string;
    subject_user_id: string;
    matter_id: string;
    overall: number;
    confidence: string;
    rationale: string;
    dimensions: ScoringDimensions;
    human_override:
      | { overall: number | null; note: string | null; by: string | null; at: number | null }
      | null;
  } | null;
  evidence: ScoringEvidenceItem[];
};

export type CommenterWeight = {
  pivot_user_id: string;
  weight: number;
  label: string;
  note: string | null;
  updated_at: number;
  updated_by: string;
  user_display: string | null;
  user_avatar_url: string | null;
  user_pinyin: string | null;
  user_status: string | null;
};

export type ScoringUserSearchHit = {
  pivot_user_id: string;
  display_name: string;
  pinyin: string | null;
  email: string | null;
  avatar_url: string;
  role: string;
};

export async function fetchScoringConfig(): Promise<ScoringConfig> {
  const r = await adminFetch("/api/admin/scoring/config");
  if (!r.ok) throw new Error(`/api/admin/scoring/config failed: ${r.status}`);
  return (await r.json()) as ScoringConfig;
}

export async function updateScoringConfig(body: ScoringConfig): Promise<void> {
  const r = await adminFetch("/api/admin/scoring/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `update scoring config failed: ${r.status}`);
  }
}

export async function fetchScoringRuns(params: {
  status?: string;
  /** Exact matter_id match — use matter_query for substring search instead. */
  matter_id?: string;
  /** Substring match against matter_id (LIKE). */
  matter_query?: string;
  limit?: number;
  offset?: number;
} = {}): Promise<ScoringRunsList> {
  const qs = new URLSearchParams();
  if (params.status) qs.set("status", params.status);
  if (params.matter_id) qs.set("matter_id", params.matter_id);
  if (params.matter_query) qs.set("matter_query", params.matter_query);
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  if (params.offset !== undefined) qs.set("offset", String(params.offset));
  const url = `/api/admin/scoring/runs${qs.toString() ? `?${qs}` : ""}`;
  const r = await adminFetch(url);
  if (!r.ok) throw new Error(`/api/admin/scoring/runs failed: ${r.status}`);
  return (await r.json()) as ScoringRunsList;
}

export async function fetchScoringRunDetail(runId: string): Promise<ScoringRunDetail> {
  const r = await adminFetch(`/api/admin/scoring/runs/${encodeURIComponent(runId)}`);
  if (!r.ok) throw new Error(`/api/admin/scoring/runs/${runId} failed: ${r.status}`);
  return (await r.json()) as ScoringRunDetail;
}

export async function triggerScoringRerun(matterId: string): Promise<{
  ok: boolean;
  matter_id: string;
  queued: boolean;
  message: string;
}> {
  const r = await adminFetch(
    `/api/admin/scoring/matters/${encodeURIComponent(matterId)}/rerun`,
    { method: "POST" },
  );
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    const detail = typeof d.detail === "string" ? d.detail : d.detail?.message || JSON.stringify(d.detail);
    throw new Error(detail || `rerun failed: ${r.status}`);
  }
  return r.json();
}

export async function listCommenterWeights(): Promise<{ items: CommenterWeight[] }> {
  const r = await adminFetch("/api/admin/scoring/commenter-weights");
  if (!r.ok) throw new Error(`/api/admin/scoring/commenter-weights failed: ${r.status}`);
  return (await r.json()) as { items: CommenterWeight[] };
}

export async function upsertCommenterWeight(body: {
  pivot_user_id: string;
  weight: number;
  label: string;
  note?: string | null;
}): Promise<CommenterWeight> {
  const r = await adminFetch("/api/admin/scoring/commenter-weights", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    const detail = typeof d.detail === "string" ? d.detail : d.detail?.message || JSON.stringify(d.detail);
    throw new Error(detail || `upsert weight failed: ${r.status}`);
  }
  return (await r.json()) as CommenterWeight;
}

export async function updateCommenterWeight(
  userId: string,
  body: { weight?: number; label?: string; note?: string | null },
): Promise<CommenterWeight> {
  const r = await adminFetch(
    `/api/admin/scoring/commenter-weights/${encodeURIComponent(userId)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `update weight failed: ${r.status}`);
  }
  return (await r.json()) as CommenterWeight;
}

export async function deleteCommenterWeight(userId: string): Promise<void> {
  const r = await adminFetch(
    `/api/admin/scoring/commenter-weights/${encodeURIComponent(userId)}`,
    { method: "DELETE" },
  );
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `delete weight failed: ${r.status}`);
  }
}

export async function searchScoringUsers(q: string): Promise<{
  items: ScoringUserSearchHit[];
}> {
  const url = `/api/admin/scoring/users-search?q=${encodeURIComponent(q)}`;
  const r = await adminFetch(url);
  if (!r.ok) throw new Error(`search users failed: ${r.status}`);
  return (await r.json()) as { items: ScoringUserSearchHit[] };
}

export type ScoringScorePayload = NonNullable<ScoringRunDetail["score"]>;

export async function overrideScoringScore(
  runId: string,
  body: { overall: number; note: string },
): Promise<ScoringScorePayload> {
  const r = await adminFetch(
    `/api/admin/scoring/scores/${encodeURIComponent(runId)}/override`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    const detail = typeof d.detail === "string" ? d.detail : d.detail?.message || JSON.stringify(d.detail);
    throw new Error(detail || `override score failed: ${r.status}`);
  }
  return (await r.json()) as ScoringScorePayload;
}
