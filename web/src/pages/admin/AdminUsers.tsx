import { useCallback, useEffect, useState } from "react";
import {
  ChevronDown,
  KeyRound,
  Pause,
  Play,
  Shield,
  Trash2,
  Undo2,
} from "lucide-react";
import {
  changeUserRoles,
  fetchMe,
  listAdminRoles,
  listAdminUsers,
  markUserDeleted,
  resetUserPassword,
  restoreUser,
  resumeUser,
  suspendUser,
  type AdminRoleOption,
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function AdminUsers() {
  const [items, setItems] = useState<AdminUser[]>([]);
  const [roleNameByKey, setRoleNameByKey] = useState<Map<string, string>>(new Map());
  const [me, setMe] = useState<Me | null>(null);
  const [search, setSearch] = useState("");
  const [includeDeleted, setIncludeDeleted] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [users, roles] = await Promise.all([
        listAdminUsers({
          include_deleted: includeDeleted,
          search: search.trim() || undefined,
        }),
        listAdminRoles(),
      ]);
      setItems(users.items);
      setRoleNameByKey(new Map(roles.map((role) => [role.role, roleDisplayName(role)])));
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
        <h1 className="m-0 text-[22px]" style={titleStyle}>
          用户列表
        </h1>
        <div className="flex flex-1 items-center justify-end gap-3">
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

      {loading && <p style={mutedStyle}>加载中...</p>}
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
          <UserRow
            key={u.id}
            user={u}
            me={me}
            roleNameByKey={roleNameByKey}
            onChanged={reload}
          />
        ))}
      </ul>
    </div>
  );
}

function UserRow({
  user,
  me,
  roleNameByKey,
  onChanged,
}: {
  user: AdminUser;
  me: Me | null;
  roleNameByKey: Map<string, string>;
  onChanged: () => void;
}) {
  const isSelf = me?.id === user.id;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmKind, setConfirmKind] =
    useState<"delete" | "restore" | "reset" | "roles" | null>(null);

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
            <div className="flex flex-wrap items-center gap-2">
              <span
                className="truncate text-[14px] font-semibold"
                style={{ color: "var(--text)" }}
              >
                {user.display_name}
              </span>
              <UserStatusBadge status={user.status} />
              {user.roles?.includes("admin") && <RoleChip label="管理员" strong />}
              {isSelf && (
                <span className="text-[10.5px] font-meta" style={mutedStyle}>
                  （你）
                </span>
              )}
            </div>
            <div className="mt-0.5 truncate text-[12px] font-meta" style={mutedStyle}>
              {user.email || "无邮箱"}
              {user.last_login_at && (
                <> · 上次登录 {new Date(user.last_login_at * 1000).toLocaleString()}</>
              )}
            </div>
            <div className="mt-1 flex flex-wrap gap-1">
              {(user.roles ?? []).filter((role) => role !== "admin").map((role) => (
                <RoleChip key={role} label={roleNameByKey.get(role) ?? role} />
              ))}
            </div>
            <BindingChips bindings={user.bindings} />
            {user.status_note && (
              <div className="mt-0.5 truncate text-[12px]" style={{ color: "var(--text-soft)" }}>
                备注：{user.status_note}
              </div>
            )}
          </div>
        </div>

        <div className="flex shrink-0 items-center">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                disabled={busy}
                className="h-8 gap-1 rounded-[var(--r-sm)] px-2.5 text-[12.5px]"
                aria-label="用户操作"
              >
                操作
                <ChevronDown className="h-3.5 w-3.5" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-[160px]">
              {user.status === "active" && (
                <DropdownMenuItem
                  disabled={isSelf}
                  onSelect={() => guard(async () => {
                    await suspendUser(user.id);
                  })}
                >
                  <Pause className="h-3.5 w-3.5" />
                  暂停
                </DropdownMenuItem>
              )}
              {user.status === "suspended" && (
                <DropdownMenuItem
                  onSelect={() => guard(async () => {
                    await resumeUser(user.id);
                  })}
                >
                  <Play className="h-3.5 w-3.5" />
                  恢复
                </DropdownMenuItem>
              )}
              {user.status === "deleted" && (
                <DropdownMenuItem onSelect={() => setConfirmKind("restore")}>
                  <Undo2 className="h-3.5 w-3.5" />
                  撤销停用
                </DropdownMenuItem>
              )}
              <DropdownMenuItem
                disabled={isSelf || user.status !== "active"}
                onSelect={() => setConfirmKind("roles")}
              >
                <Shield className="h-3.5 w-3.5" />
                修改角色
              </DropdownMenuItem>
              {user.providers.includes("invite") && (
                <DropdownMenuItem onSelect={() => setConfirmKind("reset")}>
                  <KeyRound className="h-3.5 w-3.5" />
                  重置密码
                </DropdownMenuItem>
              )}
              {user.status !== "deleted" && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    disabled={isSelf}
                    onSelect={() => setConfirmKind("delete")}
                    style={{ color: "var(--danger-500)" }}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    停用
                  </DropdownMenuItem>
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
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
      <EditRolesDialog
        open={confirmKind === "roles"}
        user={user}
        onClose={() => setConfirmKind(null)}
        onConfirm={(roles) =>
          guard(async () => {
            await changeUserRoles(user.id, roles);
            setConfirmKind(null);
          })
        }
      />
    </li>
  );
}

function EditRolesDialog({
  open,
  user,
  onClose,
  onConfirm,
}: {
  open: boolean;
  user: AdminUser;
  onClose: () => void;
  onConfirm: (roles: string[]) => void;
}) {
  const [roles, setRoles] = useState<AdminRoleOption[]>([]);
  const [selected, setSelected] = useState<string[]>(user.roles ?? []);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setSelected(user.roles ?? []);
    setError(null);
    setLoading(true);
    listAdminRoles()
      .then((items) => setRoles(items.filter((item) => item.is_active)))
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  }, [open, user.roles]);

  const toggle = (role: string) => {
    setSelected((current) =>
      current.includes(role)
        ? current.filter((item) => item !== role)
        : [...current, role],
    );
  };

  const canSave = selected.length > 0;

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>修改角色</DialogTitle>
          <DialogDescription>
            为 {user.display_name} 选择一个或多个角色。
          </DialogDescription>
        </DialogHeader>
        {error && (
          <p className="text-[12px]" style={{ color: "var(--danger-500)" }}>
            {error}
          </p>
        )}
        {loading ? (
          <p className="text-sm" style={mutedStyle}>加载中...</p>
        ) : (
          <div className="max-h-[360px] space-y-2 overflow-auto pr-1">
            {roles.map((role) => (
              <label
                key={role.role}
                className="flex items-center justify-between gap-3 rounded-[var(--r-sm)] border border-[var(--line)] px-3 py-2"
              >
                <span className="flex min-w-0 items-center gap-2">
                  <input
                    type="checkbox"
                    checked={selected.includes(role.role)}
                    onChange={() => toggle(role.role)}
                  />
                  <span className="truncate text-sm font-medium text-[var(--text)]">
                    {roleDisplayName(role)}
                  </span>
                </span>
                <span className="shrink-0 text-xs text-[var(--text-mute)]">
                  {role.kind === "system" ? "系统" : "业务"} · {role.user_count}人
                </span>
              </label>
            ))}
          </div>
        )}
        {!canSave && (
          <p className="text-[12px]" style={{ color: "var(--danger-500)" }}>
            至少保留一个角色。
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button onClick={() => onConfirm(selected)} disabled={!canSave || loading}>
            保存
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function roleDisplayName(role: AdminRoleOption): string {
  return role.label || role.name || role.role;
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
            停用后该用户不能再登录。请输入用户 display_name 确认操作。
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <div>
            <Label className="text-[12.5px]">输入 “{user.display_name}” 以确认</Label>
            <Input
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              autoFocus
            />
          </div>
          <div>
            <Label className="text-[12.5px]">备注</Label>
            <Input value={note} onChange={(e) => setNote(e.target.value)} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button
            disabled={!enabled}
            onClick={() => onConfirm(note.trim() || undefined)}
            style={{ background: "var(--danger-500)", color: "white" }}
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
          <DialogTitle>恢复用户</DialogTitle>
          <DialogDescription>
            请输入用户 display_name 确认恢复。
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <div>
            <Label className="text-[12.5px]">输入 “{user.display_name}” 以确认</Label>
            <Input
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              autoFocus
            />
          </div>
          <div>
            <Label className="text-[12.5px]">备注</Label>
            <Input value={note} onChange={(e) => setNote(e.target.value)} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button disabled={!enabled} onClick={() => onConfirm(note.trim() || undefined)}>
            确认恢复
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
  onConfirm: (password: string) => void;
}) {
  const [password, setPassword] = useState("");
  useEffect(() => {
    if (!open) setPassword("");
  }, [open]);
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>重置密码</DialogTitle>
          <DialogDescription>
            为 {user.display_name} 设置新的邀请登录密码。
          </DialogDescription>
        </DialogHeader>
        <Input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="至少 6 位"
        />
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button disabled={password.length < 6} onClick={() => onConfirm(password)}>
            确认重置
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RoleChip({ label, strong = false }: { label: string; strong?: boolean }) {
  return (
    <span
      className="rounded-full px-2 py-0.5 text-[10.5px] font-bold tracking-wider font-meta"
      style={{
        background: strong ? "var(--accent-bg)" : "var(--surface-alt)",
        color: strong ? "var(--accent)" : "var(--text-soft)",
        border: strong ? "1px solid var(--accent)" : "1px solid var(--line)",
      }}
    >
      {label}
    </span>
  );
}

function BindingChips({
  bindings,
}: {
  bindings: AdminUser["bindings"];
}) {
  if (!bindings?.length) return null;
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {bindings.map((b) => (
        <span
          key={b.id}
          className="rounded-full border border-[var(--line)] px-2 py-0.5 text-[10.5px] font-meta"
          style={{ color: "var(--text-mute)" }}
        >
          {b.provider}
        </span>
      ))}
    </div>
  );
}

const titleStyle: React.CSSProperties = {
  color: "var(--text)",
  fontFamily: "var(--font-serif)",
};

const mutedStyle: React.CSSProperties = { color: "var(--text-mute)" };
