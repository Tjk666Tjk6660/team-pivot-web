import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Mail, UserPlus, Users } from "lucide-react";
import { toast } from "sonner";
import {
  listAdminUsers,
  listApplications,
  listInvites,
} from "@/api";
import { Card, CardContent } from "@/components/ui/card";
import { AISettingsSection, WorkspaceConfigSection } from "@/pages/AdminPage";
import { PageShell } from "./_PageShell";

/** /admin 默认页：
 *  - 顶部欢迎 + 上手指引
 *  - 关键初始化项 inline 展开（数据仓库 + AI 助手）—— 首次部署必须
 *    配置完这两项 Pivot 才能跑起来，所以放在 admin 一进后台就能看见
 *  - 底部 KPI 快捷卡片（待审批 / 活跃用户 / 待使用邀请） */
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

  const onAdminLost = () =>
    toast.error("管理员权限已失效，请刷新或重新登录");

  return (
    <PageShell title="管理员后台">
      <p
        className="text-[14px] leading-[1.65]"
        style={{
          fontFamily: "var(--font-serif)",
          color: "var(--text-soft)",
          margin: 0,
        }}
      >
        左侧菜单按分组组织：
        <strong style={{ color: "var(--text)" }}> 用户管理 </strong>
        管申请 / 用户 / 邀请；
        <strong style={{ color: "var(--text)" }}> 系统设置 </strong>
        管数据仓库、AI 助手、日报、Matter 评分等。
        <br />
        <span style={{ color: "var(--text-mute)" }}>
          首次部署请先把下方两项「数据仓库」与「AI 助手」配置好，Pivot 才能正常运行。
        </span>
      </p>

      <section>
        <div
          className="mb-3 text-[10.5px] font-bold uppercase tracking-[0.22em] font-meta"
          style={{ color: "var(--text-mute)" }}
        >
          快捷入口
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
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
        </div>
      </section>

      <section>
        <SectionTitle index={1} hint="必填" title="数据仓库" />
        <WorkspaceConfigSection onAdminLost={onAdminLost} />
      </section>

      <section>
        <SectionTitle index={2} hint="必填" title="AI 助手" />
        <AISettingsSection onAdminLost={onAdminLost} />
      </section>
    </PageShell>
  );
}

function SectionTitle({
  index,
  hint,
  title,
}: {
  index: number;
  hint: string;
  title: string;
}) {
  return (
    <div className="mb-3 flex items-baseline gap-3">
      <span
        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[12px] font-bold"
        style={{
          background: "var(--accent)",
          color: "var(--accent-ink)",
        }}
      >
        {index}
      </span>
      <h2
        className="m-0 text-[20px]"
        style={{
          fontFamily: "var(--font-serif)",
          fontWeight: 600,
          color: "var(--text)",
        }}
      >
        {title}
      </h2>
      <span
        className="text-[10.5px] font-bold uppercase tracking-[0.18em] font-meta"
        style={{ color: "var(--danger-500)" }}
      >
        {hint}
      </span>
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
