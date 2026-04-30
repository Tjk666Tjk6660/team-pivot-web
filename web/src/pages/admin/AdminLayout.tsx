import { useEffect, useState } from "react";
import { Link, NavLink, Outlet } from "react-router-dom";
import { ArrowLeft, ChevronDown, ChevronRight } from "lucide-react";
import { Toaster } from "sonner";
import { fetchMe, type Me } from "@/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/** Shell for /admin/* routes:
 *  - left sidebar with grouped, tree-style navigation
 *  - top bar with "back to Pivot" + admin identity
 *  - role guard: non-admin / unauthenticated visitors see RoleDeniedNotice
 *  - sub-routes render through <Outlet />
 *
 * The sidebar groups two clusters:
 *   1. 用户管理 — applications / users / invites (per /admin/applications, etc.)
 *   2. 系统设置 — workspace / markdown / daily-report / ai / contacts / scoring
 *
 * Adding a new admin section means: drop a Route under <Outlet/> in App.tsx and
 * add one NavItem entry below. No new top-bar tabs to maintain.
 */
export function AdminLayout() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);

  useEffect(() => {
    fetchMe().then(setMe).catch(() => setMe(null));
  }, []);

  const isAdmin = me?.role === "admin" && me.status === "active";

  if (me === undefined) {
    return (
      <div
        className="grid min-h-screen place-items-center"
        style={{ background: "var(--bg-alt)" }}
      >
        <p style={{ color: "var(--text-mute)" }}>加载中…</p>
      </div>
    );
  }

  if (!isAdmin) {
    return <RoleDeniedNotice me={me} />;
  }

  return (
    <div
      className="flex min-h-screen"
      style={{ background: "var(--bg)" }}
    >
      <Toaster position="top-center" richColors />
      <aside
        className="flex w-[240px] shrink-0 flex-col"
        style={{
          background: "var(--surface-alt)",
          borderRight: "1px solid var(--line)",
        }}
      >
        <SidebarHeader me={me} />
        <nav className="flex-1 overflow-y-auto px-3 py-4">
          <ul className="mb-4 flex flex-col gap-0.5">
            <NavItem to="/admin">首页</NavItem>
          </ul>
          <NavGroup title="用户管理">
            <NavItem to="/admin/applications">加入申请</NavItem>
            <NavItem to="/admin/users">用户</NavItem>
            <NavItem to="/admin/invites">邀请</NavItem>
          </NavGroup>
          <NavGroup title="系统设置">
            <NavItem to="/admin/workspace">数据仓库</NavItem>
            <NavItem to="/admin/markdown">正文主题</NavItem>
            <NavItem to="/admin/daily-report">日报</NavItem>
            <NavItem to="/admin/ai">AI 助手</NavItem>
            {/* 联系人同步只对绑了飞书的 admin 显示 —— 没飞书 binding
                的邀请 admin 没法 OAuth 触发个人级 token，且这个能力本身
                跟"飞书企业通讯录"绑定，邮箱用户无意义。 */}
            {me.providers.includes("feishu") && (
              <NavItem to="/admin/contacts">联系人同步</NavItem>
            )}
            <NavItem to="/admin/scoring">Matter 评分</NavItem>
          </NavGroup>
        </nav>
        <div
          className="px-3 py-3"
          style={{ borderTop: "1px solid var(--line)" }}
        >
          <Link
            to="/"
            className="flex items-center gap-1.5 text-[12.5px] font-meta hover:text-[var(--text)]"
            style={{ color: "var(--text-mute)" }}
          >
            <ArrowLeft className="h-3.5 w-3.5" /> 返回 Pivot
          </Link>
        </div>
      </aside>

      <main className="min-w-0 flex-1">
        <Outlet />
      </main>
    </div>
  );
}

function SidebarHeader({ me }: { me: Me }) {
  return (
    <div
      className="flex items-center gap-3 px-4 py-4"
      style={{ borderBottom: "1px solid var(--line)" }}
    >
      <img
        src="/pivot-logo.png"
        alt=""
        className="h-8 w-8 shrink-0 rounded-[var(--r-sm)] object-cover object-top"
        style={{
          background: "var(--surface)",
          border: "1px solid var(--line)",
        }}
      />
      <div className="min-w-0">
        <div
          className="text-[10.5px] font-bold uppercase tracking-[0.18em] font-meta"
          style={{ color: "var(--text-mute)" }}
        >
          管理员后台
        </div>
        <div
          className="mt-0.5 truncate text-[13px] font-semibold"
          style={{ color: "var(--text)" }}
          title={me.email ?? me.display_name}
        >
          {me.display_name}
        </div>
      </div>
    </div>
  );
}

function NavGroup({
  title,
  children,
  storageKey,
}: {
  title: string;
  children: React.ReactNode;
  /** localStorage key that remembers the open/closed state across reloads.
   *  Defaults to title-derived key so each group has its own slot. */
  storageKey?: string;
}) {
  const key = `admin.nav.${storageKey ?? title}`;
  const [open, setOpen] = useState<boolean>(() => {
    try {
      const v = localStorage.getItem(key);
      return v == null ? true : v === "1";
    } catch {
      return true;
    }
  });
  const toggle = () => {
    setOpen((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(key, next ? "1" : "0");
      } catch {
        /* ignore (private window etc.) */
      }
      return next;
    });
  };
  return (
    <div className="mb-4">
      <button
        type="button"
        onClick={toggle}
        className="flex w-full items-center gap-1.5 rounded-[var(--r-sm)] px-2 py-1.5 text-left text-[15px] font-semibold transition-colors hover:bg-[var(--surface)]"
        style={{
          fontFamily: "var(--font-serif)",
          color: "var(--text-mute)",
          letterSpacing: "var(--letter-tight)",
        }}
        aria-expanded={open}
      >
        {open ? (
          <ChevronDown className="h-4 w-4 shrink-0" />
        ) : (
          <ChevronRight className="h-4 w-4 shrink-0" />
        )}
        <span className="flex-1">{title}</span>
      </button>
      {open && (
        <ul className="mt-0.5 flex flex-col gap-0.5 pl-5">{children}</ul>
      )}
    </div>
  );
}

function NavItem({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <li>
      <NavLink
        to={to}
        end
        className={({ isActive }) =>
          [
            "block rounded-[var(--r-sm)] px-2.5 py-1.5 text-[13.5px] transition-colors",
            isActive ? "font-semibold" : "font-normal",
            isActive ? "" : "hover:bg-[var(--surface)]",
          ].join(" ")
        }
        style={({ isActive }) => ({
          fontFamily: "var(--font-serif)",
          color: isActive ? "var(--accent-ink)" : "var(--text-soft)",
          background: isActive ? "var(--accent)" : "transparent",
        })}
      >
        {children}
      </NavLink>
    </li>
  );
}

function RoleDeniedNotice({ me }: { me: Me | null }) {
  return (
    <div
      className="grid min-h-screen place-items-center px-6"
      style={{ background: "var(--bg-alt)" }}
    >
      <Card className="w-full max-w-2xl border-[var(--line)] shadow-[var(--shadow-sm)]">
        <CardHeader>
          <CardTitle
            className="text-[20px]"
            style={{
              fontFamily: "var(--font-serif)",
              color: "var(--danger-500)",
            }}
          >
            需要管理员权限
          </CardTitle>
          <CardDescription>
            {me === null
              ? "你尚未登录。请先登录后再访问管理面板。"
              : me.status !== "active"
                ? "账号当前不处于活跃状态，无法进入管理面板。"
                : "这个页面仅管理员可访问。如需协助，请联系当前管理员把你升级为 admin。"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button asChild>
            <Link to="/">返回首页</Link>
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
