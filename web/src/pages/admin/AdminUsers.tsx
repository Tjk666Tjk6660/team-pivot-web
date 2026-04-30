import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import {
  changeUserRole,
  fetchMe,
  listAdminUsers,
  markUserDeleted,
  resetUserPassword,
  restoreUser,
  resumeUser,
  suspendUser,
  type AdminUser,
  type Me,
} from "@/api";
import { UserStatusBadge } from "@/components/admin/UserStatusBadge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function AdminUsers() {
  const [items, setItems] = useState<AdminUser[]>([]);
  const [me, setMe] = useState<Me | null>(null);
  const [search, setSearch] = useState("");
  const [includeDeleted, setIncludeDeleted] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await listAdminUsers({
        include_deleted: includeDeleted,
        search: search.trim() || undefined,
      });
      setItems(r.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [includeDeleted, search]);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    fetchMe().then(setMe).catch(() => setMe(null));
  }, []);

  return (
    <div className="mx-auto max-w-5xl p-6">
      <header className="mb-5 flex flex-wrap items-center gap-3">
        <Link
          to="/admin"
          className="inline-flex items-center gap-1 text-[12.5px] font-meta hover:text-[var(--text)]"
          style={{ color: "var(--text-mute)" }}
        >
          <ArrowLeft className="h-3.5 w-3.5" /> 返回
        </Link>
        <h1 className="m-0 text-[22px]" style={titleStyle}>
          用户管理
        </h1>
        <div className="flex flex-1 items-center gap-3 justify-end">
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索 display_name / email / pinyin"
            className="h-9 w-64 text-[13px]"
          />
          <label
            className="flex items-center gap-1.5 text-[12.5px] font-meta"
            style={{ color: "var(--text-mute)" }}
          >
            <input
              type="checkbox"
              checked={includeDeleted}
              onChange={(e) => setIncludeDeleted(e.target.checked)}
            />
            含已停用
          </label>
        </div>
      </header>

      {loading && <p style={mutedStyle}>加载中…</p>}
      {error && (
        <p className="text-[13px]" style={{ color: "var(--danger-500)" }}>
          {error}
        </p>
      )}
      {!loading && !error && items.length === 0 && (
        <p style={mutedStyle}>没有匹配的用户。</p>
      )}

      <ul className="flex flex-col gap-2">
        {items.map((u) => (
          <UserRow key={u.id} user={u} me={me} onChanged={reload} />
        ))}
      </ul>
    </div>
  );
}

function UserRow({
  user,
  me,
  onChanged,
}: {
  user: AdminUser;
  me: Me | null;
  onChanged: () => void;
}) {
  const isSelf = me?.id === user.id;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmKind, setConfirmKind] =
    useState<"delete" | "restore" | "reset" | null>(null);

  const guard = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <li
      className="rounded-[var(--r-md)] p-3.5"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--line)",
        opacity: user.status === "deleted" ? 0.6 : 1,
      }}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          {user.avatar_url ? (
            <img
              src={user.avatar_url}
              alt=""
              className="h-9 w-9 shrink-0 rounded-full object-cover"
            />
          ) : (
            <div
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[12px] font-semibold uppercase"
              style={{ background: "var(--accent-bg)", color: "var(--accent)" }}
            >
              {(user.display_name || "?").slice(0, 1)}
            </div>
          )}
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span
                className="truncate text-[14px] font-semibold"
                style={{ color: "var(--text)" }}
              >
                {user.display_name}
              </span>
              <UserStatusBadge status={user.status} />
              {user.role === "admin" && (
                <span
                  className="rounded-full px-2 py-0.5 text-[10.5px] font-bold tracking-wider font-meta"
                  style={{
                    background: "var(--accent-bg)",
                    color: "var(--accent)",
                    border: "1px solid var(--accent)",
                  }}
                >
                  ADMIN
                </span>
              )}
              {isSelf && (
                <span
                  className="text-[10.5px] font-meta"
                  style={{ color: "var(--text-mute)" }}
                >
                  （这是你）
                </span>
              )}
            </div>
            <div className="mt-0.5 truncate text-[12px] font-meta" style={mutedStyle}>
              {user.email || "无邮箱"}
              {user.last_login_at && (
                <> · 上次登录 {new Date(user.last_login_at * 1000).toLocaleString()}</>
              )}
            </div>
            <BindingChips bindings={user.bindings} />
            {user.status_note && (
              <div
                className="mt-0.5 truncate text-[12px]"
                style={{ color: "var(--text-soft)" }}
              >
                备注：{user.status_note}
              </div>
            )}
          </div>
        </div>

        <div className="flex shrink-0 flex-wrap justify-end gap-1.5">
          {user.status === "active" && (
            <Button
              variant="ghost"
              size="sm"
              disabled={busy || isSelf}
              onClick={() => guard(async () => {
                await suspendUser(user.id);
              })}
              title={isSelf ? "不能对自己执行该操作" : undefined}
            >
              暂停
            </Button>
          )}
          {user.status === "suspended" && (
            <Button
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => guard(async () => {
                await resumeUser(user.id);
              })}
            >
              恢复
            </Button>
          )}
          {user.status !== "deleted" && (
            <Button
              variant="ghost"
              size="sm"
              disabled={busy || isSelf}
              onClick={() => setConfirmKind("delete")}
              style={{ color: "var(--danger-500)" }}
              title={isSelf ? "不能对自己执行该操作" : undefined}
            >
              停用
            </Button>
          )}
          {user.status === "deleted" && (
            <Button
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => setConfirmKind("restore")}
            >
              撤销停用
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            disabled={busy || isSelf || user.status !== "active"}
            onClick={() => guard(async () => {
              const next = user.role === "admin" ? "member" : "admin";
              await changeUserRole(user.id, next);
            })}
            title={
              isSelf
                ? "不能改自己的角色"
                : user.status !== "active"
                  ? "仅活跃用户可改角色"
                  : undefined
            }
          >
            {user.role === "admin" ? "降为 member" : "升为 admin"}
          </Button>
          {user.providers.includes("invite") && (
            <Button
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => setConfirmKind("reset")}
            >
              重置密码
            </Button>
          )}
        </div>
      </div>
      {error && (
        <p className="mt-2 text-[12px]" style={{ color: "var(--danger-500)" }}>
          {error}
        </p>
      )}

      <ConfirmDeleteDialog
        open={confirmKind === "delete"}
        user={user}
        onClose={() => setConfirmKind(null)}
        onConfirm={(note) =>
          guard(async () => {
            await markUserDeleted(user.id, user.display_name, note);
            setConfirmKind(null);
          })
        }
      />
      <ConfirmRestoreDialog
        open={confirmKind === "restore"}
        user={user}
        onClose={() => setConfirmKind(null)}
        onConfirm={(note) =>
          guard(async () => {
            await restoreUser(user.id, user.display_name, note);
            setConfirmKind(null);
          })
        }
      />
      <ResetPasswordDialog
        open={confirmKind === "reset"}
        user={user}
        onClose={() => setConfirmKind(null)}
        onConfirm={(pw) =>
          guard(async () => {
            await resetUserPassword(user.id, pw);
            setConfirmKind(null);
          })
        }
      />
    </li>
  );
}

function ConfirmDeleteDialog({
  open,
  user,
  onClose,
  onConfirm,
}: {
  open: boolean;
  user: AdminUser;
  onClose: () => void;
  onConfirm: (note: string | undefined) => void;
}) {
  const [confirmText, setConfirmText] = useState("");
  const [note, setNote] = useState("");
  useEffect(() => {
    if (!open) {
      setConfirmText("");
      setNote("");
    }
  }, [open]);
  const enabled = confirmText === user.display_name;
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>停用用户</DialogTitle>
          <DialogDescription>
            停用后该用户不能再登录或被 @ 提及；历史 git 内容仍保留，
            渲染时会显示为灰色。请输入用户的 display_name 确认操作。
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <div>
            <Label className="text-[12.5px]">输入 "{user.display_name}" 以确认</Label>
            <Input
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              autoFocus
            />
          </div>
          <div>
            <Label className="text-[12.5px]">备注（可选）</Label>
            <Input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="例如：离职"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button
            disabled={!enabled}
            onClick={() => onConfirm(note.trim() || undefined)}
            style={{
              background: "var(--danger-500)",
              color: "white",
              border: "1px solid var(--danger-500)",
            }}
          >
            确认停用
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ConfirmRestoreDialog({
  open,
  user,
  onClose,
  onConfirm,
}: {
  open: boolean;
  user: AdminUser;
  onClose: () => void;
  onConfirm: (note: string | undefined) => void;
}) {
  const [confirmText, setConfirmText] = useState("");
  useEffect(() => {
    if (!open) setConfirmText("");
  }, [open]);
  const enabled = confirmText === user.display_name;
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>撤销停用</DialogTitle>
          <DialogDescription>
            撤销后该用户可以再次登录。请输入用户的 display_name 确认。
          </DialogDescription>
        </DialogHeader>
        <Label className="text-[12.5px]">输入 "{user.display_name}" 以确认</Label>
        <Input
          value={confirmText}
          onChange={(e) => setConfirmText(e.target.value)}
          autoFocus
        />
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button
            disabled={!enabled}
            onClick={() => onConfirm(undefined)}
            style={{
              background: "var(--accent)",
              color: "var(--accent-ink)",
              border: "1px solid var(--accent)",
            }}
          >
            撤销停用
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ResetPasswordDialog({
  open,
  user,
  onClose,
  onConfirm,
}: {
  open: boolean;
  user: AdminUser;
  onClose: () => void;
  onConfirm: (newPassword: string) => void;
}) {
  const [pw, setPw] = useState("");
  useEffect(() => {
    if (!open) setPw("");
  }, [open]);
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>重置密码</DialogTitle>
          <DialogDescription>
            为 {user.display_name} 设置新密码（≥ 6 位）。重置后请告知用户新密码。
          </DialogDescription>
        </DialogHeader>
        <Input
          type="text"
          value={pw}
          onChange={(e) => setPw(e.target.value)}
          placeholder="新密码"
          autoFocus
        />
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button
            disabled={pw.length < 6}
            onClick={() => onConfirm(pw)}
            style={{
              background: "var(--accent)",
              color: "var(--accent-ink)",
              border: "1px solid var(--accent)",
            }}
          >
            重置
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function BindingChips({ bindings }: { bindings: AdminUser["bindings"] }) {
  if (bindings.length === 0) {
    return (
      <div
        className="mt-1 text-[11.5px] font-meta italic"
        style={{ color: "var(--text-mute)" }}
      >
        无身份绑定
      </div>
    );
  }
  // Single binding → 紧凑一行 chip 即可（最常见情况，不占空间）。
  if (bindings.length === 1) {
    return (
      <div className="mt-1.5">
        <BindingChip binding={bindings[0]} />
      </div>
    );
  }
  // Multi binding → 此 pivot_user 合并过 / 双登录方式。展开详情列表，
  // 每条一行带 名字 / 邮箱 / external_id / 绑定时间，admin 一眼能看清
  // 这个账号是合并自哪些原始身份。第一条按时间最早，是"主身份"，后续是
  // "合并自"。
  const sorted = [...bindings].sort((a, b) => a.bound_at - b.bound_at);
  return (
    <div
      className="mt-2 rounded-[var(--r-sm)]"
      style={{
        background: "var(--surface-alt)",
        border: "1px solid var(--line)",
      }}
    >
      <div
        className="flex items-center gap-2 px-2.5 py-1.5"
        style={{ borderBottom: "1px solid var(--line)" }}
      >
        <span
          className="text-[10.5px] font-bold uppercase tracking-[0.18em] font-meta"
          style={{ color: "var(--accent)" }}
        >
          合并身份
        </span>
        <span
          className="text-[11px] font-meta"
          style={{ color: "var(--text-mute)" }}
        >
          {bindings.length} 条外部身份合并到此账号
        </span>
      </div>
      <ul className="divide-y" style={{ borderColor: "var(--line)" }}>
        {sorted.map((b, i) => (
          <BindingDetailRow key={b.id} binding={b} primary={i === 0} />
        ))}
      </ul>
    </div>
  );
}

function BindingChip({
  binding,
}: {
  binding: AdminUser["bindings"][number];
}) {
  const rawName = _readBindingName(binding);
  const provider = binding.provider;
  const externalShort =
    binding.external_id.length > 14
      ? binding.external_id.slice(0, 12) + "…"
      : binding.external_id;
  const label =
    provider === "feishu"
      ? rawName ?? externalShort
      : provider === "invite"
        ? binding.external_id
        : externalShort;
  const tag =
    provider === "feishu" ? "飞书" : provider === "invite" ? "邮箱" : provider;
  const tooltip = [
    `provider=${provider}`,
    `external_id=${binding.external_id}`,
    binding.external_union_id ? `union_id=${binding.external_union_id}` : null,
    rawName ? `name=${rawName}` : null,
    `bound_at=${new Date(binding.bound_at * 1000).toLocaleString()}`,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-meta"
      style={{
        background: "var(--surface-alt)",
        border: "1px solid var(--line)",
        color: "var(--text-soft)",
      }}
      title={tooltip}
    >
      <span
        className="font-bold tracking-wider"
        style={{ color: "var(--text-mute)" }}
      >
        {tag}
      </span>
      <span style={{ color: "var(--text)" }}>{label}</span>
    </span>
  );
}

function BindingDetailRow({
  binding,
  primary,
}: {
  binding: AdminUser["bindings"][number];
  primary: boolean;
}) {
  const rawName = _readBindingName(binding);
  const rawEmail = _readBindingEmail(binding);
  const provider = binding.provider;
  const tag =
    provider === "feishu" ? "飞书" : provider === "invite" ? "邮箱" : provider;
  return (
    <li className="flex items-center gap-3 px-2.5 py-1.5">
      <span
        className="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider font-meta"
        style={{
          background: "var(--surface)",
          color: "var(--text-mute)",
          border: "1px solid var(--line)",
        }}
      >
        {tag}
      </span>
      <div className="min-w-0 flex-1">
        <div
          className="truncate text-[13px] font-semibold"
          style={{ color: "var(--text)" }}
        >
          {rawName ?? <span style={{ color: "var(--text-mute)" }}>未填名字</span>}
          {rawEmail && (
            <span
              className="ml-2 text-[12px] font-meta font-normal"
              style={{ color: "var(--text-soft)" }}
            >
              {rawEmail}
            </span>
          )}
        </div>
        <div
          className="mt-0.5 truncate text-[11px] font-mono"
          style={{ color: "var(--text-mute)" }}
        >
          {binding.external_id}
          {binding.external_union_id && (
            <span className="ml-1.5">· {binding.external_union_id}</span>
          )}
        </div>
      </div>
      <div className="shrink-0 text-right">
        <span
          className="text-[10.5px] font-bold uppercase tracking-wider font-meta"
          style={{ color: primary ? "var(--text-mute)" : "var(--accent)" }}
        >
          {primary ? "原始身份" : "合并自"}
        </span>
        <div
          className="mt-0.5 text-[11px] font-meta"
          style={{ color: "var(--text-mute)" }}
        >
          {new Date(binding.bound_at * 1000).toLocaleDateString()}
        </div>
      </div>
    </li>
  );
}

function _readBindingName(
  binding: AdminUser["bindings"][number],
): string | null {
  // feishu raw_profile 在迁移时落入了 {"name":"...","avatar_url":...,"union_id":...}
  // invite binding raw_profile 是 null（建邀请时没存）—— 邀请用户的名字
  // 我们用 pivot_user.display_name 兜底，但那不在 binding 视图里，所以这里返 null。
  const raw = binding.raw_profile;
  if (raw && typeof raw.name === "string") {
    return raw.name;
  }
  return null;
}

function _readBindingEmail(
  binding: AdminUser["bindings"][number],
): string | null {
  // invite provider 把邮箱直接当 external_id 存（参见 server/api/auth_invite.py
  // 的 bindings.bind(provider='invite', external_id=email, ...)）。
  // feishu raw_profile 不带 email（飞书 OAuth 默认 scope 不返回 email），
  // 所以飞书 binding 这里返 null。
  if (binding.provider === "invite") {
    return binding.external_id;
  }
  const raw = binding.raw_profile;
  if (raw && typeof raw.email === "string") {
    return raw.email;
  }
  return null;
}

const titleStyle: React.CSSProperties = {
  fontFamily: "var(--font-serif)",
  fontWeight: 600,
  letterSpacing: "var(--letter-tight)",
  color: "var(--text)",
};

const mutedStyle: React.CSSProperties = {
  color: "var(--text-mute)",
  fontSize: "13px",
};
