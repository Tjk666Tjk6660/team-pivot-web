import type { AdminUser } from "@/api";

const STATUS_LABEL: Record<AdminUser["status"], string> = {
  active: "活跃",
  suspended: "已暂停登录",
  deleted: "已注销",
};

const STATUS_COLOR: Record<AdminUser["status"], { bg: string; fg: string; border: string }> = {
  active: {
    bg: "var(--accent-bg)",
    fg: "var(--accent)",
    border: "var(--accent)",
  },
  suspended: {
    bg: "color-mix(in srgb, var(--warning-500, #d97706) 12%, transparent)",
    fg: "var(--warning-500, #d97706)",
    border: "var(--warning-500, #d97706)",
  },
  deleted: {
    bg: "color-mix(in srgb, var(--danger-500) 10%, transparent)",
    fg: "var(--danger-500)",
    border: "var(--danger-500)",
  },
};

export function UserStatusBadge({ status }: { status: AdminUser["status"] }) {
  const c = STATUS_COLOR[status];
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-bold tracking-wider font-meta"
      style={{
        background: c.bg,
        color: c.fg,
        border: `1px solid ${c.border}`,
      }}
    >
      {STATUS_LABEL[status]}
    </span>
  );
}
