import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Mail, UserPlus, Users } from "lucide-react";
import { listAdminUsers, listApplications, listInvites } from "@/api";
import { Card, CardContent } from "@/components/ui/card";

/** Default landing page when admin opens /admin (no sub-route).
 *  Three small KPI tiles for the 用户管理 group + a hint to use the
 *  sidebar to reach the rest. Doesn't try to summarize every section
 *  (workspace / AI etc. don't have a meaningful "count"). */
export function AdminHome() {
  const [stats, setStats] = useState<{
    pending_applications: number;
    active_users: number;
    pending_invites: number;
  } | null>(null);

  useEffect(() => {
    Promise.all([
      listApplications("pending").catch(() => ({ items: [] })),
      listAdminUsers({ include_deleted: false }).catch(() => ({ items: [] })),
      listInvites(false).catch(() => ({ items: [] })),
    ]).then(([apps, users, invites]) => {
      const now = Date.now() / 1000;
      const liveInvites = invites.items.filter(
        (i) => i.used_at == null && i.expires_at > now,
      );
      const activeUsers = users.items.filter((u) => u.status === "active");
      setStats({
        pending_applications: apps.items.length,
        active_users: activeUsers.length,
        pending_invites: liveInvites.length,
      });
    });
  }, []);

  return (
    <div className="mx-auto max-w-4xl p-8">
      <header className="mb-6">
        <div
          className="mb-2 text-[10.5px] font-bold uppercase tracking-[0.22em] font-meta"
          style={{ color: "var(--accent)" }}
        >
          管理员后台
        </div>
        <h1
          className="m-0 text-[28px]"
          style={{
            fontFamily: "var(--font-serif)",
            fontWeight: 600,
            letterSpacing: "var(--letter-tight)",
            color: "var(--text)",
          }}
        >
          欢迎，管理员
        </h1>
        <p
          className="mt-2 text-[14px] leading-[1.65]"
          style={{
            fontFamily: "var(--font-serif)",
            color: "var(--text-soft)",
          }}
        >
          左侧选择菜单进入对应页面：
          <strong style={{ color: "var(--text)" }}> 用户管理 </strong>
          管申请 / 用户 / 邀请；
          <strong style={{ color: "var(--text)" }}> 系统设置 </strong>
          管数据仓库、AI 助手、日报、联系人同步、Matter 评分等。
        </p>
      </header>

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <KPI
          icon={<UserPlus className="h-5 w-5" />}
          label="待审批申请"
          value={stats?.pending_applications ?? "…"}
          to="/admin/applications"
          highlight={(stats?.pending_applications ?? 0) > 0}
        />
        <KPI
          icon={<Users className="h-5 w-5" />}
          label="活跃用户"
          value={stats?.active_users ?? "…"}
          to="/admin/users"
        />
        <KPI
          icon={<Mail className="h-5 w-5" />}
          label="待使用邀请"
          value={stats?.pending_invites ?? "…"}
          to="/admin/invites"
        />
      </section>
    </div>
  );
}

function KPI({
  icon,
  label,
  value,
  to,
  highlight = false,
}: {
  icon: React.ReactNode;
  label: string;
  value: number | string;
  to: string;
  highlight?: boolean;
}) {
  return (
    <Link to={to} className="block">
      <Card
        className="border-[var(--line)] shadow-none transition-colors hover:border-[var(--accent)]"
        style={{
          background: highlight ? "var(--accent-bg)" : "var(--surface)",
        }}
      >
        <CardContent className="flex items-center gap-4 p-5">
          <div
            className="flex h-10 w-10 items-center justify-center rounded-[var(--r-sm)]"
            style={{
              background: highlight ? "var(--accent)" : "var(--surface-alt)",
              color: highlight ? "var(--accent-ink)" : "var(--accent)",
            }}
          >
            {icon}
          </div>
          <div className="min-w-0">
            <div
              className="text-[11px] font-bold uppercase tracking-[0.18em] font-meta"
              style={{ color: "var(--text-mute)" }}
            >
              {label}
            </div>
            <div
              className="mt-1 text-[24px]"
              style={{
                fontFamily: "var(--font-serif)",
                fontWeight: 600,
                color: "var(--text)",
              }}
            >
              {value}
            </div>
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}
