import { useCallback, useEffect, useMemo, useState } from "react";
import { Plus, Shield, Users } from "lucide-react";
import {
  createAdminRole,
  listAdminRoles,
  listAdminUsers,
  setAdminRoleMembers,
  type AdminRoleOption,
  type AdminUser,
} from "@/api";
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
import { cn } from "@/lib/utils";

export function AdminRoles() {
  const [roles, setRoles] = useState<AdminRoleOption[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [selectedRole, setSelectedRole] = useState<string | null>(null);
  const [memberIds, setMemberIds] = useState<string[]>([]);
  const [createOpen, setCreateOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async (
    preferredRole?: string | null,
    showLoading = false,
  ) => {
    if (showLoading) setLoading(true);
    setError(null);
    try {
      const [roleItems, userResult] = await Promise.all([
        listAdminRoles(),
        listAdminUsers({ include_deleted: false }),
      ]);
      setRoles(roleItems);
      setUsers(userResult.items);
      const nextSelected = preferredRole ?? roleItems[0]?.role ?? null;
      setSelectedRole(nextSelected);
      if (nextSelected) {
        setMemberIds(
          userResult.items
            .filter((user) => user.roles?.includes(nextSelected))
            .map((user) => user.id),
        );
      } else {
        setMemberIds([]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload(null, true);
  }, [reload]);

  const activeRole = useMemo(
    () => roles.find((role) => role.role === selectedRole) ?? null,
    [roles, selectedRole],
  );

  const selectRole = (role: string) => {
    setSelectedRole(role);
    setMemberIds(
      users.filter((user) => user.roles?.includes(role)).map((user) => user.id),
    );
  };

  const createRole = async (name: string) => {
    setSaving(true);
    setError(null);
    try {
      await createAdminRole(name);
      setCreateOpen(false);
      await reload(name);
    } catch (err) {
      throw err;
    } finally {
      setSaving(false);
    }
  };

  const toggleMember = (userId: string) => {
    setMemberIds((current) =>
      current.includes(userId)
        ? current.filter((id) => id !== userId)
        : [...current, userId],
    );
  };

  const saveMembers = async () => {
    if (!activeRole) return;
    setSaving(true);
    setError(null);
    try {
      await setAdminRoleMembers(activeRole.role, memberIds);
      await reload(activeRole.role);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mx-auto max-w-6xl p-6">
      <header className="mb-5 flex flex-wrap items-center gap-3">
        <h1 className="m-0 text-[22px]" style={{ color: "var(--text)" }}>
          角色管理
        </h1>
      </header>

      {error && (
        <p className="mb-3 text-[13px]" style={{ color: "var(--danger-500)" }}>
          {error}
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
        <section className="rounded-[var(--r-md)] border border-[var(--line)] bg-[var(--surface)] p-4">
          <div className="mb-3 flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Shield className="h-4 w-4 text-[var(--accent)]" />
              <h2 className="text-sm font-semibold text-[var(--text)]">角色</h2>
            </div>
            <Button
              type="button"
              size="sm"
              onClick={() => setCreateOpen(true)}
              disabled={saving}
            >
              <Plus className="h-4 w-4" />
              新增角色
            </Button>
          </div>

          {loading ? (
            <p className="text-sm text-[var(--text-mute)]">加载中...</p>
          ) : (
            <div className="space-y-1">
              {roles.map((role) => (
                <button
                  key={role.role}
                  type="button"
                  onClick={() => selectRole(role.role)}
                  className={cn(
                    "flex w-full items-center justify-between rounded-[var(--r-sm)] px-3 py-2 text-left text-sm",
                    selectedRole === role.role
                      ? "bg-[var(--accent-bg)] text-[var(--accent)]"
                      : "text-[var(--text)] hover:bg-[var(--surface-alt)]",
                  )}
                >
                  <span className="min-w-0 truncate">{role.role}</span>
                  <span className="shrink-0 text-xs text-[var(--text-mute)]">
                    {role.kind === "system" ? "系统" : "业务"} · {role.user_count}人
                  </span>
                </button>
              ))}
            </div>
          )}
        </section>

        <section className="rounded-[var(--r-md)] border border-[var(--line)] bg-[var(--surface)] p-4">
          {activeRole ? (
            <>
              <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <Users className="h-4 w-4 text-[var(--accent)]" />
                    <h2 className="text-base font-semibold text-[var(--text)]">
                      {activeRole.role}
                    </h2>
                  </div>
                  <p className="mt-1 text-sm text-[var(--text-mute)]">
                    选择属于这个角色的用户。保存后会更新用户的 role 数组。
                  </p>
                </div>
                <Button type="button" onClick={saveMembers} disabled={saving}>
                  保存成员
                </Button>
              </div>

              <div className="grid gap-2 md:grid-cols-2">
                {users.map((user) => (
                  <label
                    key={user.id}
                    className="flex items-center gap-3 rounded-[var(--r-sm)] border border-[var(--line)] px-3 py-2"
                  >
                    <input
                      type="checkbox"
                      checked={memberIds.includes(user.id)}
                      onChange={() => toggleMember(user.id)}
                      disabled={saving}
                    />
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-[var(--text)]">
                        {user.display_name}
                      </div>
                      <div className="truncate text-xs text-[var(--text-mute)]">
                        {user.roles?.join("、") || "无角色"}
                      </div>
                    </div>
                  </label>
                ))}
              </div>

              {activeRole.role === "admin" && (
                <p className="mt-3 text-xs text-[var(--text-mute)]">
                  admin 是系统角色，保存时会保护至少一个 active admin。
                </p>
              )}
            </>
          ) : (
            <div className="py-12 text-center text-sm text-[var(--text-mute)]">
              先选择或新增一个角色。
            </div>
          )}
        </section>
      </div>

      <CreateRoleDialog
        open={createOpen}
        saving={saving}
        onClose={() => setCreateOpen(false)}
        onConfirm={createRole}
      />
    </div>
  );
}

function CreateRoleDialog({
  open,
  saving,
  onClose,
  onConfirm,
}: {
  open: boolean;
  saving: boolean;
  onClose: () => void;
  onConfirm: (name: string) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setName("");
      setError(null);
    }
  }, [open]);

  const submit = async () => {
    const trimmedName = name.trim();
    if (!trimmedName) {
      setError("请输入角色名称");
      return;
    }
    setError(null);
    try {
      await onConfirm(trimmedName);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>新增角色</DialogTitle>
          <DialogDescription>
            创建后会出现在角色列表和可见范围选择器里，成员可以稍后在右侧维护。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="role-name">角色名称</Label>
            <Input
              id="role-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="例如：行政部门、技术部门"
              disabled={saving}
              autoFocus
            />
          </div>
          {error && (
            <p className="text-[13px]" style={{ color: "var(--danger-500)" }}>
              {error}
            </p>
          )}
        </div>

        <DialogFooter>
          <Button type="button" variant="ghost" onClick={onClose} disabled={saving}>
            取消
          </Button>
          <Button type="button" onClick={submit} disabled={saving || !name.trim()}>
            创建
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
