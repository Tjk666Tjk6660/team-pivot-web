import { useEffect, useMemo, useState } from "react";
import { Check, ChevronRight, Search, Shield, Users, X } from "lucide-react";
import {
  fetchVisibilityOptions,
  type VisibilityOptions,
  type VisibilityScope,
  type VisibilityUserOption,
} from "@/api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

type Props = {
  category?: string;
  value: VisibilityScope;
  onChange: (value: VisibilityScope) => void;
  disabled?: boolean;
  allowUsers?: boolean;
  allowedRoles?: string[];
  publicLabel?: string;
  restrictedLabel?: string;
  dialogTitle?: string;
};

const PUBLIC_SCOPE: VisibilityScope = { mode: "public", roles: [], user_ids: [] };

export function VisibilityScopePicker({
  category,
  value,
  onChange,
  disabled,
  allowUsers = true,
  allowedRoles,
  publicLabel = "全部用户",
  restrictedLabel = "指定范围",
  dialogTitle = "选择可见范围",
}: Props) {
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<VisibilityOptions | null>(null);
  const [draft, setDraft] = useState<VisibilityScope>(value);
  const [query, setQuery] = useState("");
  const [activeRole, setActiveRole] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setDraft(allowUsers ? value : { ...value, user_ids: [] });
    setActiveRole(null);
    void fetchVisibilityOptions(category).then(setOptions);
  }, [allowUsers, category, open, value]);

  const allowedRoleSet = useMemo(
    () => allowedRoles ? new Set(allowedRoles) : null,
    [allowedRoles],
  );
  const selectedCount = value.mode === "public"
    ? 0
    : value.roles.length + (allowUsers ? value.user_ids.length : 0);
  const summary = value.mode === "public"
    ? publicLabel
    : `${restrictedLabel}：${selectedCount} 个`;

  const roleRows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (options?.roles ?? []).filter((item) =>
      (!allowedRoleSet || allowedRoleSet.has(item.role)) &&
      (!q || `${roleDisplayName(item)} ${item.role}`.toLowerCase().includes(q)),
    );
  }, [allowedRoleSet, options, query]);
  const roleNameByKey = useMemo(
    () => new Map((options?.roles ?? []).map((item) => [item.role, roleDisplayName(item)])),
    [options],
  );

  const userRows = useMemo(() => {
    if (!allowUsers) return [];
    const q = query.trim().toLowerCase();
    const rows = activeRole
      ? options?.roles.find((item) => item.role === activeRole)?.users ?? []
      : allowedRoleSet
        ? dedupeUsers(
            (options?.roles ?? [])
              .filter((item) => allowedRoleSet.has(item.role))
              .flatMap((item) => item.users),
          )
        : options?.users ?? [];
    return rows.filter((item) => {
      const label = `${item.display_name} ${item.pinyin ?? ""}`.toLowerCase();
      return !q || label.includes(q);
    });
  }, [activeRole, allowUsers, allowedRoleSet, options, query]);

  const toggleRole = (role: string) => {
    const roles = draft.roles.includes(role)
      ? draft.roles.filter((item) => item !== role)
      : [...draft.roles, role];
    setDraft({
      ...draft,
      mode: "restricted",
      roles,
      user_ids: allowUsers ? draft.user_ids : [],
    });
  };
  const toggleUser = (id: string) => {
    const user_ids = draft.user_ids.includes(id)
      ? draft.user_ids.filter((item) => item !== id)
      : [...draft.user_ids, id];
    setDraft({ ...draft, mode: "restricted", user_ids });
  };

  const confirmDraft = () => {
    const next: VisibilityScope =
      draft.roles.length || (allowUsers && draft.user_ids.length)
        ? {
            ...draft,
            mode: "restricted",
            user_ids: allowUsers ? draft.user_ids : [],
          }
        : PUBLIC_SCOPE;
    onChange(next);
    setOpen(false);
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          variant={value.mode === "public" ? "default" : "outline"}
          size="sm"
          disabled={disabled}
          onClick={() => onChange(PUBLIC_SCOPE)}
        >
          <Users className="h-3.5 w-3.5" />
          {publicLabel}
        </Button>
        <Button
          type="button"
          variant={value.mode === "restricted" ? "default" : "outline"}
          size="sm"
          disabled={disabled}
          onClick={() => setOpen(true)}
        >
          <Shield className="h-3.5 w-3.5" />
          {restrictedLabel}
        </Button>
        <span className="text-xs text-[var(--text-mute)]">{summary}</span>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-[760px] p-0">
          <DialogHeader className="border-b border-[var(--line)] px-5 py-4">
            <DialogTitle className="text-base">{dialogTitle}</DialogTitle>
          </DialogHeader>
          <div className="grid min-h-[420px] grid-cols-1 md:grid-cols-[1.1fr_0.9fr]">
            <div className="border-b border-[var(--line)] p-4 md:border-b-0 md:border-r">
              <div className="relative mb-3">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--text-fade)]" />
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder={allowUsers ? "搜索用户、角色" : "搜索角色"}
                  className="pl-9"
                />
              </div>
              {activeRole && (
                <button
                  type="button"
                  className="mb-2 text-xs font-medium text-[var(--accent)]"
                  onClick={() => setActiveRole(null)}
                >
                  返回角色列表
                </button>
              )}
              <div className="max-h-[330px] space-y-1 overflow-auto pr-1">
                {!activeRole && roleRows.map((item) => (
                  <div key={item.role} className="flex items-center gap-2 rounded-[var(--r-sm)] px-2 py-2 hover:bg-[var(--surface-alt)]">
                    <input
                      type="checkbox"
                      checked={draft.roles.includes(item.role)}
                      onChange={() => toggleRole(item.role)}
                    />
                    <div className="flex h-7 w-7 items-center justify-center rounded-full bg-[var(--accent)] text-white">
                      <Shield className="h-3.5 w-3.5" />
                    </div>
                    <span className="min-w-0 flex-1 truncate text-sm">{roleDisplayName(item)}</span>
                    {allowUsers && (
                      <button
                        type="button"
                        className="inline-flex items-center gap-1 text-xs text-[var(--accent)]"
                        onClick={() => setActiveRole(item.role)}
                      >
                        下级 <ChevronRight className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </div>
                ))}
                {allowUsers && userRows.map((item) => (
                  <div key={item.id} className="flex items-center gap-2 rounded-[var(--r-sm)] px-2 py-2 hover:bg-[var(--surface-alt)]">
                    <input
                      type="checkbox"
                      checked={draft.user_ids.includes(item.id)}
                      onChange={() => toggleUser(item.id)}
                    />
                    <div className="flex h-7 w-7 items-center justify-center rounded-full bg-[var(--surface-alt)] text-xs font-semibold text-[var(--text-soft)]">
                      {item.display_name.slice(0, 1)}
                    </div>
                    <span className="min-w-0 truncate text-sm">{item.display_name}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="p-4">
              <div className="mb-3 text-sm font-semibold">
                已选：{draft.roles.length + (allowUsers ? draft.user_ids.length : 0)} 个
              </div>
              <div className="space-y-2">
                {draft.roles.map((role) => (
                  <SelectedPill
                    key={role}
                    label={roleNameByKey.get(role) ?? role}
                    onRemove={() => toggleRole(role)}
                  />
                ))}
                {allowUsers && draft.user_ids.map((id) => {
                  const user = options?.users.find((item) => item.id === id);
                  return (
                    <SelectedPill
                      key={id}
                      label={user?.display_name ?? id}
                      onRemove={() => toggleUser(id)}
                    />
                  );
                })}
              </div>
            </div>
          </div>
          <DialogFooter className="border-t border-[var(--line)] px-5 py-4">
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              取消
            </Button>
            <Button type="button" onClick={confirmDraft}>
              <Check className="h-4 w-4" />
              确认
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function roleDisplayName(role: { role: string; name?: string; label?: string }): string {
  return role.label || role.name || role.role;
}

function dedupeUsers(users: VisibilityUserOption[]): VisibilityUserOption[] {
  return Array.from(new Map(users.map((item) => [item.id, item])).values());
}

function SelectedPill({
  label,
  onRemove,
}: {
  label: string;
  onRemove: () => void;
}) {
  return (
    <div className={cn(
      "flex items-center justify-between rounded-[var(--r-sm)]",
      "border border-[var(--line)] bg-[var(--surface-alt)] px-3 py-2 text-sm",
    )}>
      <span className="truncate">{label}</span>
      <button type="button" onClick={onRemove} className="text-[var(--text-mute)]">
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
